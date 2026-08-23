#!/usr/bin/env python3
"""Live two-cycle Camera/LiDAR teardown verification for Task 1.6."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CAMERA_PATH = "/World/MCP_Task_1_6_Camera"
LIDAR_PATH = "/World/MCP_Task_1_6_Lidar"
TARGET_PATH = "/World/MCP_Task_1_6_Target"
LIGHT_PATH = "/World/MCP_Task_1_6_Light"
SCRATCH_PATHS = (CAMERA_PATH, LIDAR_PATH, TARGET_PATH, LIGHT_PATH)
REQUIRED_ENVELOPE_FIELDS = {
    "schema_version",
    "status",
    "code",
    "message",
    "data",
    "warnings",
    "command_id",
    "timing",
    "artifacts",
    "readback",
}


def _payload(result: Any) -> dict[str, Any]:
    text = next(item.text for item in result.content if item.type == "text")
    value = json.loads(text)
    assert set(value) == REQUIRED_ENVELOPE_FIELDS, sorted(set(value) ^ REQUIRED_ENVELOPE_FIELDS)
    return value


async def _delete_if_present(session: ClientSession, prim_path: str) -> None:
    before = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
    if before["status"] != "success":
        return
    deleted = _payload(await session.call_tool("delete_object", {"prim_path": prim_path, "post_delete_updates": 32}))
    assert deleted["status"] == "success", deleted
    after = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
    assert after["status"] == "error", after


async def _ensure_non_playing(session: ClientSession) -> None:
    state = _payload(await session.call_tool("get_simulation_state", {}))
    assert state["status"] == "success", state
    if state["data"]["timeline_state"] == "playing":
        stopped = _payload(await session.call_tool("stop_simulation", {}))
        assert stopped["status"] == "success", stopped


async def _assert_scratch_stage(session: ClientSession) -> None:
    allowed = repr(SCRATCH_PATHS)
    code = f"""
import json
import omni.usd
stage = omni.usd.get_context().get_stage()
allowed = {allowed}
unexpected = []
for prim in stage.TraverseAll():
    path = str(prim.GetPath())
    if (
        path == "/World"
        or path == "/PhysicsScene"
        or path.startswith("/Render")
        or path.startswith("/OmniverseKit")
        or path == "/Environment"
        or path.startswith("/Environment/")
    ):
        continue
    if any(path == root or path.startswith(root + "/") for root in allowed):
        continue
    unexpected.append(path)
print(json.dumps(unexpected))
"""
    response = _payload(await session.call_tool("execute_script", {"code": code}))
    assert response["status"] == "success", response
    lines = [line for line in response["data"]["stdout"].splitlines() if line.strip()]
    unexpected = json.loads(lines[-1])
    assert not unexpected, f"Refusing non-scratch stage with unexpected prims: {unexpected[:20]}"


async def _capture(session: ClientSession, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    last = None
    for _attempt in range(24):
        last = _payload(await session.call_tool(tool, arguments))
        if last["status"] == "success":
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"{tool} did not produce a frame: {last}")


async def _render_products(session: ClientSession) -> dict[str, list[str]]:
    code = f"""
import json
import omni.usd
from pxr import UsdRender
stage = omni.usd.get_context().get_stage()
result = {{{CAMERA_PATH!r}: [], {LIDAR_PATH!r}: []}}
for prim in stage.TraverseAll():
    if not prim.IsA(UsdRender.Product):
        continue
    targets = [str(path) for path in UsdRender.Product(prim).GetCameraRel().GetTargets()]
    for sensor_path in result:
        if sensor_path in targets:
            result[sensor_path].append(str(prim.GetPath()))
print(json.dumps(result, sort_keys=True))
"""
    response = _payload(await session.call_tool("execute_script", {"code": code}))
    assert response["status"] == "success", response
    lines = [line for line in response["data"]["stdout"].splitlines() if line.strip()]
    return json.loads(lines[-1])


async def _create_sensors(session: ClientSession) -> None:
    camera = _payload(
        await session.call_tool(
            "create_camera",
            {
                "prim_path": CAMERA_PATH,
                "position": [7.0, 4.0, 3.0],
                "rotation": [70.0, 0.0, 120.0],
                "resolution": [64, 48],
            },
        )
    )
    assert camera["status"] == "success", camera
    lidar = _payload(
        await session.call_tool(
            "create_lidar",
            {
                "prim_path": LIDAR_PATH,
                "position": [0.0, 0.0, 1.0],
                "horizontal_fov_deg": 90.0,
                "vertical_fov_deg": 10.0,
                "horizontal_resolution_deg": 10.0,
                "vertical_resolution_deg": 10.0,
                "rotation_rate_hz": 10.0,
                "min_range_m": 0.1,
                "max_range_m": 20.0,
            },
        )
    )
    assert lidar["status"] == "success", lidar


def _assert_delete(
    response: dict[str, Any],
    *,
    prim_path: str,
    expected_annotators: int,
    render_product_path: str,
) -> dict[str, Any]:
    assert response["status"] == "success", response
    lifecycle = response["data"]["lifecycle"]
    assert lifecycle["prim_path"] == prim_path
    assert lifecycle["teardown_method"] == "_invalidate_sensor"
    assert len(lifecycle["annotators_before"]) == expected_annotators
    assert lifecycle["writers_before"] == []
    assert lifecycle["render_product_path"] == render_product_path
    assert lifecycle["annotators_after"] == []
    assert lifecycle["writers_after"] == []
    assert lifecycle["render_product_released"] is True
    assert lifecycle["cache_evicted"] is True
    assert lifecycle["metadata_evicted"] is True
    assert response["data"]["post_delete_updates"] == 32
    assert all(response["readback"].values()), response["readback"]
    return lifecycle


async def _run_cycle(session: ClientSession, cycle: int) -> dict[str, Any]:
    await _create_sensors(session)
    created_readback = {}
    for prim_path in (CAMERA_PATH, LIDAR_PATH):
        value = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
        assert value["status"] == "success", value
        created_readback[prim_path] = value["data"]["type"]

    played = _payload(await session.call_tool("play_simulation", {}))
    assert played["status"] == "success", played
    await asyncio.sleep(3)
    camera = await _capture(
        session,
        "capture_image",
        {"prim_path": CAMERA_PATH, "return_mode": "metadata"},
    )
    lidar = await _capture(
        session,
        "get_lidar_point_cloud",
        {"prim_path": LIDAR_PATH, "return_mode": "metadata"},
    )
    paused = _payload(await session.call_tool("pause_simulation", {}))
    assert paused["status"] == "success", paused

    before = await _render_products(session)
    assert len(before[CAMERA_PATH]) == 1, before
    assert len(before[LIDAR_PATH]) == 1, before
    delete_tool = "delete_sensor" if cycle == 1 else "delete_object"
    camera_delete = _payload(
        await session.call_tool(
            delete_tool,
            {"prim_path": CAMERA_PATH, "post_delete_updates": 32},
        )
    )
    lidar_delete = _payload(
        await session.call_tool(
            delete_tool,
            {"prim_path": LIDAR_PATH, "post_delete_updates": 32},
        )
    )
    camera_lifecycle = _assert_delete(
        camera_delete,
        prim_path=CAMERA_PATH,
        expected_annotators=8,
        render_product_path=before[CAMERA_PATH][0],
    )
    lidar_lifecycle = _assert_delete(
        lidar_delete,
        prim_path=LIDAR_PATH,
        expected_annotators=2,
        render_product_path=before[LIDAR_PATH][0],
    )
    after = await _render_products(session)
    assert after == {CAMERA_PATH: [], LIDAR_PATH: []}, after
    for prim_path in (CAMERA_PATH, LIDAR_PATH):
        value = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
        assert value["status"] == "error", value

    capabilities = _payload(await session.call_tool("get_capabilities", {}))
    warmup = capabilities["data"]["sensor_warmup"]
    assert warmup["camera"]["cached_sensor_count"] == 0, warmup
    assert warmup["lidar"]["cached_sensor_count"] == 0, warmup
    return {
        "cycle": cycle,
        "delete_tool": delete_tool,
        "created_readback": created_readback,
        "camera_shape": camera["data"]["image"]["shape"],
        "lidar_point_count": lidar["data"]["lidar_point_cloud"]["point_count"],
        "render_products_before": before,
        "render_products_after": after,
        "camera_lifecycle": camera_lifecycle,
        "lidar_lifecycle": lidar_lifecycle,
    }


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert "delete_sensor" in tools
            await _ensure_non_playing(session)
            await _assert_scratch_stage(session)
            for prim_path in SCRATCH_PATHS:
                await _delete_if_present(session, prim_path)
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                data = capabilities["data"]
                assert data["runtime"]["isaac_sim_version"].startswith("6.0.1")
                assert data["extension"]["command_count"] == 54
                assert data["feature_flags"]["sensor.lifecycle"]["state"] == "supported"

                target = _payload(
                    await session.call_tool(
                        "create_object",
                        {
                            "object_type": "Cube",
                            "prim_path": TARGET_PATH,
                            "position": [4.0, 0.0, 1.0],
                            "size": 2.0,
                            "color": [0.8, 0.2, 0.1],
                        },
                    )
                )
                assert target["status"] == "success", target
                light = _payload(
                    await session.call_tool(
                        "create_light",
                        {
                            "light_type": "DistantLight",
                            "prim_path": LIGHT_PATH,
                            "rotation": [315.0, 0.0, 0.0],
                            "intensity": 3000.0,
                        },
                    )
                )
                assert light["status"] == "success", light

                cycles = [await _run_cycle(session, cycle) for cycle in (1, 2)]
                stopped = _payload(await session.call_tool("stop_simulation", {}))
                assert stopped["status"] == "success", stopped
            finally:
                await _ensure_non_playing(session)
                for prim_path in SCRATCH_PATHS:
                    await _delete_if_present(session, prim_path)

    print(
        json.dumps(
            {
                "isaac_sim_version": data["runtime"]["isaac_sim_version"],
                "adapter": data["runtime"]["adapter"],
                "command_count": data["extension"]["command_count"],
                "cycles": cycles,
                "same_path_recreated": True,
                "duplicate_pipeline_detected": False,
                "scratch_cleanup": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
