#!/usr/bin/env python3
"""Live scratch-articulation verification for Robot control task 2.2."""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROBOT_PATH = "/World/MCP_Task_2_2_Robot"
DRIVE_FIELDS = ("stiffness", "damping", "max_force", "max_velocity", "drive_type")
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


async def _ensure_stopped(session: ClientSession) -> None:
    state = None
    for _attempt in range(60):
        state = _payload(await session.call_tool("get_simulation_state", {}))
        if state["status"] == "success":
            break
        assert state["code"] == "STAGE_NOT_READY", state
        await asyncio.sleep(1.0)
    assert state is not None and state["status"] == "success", state
    if state["data"]["timeline_state"] != "stopped":
        stopped = _payload(await session.call_tool("stop_simulation", {}))
        assert stopped["status"] == "success", stopped


async def _delete_if_present(session: ClientSession) -> None:
    before = _payload(await session.call_tool("get_prim_info", {"prim_path": ROBOT_PATH}))
    if before["status"] != "success":
        return
    deleted = _payload(await session.call_tool("delete_object", {"prim_path": ROBOT_PATH}))
    assert deleted["status"] == "success", deleted
    after = _payload(await session.call_tool("get_prim_info", {"prim_path": ROBOT_PATH}))
    assert after["status"] == "error", after


async def _assert_scratch_stage(session: ClientSession) -> None:
    code = f"""
import json
import omni.usd
stage = omni.usd.get_context().get_stage()
allowed_root = {ROBOT_PATH!r}
unexpected = []
for prim in stage.TraverseAll():
    path = str(prim.GetPath())
    if (
        path == "/World"
        or path == "/PhysicsScene"
        or path.startswith("/Render")
        or path == "/Orchestrator"
        or path.startswith("/Orchestrator/")
        or path.startswith("/OmniverseKit")
        or path == "/Environment"
        or path.startswith("/Environment/")
    ):
        continue
    if path == allowed_root or path.startswith(allowed_root + "/"):
        continue
    unexpected.append(path)
print(json.dumps(unexpected))
"""
    response = _payload(await session.call_tool("execute_script", {"code": code}))
    assert response["status"] == "success", response
    lines = [line for line in response["data"]["stdout"].splitlines() if line.strip()]
    unexpected = json.loads(lines[-1])
    assert not unexpected, f"Refusing non-scratch stage with unexpected prims: {unexpected[:20]}"


def _find_joint(response: dict[str, Any], name: str) -> dict[str, Any]:
    assert response["status"] == "success", response
    joints = response["data"]["joints"]
    joint = next(item for item in joints if item["name"] == name)
    for field in DRIVE_FIELDS[:-1]:
        value = joint[field]
        assert value is not None and math.isfinite(float(value)), (field, joint)
    assert joint["drive_type"] in {"force", "acceleration"}, joint
    return joint


def _drive_snapshot(joint: dict[str, Any]) -> dict[str, Any]:
    return {field: joint[field] for field in DRIVE_FIELDS}


def _assert_requested(readback: dict[str, Any], requested: dict[str, Any]) -> None:
    assert len(readback["joints"]) == 1, readback
    joint = readback["joints"][0]
    for field, expected in requested.items():
        actual = joint[field]
        if isinstance(expected, float):
            assert math.isclose(float(actual), expected, rel_tol=1e-5, abs_tol=1e-5), (field, actual, expected)
        else:
            assert actual == expected, (field, actual, expected)


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    report: dict[str, Any] = {}
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert {"get_joint_config", "set_joint_drive_config"} <= tools
            await _ensure_stopped(session)
            await _assert_scratch_stage(session)
            await _delete_if_present(session)
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                data = capabilities["data"]
                assert data["runtime"]["isaac_sim_version"].startswith("6.0.1")
                assert data["runtime"]["adapter"] == "IsaacAdapterV6"
                assert data["runtime"]["physics_backend"] == "physx"
                assert data["extension"]["command_count"] == len(tools)
                drive_capability = data["feature_flags"]["robot.joint_drive_config"]
                assert drive_capability["state"] == "supported", drive_capability
                assert set(drive_capability["fields"].values()) == {"supported"}, drive_capability

                created = _payload(
                    await session.call_tool(
                        "create_robot",
                        {"robot_type": "frankapanda", "prim_path": ROBOT_PATH},
                    )
                )
                assert created["status"] == "success", created
                info = _payload(await session.call_tool("get_robot_info", {"prim_path": ROBOT_PATH}))
                assert info["status"] == "success", info
                names = info["data"]["joint_names"]
                assert names, info
                selected_name = names[0]

                before = _payload(await session.call_tool("get_joint_config", {"prim_path": ROBOT_PATH}))
                before_joint = _find_joint(before, selected_name)
                requested = {
                    "stiffness": max(1.0, float(before_joint["stiffness"]) * 0.9),
                    "damping": max(0.5, float(before_joint["damping"]) * 0.9),
                    "max_force": max(1.0, min(100.0, float(before_joint["max_force"]) * 0.9)),
                    "max_velocity": max(0.1, min(1.5, float(before_joint["max_velocity"]) * 0.9)),
                    "drive_type": "acceleration" if before_joint["drive_type"] == "force" else "force",
                }
                updated = _payload(
                    await session.call_tool(
                        "set_joint_drive_config",
                        {"prim_path": ROBOT_PATH, "joint_names": [selected_name], **requested},
                    )
                )
                assert updated["status"] == "success", updated
                assert updated["data"]["applied"] is True, updated
                _assert_requested(updated["readback"], requested)

                after = _payload(await session.call_tool("get_joint_config", {"prim_path": ROBOT_PATH}))
                after_joint = _find_joint(after, selected_name)
                _assert_requested({"joints": [after_joint]}, requested)
                stable_snapshot = _drive_snapshot(after_joint)

                invalid_value = _payload(
                    await session.call_tool(
                        "set_joint_drive_config",
                        {"prim_path": ROBOT_PATH, "joint_names": [selected_name], "stiffness": -1.0},
                    )
                )
                assert invalid_value["status"] == "error", invalid_value
                assert invalid_value["code"] == "INVALID_JOINT_DRIVE_VALUE", invalid_value
                assert invalid_value["data"]["applied"] is False, invalid_value

                invalid_name = _payload(
                    await session.call_tool(
                        "set_joint_drive_config",
                        {"prim_path": ROBOT_PATH, "joint_names": ["__missing_joint__"], "damping": 1.0},
                    )
                )
                assert invalid_name["status"] == "error", invalid_name
                assert invalid_name["code"] == "JOINT_NOT_FOUND", invalid_name
                assert invalid_name["data"]["applied"] is False, invalid_name

                played = _payload(await session.call_tool("play_simulation", {}))
                assert played["status"] == "success", played
                await asyncio.sleep(0.25)
                active_rejection = _payload(
                    await session.call_tool(
                        "set_joint_drive_config",
                        {"prim_path": ROBOT_PATH, "joint_names": [selected_name], "damping": 1.0},
                    )
                )
                assert active_rejection["status"] == "error", active_rejection
                assert active_rejection["code"] == "JOINT_DRIVE_TIMELINE_ACTIVE", active_rejection
                assert active_rejection["data"]["applied"] is False, active_rejection
                await _ensure_stopped(session)

                final = _payload(await session.call_tool("get_joint_config", {"prim_path": ROBOT_PATH}))
                final_joint = _find_joint(final, selected_name)
                assert _drive_snapshot(final_joint) == stable_snapshot

                report = {
                    "isaac_sim_version": data["runtime"]["isaac_sim_version"],
                    "adapter": data["runtime"]["adapter"],
                    "physics_backend": data["runtime"]["physics_backend"],
                    "command_count": data["extension"]["command_count"],
                    "robot_path": ROBOT_PATH,
                    "joint_count": len(names),
                    "selected_joint": selected_name,
                    "before": _drive_snapshot(before_joint),
                    "requested": requested,
                    "readback": stable_snapshot,
                    "invalid_value_atomic_rejection": True,
                    "invalid_name_atomic_rejection": True,
                    "active_timeline_rejection": True,
                }
            finally:
                await _ensure_stopped(session)
                await _delete_if_present(session)

    report["scratch_cleanup"] = True
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
