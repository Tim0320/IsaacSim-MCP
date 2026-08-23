#!/usr/bin/env python3
"""Live scratch verification for Task 1.4 LiDAR configuration and read-back."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LIDAR_CONFIGS = {
    "/World/MCP_Task_1_4_Lidar_A": {
        "position": [-1.0, 0.0, 1.0],
        "horizontal_fov_deg": 120.0,
        "vertical_fov_deg": 20.0,
        "horizontal_resolution_deg": 1.0,
        "vertical_resolution_deg": 2.0,
        "rotation_rate_hz": 10,
        "min_range_m": 0.5,
        "max_range_m": 40.0,
        "horizontal_samples": 120,
        "vertical_channels": 11,
    },
    "/World/MCP_Task_1_4_Lidar_B": {
        "position": [1.0, 0.0, 1.0],
        "horizontal_fov_deg": 180.0,
        "vertical_fov_deg": 30.0,
        "horizontal_resolution_deg": 0.5,
        "vertical_resolution_deg": 5.0,
        "rotation_rate_hz": 20,
        "min_range_m": 1.0,
        "max_range_m": 80.0,
        "horizontal_samples": 360,
        "vertical_channels": 7,
    },
}
TARGETS = {
    "/World/MCP_Task_1_4_Target_XP": [5.0, 0.0, 1.0],
    "/World/MCP_Task_1_4_Target_XN": [-5.0, 0.0, 1.0],
    "/World/MCP_Task_1_4_Target_YP": [0.0, 5.0, 1.0],
    "/World/MCP_Task_1_4_Target_YN": [0.0, -5.0, 1.0],
}
INVALID_PATH = "/World/MCP_Task_1_4_Invalid"
SCRATCH_PATHS = (*LIDAR_CONFIGS, *TARGETS, INVALID_PATH)
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


async def _remove_scratch(session: ClientSession) -> None:
    errors = []
    for prim_path in SCRATCH_PATHS:
        before = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
        if before["status"] != "success":
            continue
        deleted = _payload(await session.call_tool("delete_object", {"prim_path": prim_path}))
        if deleted["status"] != "success":
            errors.append(f"delete {prim_path}: {deleted}")
            continue
        after = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
        if after["status"] != "error":
            errors.append(f"delete read-back {prim_path}: {after}")
    if errors:
        raise AssertionError("; ".join(errors))


def _expected_effective(config: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in config.items() if name != "position"}


def _assert_config(actual: dict[str, Any], requested: dict[str, Any]) -> None:
    assert actual["source"] == "generic"
    assert actual["effective"] == _expected_effective(requested)
    schema = actual["schema_attributes"]
    assert schema["valid_start_azimuth_deg"] == 0.0
    assert schema["valid_end_azimuth_deg"] == requested["horizontal_fov_deg"]
    assert schema["start_azimuth_offset_deg"] == -requested["horizontal_fov_deg"] / 2.0
    assert schema["scan_rate_base_hz"] == requested["rotation_rate_hz"]
    assert schema["tick_rate_hz"] == requested["rotation_rate_hz"]
    assert schema["pattern_firing_rate_hz"] == requested["horizontal_samples"] * requested["rotation_rate_hz"]
    assert schema["near_range_m"] == requested["min_range_m"]
    assert schema["far_range_m"] == requested["max_range_m"]
    assert schema["number_of_channels"] == requested["vertical_channels"]
    assert schema["number_of_emitters"] == requested["vertical_channels"]
    assert len(schema["elevation_deg"]) == requested["vertical_channels"]


async def _capture(session: ClientSession, prim_path: str) -> dict[str, Any]:
    last = None
    for _attempt in range(24):
        last = _payload(
            await session.call_tool(
                "get_lidar_point_cloud",
                {"prim_path": prim_path, "return_mode": "metadata"},
            )
        )
        if last["status"] == "success":
            return last
        assert last["code"] == "LIDAR_FRAME_NOT_READY", last
        await asyncio.sleep(0.5)
    raise AssertionError(f"LiDAR did not produce a frame: {last}")


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "get_lidar_config" in {tool.name for tool in tools.tools}
            await _remove_scratch(session)
            created_paths = []
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                assert capabilities["data"]["runtime"]["isaac_sim_version"].startswith("6.0.1")
                flag = capabilities["data"]["feature_flags"]["lidar.config"]
                assert flag["state"] == "supported"
                assert flag["generic_schema_config"] is True
                assert flag["readback"] is True

                invalid = _payload(
                    await session.call_tool(
                        "create_lidar",
                        {
                            "prim_path": INVALID_PATH,
                            "horizontal_fov_deg": 100.0,
                            "horizontal_resolution_deg": 3.0,
                        },
                    )
                )
                assert invalid["status"] == "error", invalid
                assert invalid["code"] == "LIDAR_HORIZONTAL_RESOLUTION_NOT_DIVISIBLE", invalid
                invalid_readback = _payload(await session.call_tool("get_prim_info", {"prim_path": INVALID_PATH}))
                assert invalid_readback["status"] == "error"

                for prim_path, config in LIDAR_CONFIGS.items():
                    arguments = {"prim_path": prim_path, **config}
                    arguments.pop("horizontal_samples")
                    arguments.pop("vertical_channels")
                    created = _payload(await session.call_tool("create_lidar", arguments))
                    assert created["status"] == "success", created
                    created_paths.append(prim_path)
                    assert created["data"]["prim_path"] == prim_path
                    _assert_config(created["data"]["lidar_config"], config)
                    assert created["readback"] == {"lidar_config": created["data"]["lidar_config"]}

                    readback = _payload(await session.call_tool("get_lidar_config", {"prim_path": prim_path}))
                    assert readback["status"] == "success", readback
                    _assert_config(readback["data"]["lidar_config"], config)
                    prim = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
                    assert prim["status"] == "success", prim
                    assert prim["data"]["transform"]["position"] == config["position"]

                for prim_path, position in TARGETS.items():
                    created = _payload(
                        await session.call_tool(
                            "create_object",
                            {
                                "object_type": "Cube",
                                "prim_path": prim_path,
                                "position": position,
                                "size": 2.0,
                                "color": [0.2, 0.7, 0.2],
                            },
                        )
                    )
                    assert created["status"] == "success", created
                    created_paths.append(prim_path)

                played = _payload(await session.call_tool("play_simulation", {}))
                assert played["status"] == "success", played
                await asyncio.sleep(3)
                captures = {prim_path: await _capture(session, prim_path) for prim_path in LIDAR_CONFIGS}
                stopped = _payload(await session.call_tool("stop_simulation", {}))
                assert stopped["status"] == "success", stopped
            finally:
                await _remove_scratch(session)

    summary = {
        "isaac_sim_version": capabilities["data"]["runtime"]["isaac_sim_version"],
        "adapter": capabilities["data"]["runtime"]["adapter"],
        "physics_backend": capabilities["data"]["runtime"]["physics_backend"],
        "configs": {
            prim_path: {
                "effective": _expected_effective(config),
                "point_count": captures[prim_path]["data"]["point_count"],
            }
            for prim_path, config in LIDAR_CONFIGS.items()
        },
        "invalid_config_code": invalid["code"],
        "scratch_cleanup": True,
    }
    assert all(item["point_count"] > 0 for item in summary["configs"].values())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
