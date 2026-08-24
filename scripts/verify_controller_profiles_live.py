#!/usr/bin/env python3
"""Guarded live verification for task 2.4 controller profiles.

The verifier performs no Stage or timeline writes until it proves that the
current Stage contains only the documented baseline/task fixture namespaces.
"""

from __future__ import annotations

import json
import math
import time

from isaac_mcp.connection import IsaacConnection

FRANKA_PATH = "/World/MCP_Task_2_4_Franka"
JETBOT_PATH = "/World/MCP_Task_2_4_Jetbot"
KAYA_PATH = "/World/MCP_Task_2_4_Kaya"
FIXTURE_PATHS = (FRANKA_PATH, JETBOT_PATH, KAYA_PATH)
OWNED_PHYSICS_PATHS = ("/World/groundPlane", "/World/PhysicsScene")


def _progress(step: str) -> None:
    print(json.dumps({"event": "progress", "step": step}), flush=True)


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _scratch_guard(connection: IsaacConnection) -> list[str]:
    code = f"""
import json
import omni.usd
allowed_roots = {FIXTURE_PATHS!r}
unexpected = []
for prim in omni.usd.get_context().get_stage().TraverseAll():
    path = str(prim.GetPath())
    if path in {{"/World", "/PhysicsScene", "/Environment"}} or path.startswith(("/Render", "/OmniverseKit", "/Environment/")):
        continue
    if any(path == root or path.startswith(root + "/") for root in allowed_roots):
        continue
    unexpected.append(path)
print(json.dumps(unexpected))
"""
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return json.loads(lines[-1])


def _joint_snapshot(connection: IsaacConnection, prim_path: str, joint_names: list[str]) -> list[dict]:
    state = _data(
        connection.send_command(
            "robots.get_joint_state", {"prim_path": prim_path, "joint_names": joint_names}
        )
    )
    snapshot = []
    for joint in state["joints"]:
        position = float(joint["position"])
        velocity = float(joint["velocity"])
        target = float(joint["targets"]["velocity"])
        assert all(math.isfinite(value) for value in (position, velocity, target)), joint
        snapshot.append(
            {
                "name": joint["name"],
                "position": position,
                "velocity": velocity,
                "velocity_target": target,
            }
        )
    return snapshot


def _command_targets(connection: IsaacConnection, prim_path: str) -> list[dict]:
    """Snapshot command targets only; measured state may move while playing."""
    state = _data(connection.send_command("robots.get_joint_state", {"prim_path": prim_path}))
    return [dict(joint["targets"]) for joint in state["joints"]]


def _base_pose(connection: IsaacConnection, prim_path: str) -> list[list[float]]:
    code = f"""
import json
import omni.usd
from pxr import UsdGeom
prim = omni.usd.get_context().get_stage().GetPrimAtPath({prim_path!r})
matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0.0)
print(json.dumps([[float(matrix[row][col]) for col in range(4)] for row in range(4)]))
"""
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return json.loads(lines[-1])


def main() -> int:
    connection = IsaacConnection(port=8766)
    owns_fixtures = False
    try:
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["runtime"]["isaac_sim_version"].startswith("6.0.1")
        assert capabilities["runtime"]["physics_backend"] == "physx"
        assert capabilities["extension"]["command_count"] == 68
        assert capabilities["feature_flags"]["robot.gripper_profiles"]["state"] == "supported"
        assert capabilities["feature_flags"]["robot.mobile_base_profiles"]["state"] == "supported"

        profiles = _data(connection.send_command("controllers.list_profiles"))
        expected_profiles = {
            "franka_parallel_gripper",
            "nvidia_jetbot_differential",
            "nvidia_kaya_holonomic",
        }
        assert set(profiles["profiles"]) == expected_profiles, profiles

        unexpected = _scratch_guard(connection)
        if unexpected:
            print(
                json.dumps(
                    {
                        "pass": False,
                        "code": "SCRATCH_STAGE_REQUIRED",
                        "message": "Refusing all Stage and timeline writes because non-task prims exist",
                        "unexpected_prim_count": len(unexpected),
                        "unexpected_prims": unexpected[:20],
                        "read_only_checks": {
                            "command_count": capabilities["extension"]["command_count"],
                            "profiles": sorted(profiles["profiles"]),
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2

        owns_fixtures = True
        _progress("prepare_scratch_stage")
        _data(connection.send_command("simulation.stop"))
        _data(connection.send_command("scene.clear", {"keep_environment": False}))
        _data(connection.send_command("scene.create_physics", {"gravity": [0.0, 0.0, -9.81]}))
        _data(
            connection.send_command(
                "robots.create", {"robot_type": "frankapanda", "prim_path": FRANKA_PATH, "position": [0, 0, 0]}
            )
        )
        _data(
            connection.send_command(
                "robots.create", {"robot_type": "jetbot", "prim_path": JETBOT_PATH, "position": [2, 0, 0]}
            )
        )
        _data(
            connection.send_command(
                "robots.create", {"robot_type": "kaya", "prim_path": KAYA_PATH, "position": [4, 0, 0]}
            )
        )
        _progress("play_and_bind_articulations")
        _data(connection.send_command("simulation.play"))
        time.sleep(1.0)

        _progress("verify_franka_gripper")
        opened = _data(
            connection.send_command(
                "controllers.open_gripper",
                {"prim_path": FRANKA_PATH, "profile": "franka_parallel_gripper"},
            )
        )
        assert opened["finger_targets_m"] == [0.04, 0.04], opened
        set_width = _data(
            connection.send_command(
                "controllers.set_gripper_width",
                {"prim_path": FRANKA_PATH, "profile": "franka_parallel_gripper", "width_m": 0.03},
            )
        )
        assert all(math.isclose(value, 0.015, abs_tol=1e-6) for value in set_width["finger_targets_m"])
        closed = _data(
            connection.send_command(
                "controllers.close_gripper",
                {"prim_path": FRANKA_PATH, "profile": "franka_parallel_gripper"},
            )
        )
        assert closed["finger_targets_m"] == [0.0, 0.0], closed

        _progress("verify_profile_mismatch_atomicity")
        before_mismatch = _command_targets(connection, FRANKA_PATH)
        mismatch = connection.send_command(
            "controllers.set_mobile_base_velocity",
            {
                "prim_path": FRANKA_PATH,
                "profile": "nvidia_jetbot_differential",
                "forward_mps": 0.1,
            },
        )
        assert mismatch["status"] == "error" and mismatch["code"] == "CONTROLLER_PROFILE_MISMATCH", mismatch
        after_mismatch = _command_targets(connection, FRANKA_PATH)
        assert before_mismatch == after_mismatch, mismatch

        _progress("verify_jetbot_differential")
        jetbot_before = _base_pose(connection, JETBOT_PATH)
        jetbot = _data(
            connection.send_command(
                "controllers.set_mobile_base_velocity",
                {
                    "prim_path": JETBOT_PATH,
                    "profile": "nvidia_jetbot_differential",
                    "forward_mps": 0.1,
                    "yaw_radps": 0.2,
                },
            )
        )
        time.sleep(0.5)
        jetbot_state = _joint_snapshot(connection, JETBOT_PATH, jetbot["joint_names"])
        jetbot_after = _base_pose(connection, JETBOT_PATH)
        jetbot_stop = _data(
            connection.send_command(
                "controllers.stop_mobile_base",
                {"prim_path": JETBOT_PATH, "profile": "nvidia_jetbot_differential"},
            )
        )
        jetbot_stopped_state = _joint_snapshot(connection, JETBOT_PATH, jetbot["joint_names"])
        assert jetbot_stop["stopped"] and all(
            abs(joint["velocity_target"]) <= 1e-8 for joint in jetbot_stopped_state
        )

        _progress("verify_kaya_holonomic")
        kaya_before = _base_pose(connection, KAYA_PATH)
        kaya = _data(
            connection.send_command(
                "controllers.set_mobile_base_velocity",
                {
                    "prim_path": KAYA_PATH,
                    "profile": "nvidia_kaya_holonomic",
                    "forward_mps": 0.1,
                    "lateral_mps": 0.05,
                    "yaw_radps": 0.1,
                },
            )
        )
        time.sleep(0.5)
        kaya_state = _joint_snapshot(connection, KAYA_PATH, kaya["joint_names"])
        kaya_after = _base_pose(connection, KAYA_PATH)
        kaya_stop = _data(
            connection.send_command(
                "controllers.stop_mobile_base",
                {"prim_path": KAYA_PATH, "profile": "nvidia_kaya_holonomic"},
            )
        )
        kaya_stopped_state = _joint_snapshot(connection, KAYA_PATH, kaya["joint_names"])
        assert kaya_stop["stopped"] and all(
            abs(joint["velocity_target"]) <= 1e-8 for joint in kaya_stopped_state
        )

        print(
            json.dumps(
                {
                    "pass": True,
                    "runtime": capabilities["runtime"],
                    "command_count": capabilities["extension"]["command_count"],
                    "gripper": {"open": opened, "set_width": set_width, "close": closed},
                    "profile_mismatch": {"code": mismatch["code"], "state_unchanged": True},
                    "jetbot": {
                        "joint_state_after_command": jetbot_state,
                        "joint_state_after_stop": jetbot_stopped_state,
                        "pose_before": jetbot_before,
                        "pose_after": jetbot_after,
                        "stopped": True,
                    },
                    "kaya": {
                        "joint_state_after_command": kaya_state,
                        "joint_state_after_stop": kaya_stopped_state,
                        "pose_before": kaya_before,
                        "pose_after": kaya_after,
                        "stopped": True,
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        if owns_fixtures:
            try:
                _progress("cleanup_owned_fixtures")
                connection.send_command("simulation.stop")
                for path in (*FIXTURE_PATHS, *OWNED_PHYSICS_PATHS):
                    if connection.send_command("scene.get_prim_info", {"prim_path": path})["status"] == "success":
                        connection.send_command("objects.delete", {"prim_path": path})
            finally:
                connection.disconnect()
        else:
            connection.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
