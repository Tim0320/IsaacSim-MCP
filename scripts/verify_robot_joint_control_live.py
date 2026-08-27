#!/usr/bin/env python3
"""Live scratch-articulation verification for Robot control task 2.1."""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from isaac_mcp.tool_inventory import MCP_LOCAL_TOOL_NAMES

ROBOT_PATH = "/World/MCP_Task_2_1_Robot"
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


async def _ensure_non_playing(session: ClientSession) -> None:
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


def _joint(response: dict[str, Any]) -> dict[str, Any]:
    assert response["status"] == "success", response
    joints = response["data"]["joints"]
    assert len(joints) == 1, joints
    joint = joints[0]
    for key in ("position", "velocity", "effort"):
        assert math.isfinite(float(joint[key])), (key, joint)
        assert math.isfinite(float(joint["targets"][key])), (key, joint)
    return joint


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
            assert {"get_joint_state", "set_joint_command"} <= tools
            await _ensure_non_playing(session)
            await _assert_scratch_stage(session)
            await _delete_if_present(session)
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                data = capabilities["data"]
                assert data["runtime"]["isaac_sim_version"].startswith("6.0.1")
                assert data["runtime"]["adapter"] == "IsaacAdapterV6"
                assert data["extension"]["command_count"] == len(tools - MCP_LOCAL_TOOL_NAMES)
                assert data["feature_flags"]["robot.joint_state"]["state"] == "supported"
                assert data["feature_flags"]["robot.joint_command"]["state"] == "supported"

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

                played = _payload(await session.call_tool("play_simulation", {}))
                assert played["status"] == "success", played
                await asyncio.sleep(1.0)
                initial = _payload(
                    await session.call_tool(
                        "get_joint_state", {"prim_path": ROBOT_PATH, "joint_names": [selected_name]}
                    )
                )
                initial_joint = _joint(initial)

                modes = {}
                commands = {
                    "position": float(initial_joint["position"]) + 0.05,
                    "velocity": 0.1,
                    "effort": 0.05,
                }
                for mode, value in commands.items():
                    commanded = _payload(
                        await session.call_tool(
                            "set_joint_command",
                            {
                                "prim_path": ROBOT_PATH,
                                "mode": mode,
                                "values": [value],
                                "joint_names": [selected_name],
                            },
                        )
                    )
                    assert commanded["status"] == "success", commanded
                    immediate = commanded["readback"]["joints"][0]
                    assert math.isclose(float(immediate["targets"][mode]), value, rel_tol=1e-4, abs_tol=1e-5), commanded
                    await asyncio.sleep(0.1)
                    state = _payload(
                        await session.call_tool(
                            "get_joint_state",
                            {"prim_path": ROBOT_PATH, "joint_names": [selected_name]},
                        )
                    )
                    measured = _joint(state)
                    modes[mode] = {
                        "requested": value,
                        "immediate_target": immediate["targets"][mode],
                        "measured_after_step": {
                            "position": measured["position"],
                            "velocity": measured["velocity"],
                            "effort": measured["effort"],
                        },
                        "target_after_step": measured["targets"][mode],
                    }

                before_invalid = _payload(
                    await session.call_tool(
                        "get_joint_state", {"prim_path": ROBOT_PATH, "joint_names": [selected_name]}
                    )
                )
                rejected = _payload(
                    await session.call_tool(
                        "set_joint_command",
                        {
                            "prim_path": ROBOT_PATH,
                            "mode": "position",
                            "values": [0.0],
                            "joint_names": ["__missing_joint__"],
                        },
                    )
                )
                assert rejected["status"] == "error", rejected
                assert rejected["code"] == "JOINT_NOT_FOUND", rejected
                assert rejected["data"]["applied"] is False, rejected
                after_invalid = _payload(
                    await session.call_tool(
                        "get_joint_state", {"prim_path": ROBOT_PATH, "joint_names": [selected_name]}
                    )
                )
                assert before_invalid["data"]["joints"][0]["targets"] == after_invalid["data"]["joints"][0]["targets"]

                paused = _payload(await session.call_tool("pause_simulation", {}))
                assert paused["status"] == "success", paused

                report = {
                    "isaac_sim_version": data["runtime"]["isaac_sim_version"],
                    "adapter": data["runtime"]["adapter"],
                    "physics_backend": data["runtime"]["physics_backend"],
                    "command_count": data["extension"]["command_count"],
                    "robot_path": ROBOT_PATH,
                    "joint_count": len(names),
                    "selected_joint": selected_name,
                    "modes": modes,
                    "invalid_joint_atomic_rejection": True,
                }
            finally:
                await _ensure_non_playing(session)
                await _delete_if_present(session)

    report["scratch_cleanup"] = True
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
