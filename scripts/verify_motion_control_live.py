#!/usr/bin/env python3
"""Live scratch-Franka verification for task 2.3 motion control."""

from __future__ import annotations

import json
import math
import time

from isaac_mcp.connection import IsaacConnection

ROBOT_PATH = "/World/MCP_Task_2_3_Robot"
HOME = [0.0, -0.57, 0.0, -2.81, 0.0, 3.037, 0.741, 0.04, 0.04]


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _initialize_runtime_pose(connection: IsaacConnection) -> None:
    code = f"""
import gc
import numpy as np
import warp as wp
from isaac_sim_mcp_extension.extension import MCPExtension
obj = next(o for o in gc.get_objects() if isinstance(o, MCPExtension))
art = obj._adapter._runtime_articulation({ROBOT_PATH!r})
q = wp.array(np.asarray([{HOME!r}], dtype=np.float32), dtype=wp.float32)
art.set_dof_positions(q)
art.set_dof_position_targets(q)
print("initialized")
"""
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    assert "initialized" in result["stdout"], result


def _assert_scratch_stage(connection: IsaacConnection) -> None:
    code = f"""
import json
import omni.usd
allowed = {ROBOT_PATH!r}
unexpected = []
for prim in omni.usd.get_context().get_stage().TraverseAll():
    path = str(prim.GetPath())
    if path in {{"/World", "/PhysicsScene", "/Environment"}} or path.startswith(("/Render", "/OmniverseKit", "/Environment/")):
        continue
    if path == allowed or path.startswith(allowed + "/"):
        continue
    unexpected.append(path)
print(json.dumps(unexpected))
"""
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    unexpected = json.loads([line for line in result["stdout"].splitlines() if line.strip()][-1])
    assert not unexpected, f"Refusing non-scratch stage: {unexpected[:20]}"


def main() -> int:
    connection = IsaacConnection(port=8766)
    report: dict = {}
    try:
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["runtime"]["isaac_sim_version"].startswith("6.0.1")
        assert capabilities["runtime"]["physics_backend"] == "physx"
        assert capabilities["extension"]["command_count"] == 62
        assert capabilities["feature_flags"]["motion.ik_and_planning"]["state"] == "supported"

        connection.send_command("simulation.stop")
        _assert_scratch_stage(connection)
        if connection.send_command("scene.get_prim_info", {"prim_path": ROBOT_PATH})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROBOT_PATH}))
        _data(connection.send_command("scene.clear", {"keep_environment": False}))
        _data(connection.send_command("scene.create_physics", {"gravity": [0.0, 0.0, -9.81]}))
        _data(connection.send_command("robots.create", {"robot_type": "frankapanda", "prim_path": ROBOT_PATH}))
        _data(connection.send_command("simulation.play"))
        _initialize_runtime_pose(connection)
        initial_state = _data(connection.send_command("robots.get_joint_state", {"prim_path": ROBOT_PATH}))
        measured = [joint["position"] for joint in initial_state["joints"]]
        assert all(math.isfinite(value) for value in measured), measured
        assert all(math.isclose(value, expected, abs_tol=1e-5) for value, expected in zip(measured, HOME)), measured

        ik_params = {
            "prim_path": ROBOT_PATH,
            "target_position": [0.45, 0.0, 0.5],
            "end_effector_frame": "right_gripper",
            "seed_joint_positions": HOME[:7],
            "random_seed": 17,
            "max_iterations": 100,
            "timeout_ms": 3000,
        }
        ik_a = _data(connection.send_command("motion.compute_ik", ik_params))
        ik_b = _data(connection.send_command("motion.compute_ik", ik_params))
        assert ik_a["success"] and ik_a["position_error"] <= 0.001, ik_a
        assert ik_a["joint_positions"] == ik_b["joint_positions"], (ik_a, ik_b)
        assert ik_a["collision_check"]["checked"] is False

        goal = HOME[:7].copy()
        goal[0] += 0.08
        rrt = _data(
            connection.send_command(
                "motion.plan_joint_trajectory",
                {
                    "prim_path": ROBOT_PATH,
                    "goal_joint_positions": goal,
                    "start_joint_positions": HOME[:7],
                    "planner": "rrt",
                    "random_seed": 17,
                    "max_iterations": 5000,
                    "timeout_ms": 5000,
                },
            )
        )
        assert rrt["collision_check"]["checked"] is True, rrt

        _data(connection.send_command("simulation.pause"))
        execution = _data(
            connection.send_command(
                "motion.execute_trajectory", {"trajectory_id": rrt["trajectory_id"], "timeout_ms": 10000}
            )
        )
        assert execution["non_blocking"] is True
        job_id = execution["job_id"]
        paused = _data(connection.send_command("motion.get_status", {"job_id": job_id}))
        assert paused["state"] in {"queued", "paused"}, paused
        _data(connection.send_command("simulation.play"))
        status = paused
        for _ in range(120):
            status = _data(connection.send_command("motion.get_status", {"job_id": job_id}))
            if status["terminal"]:
                break
            time.sleep(0.02)
        assert status["state"] == "completed", status

        cancel_plan = _data(
            connection.send_command(
                "motion.plan_joint_trajectory",
                {
                    "prim_path": ROBOT_PATH,
                    "goal_joint_positions": HOME[:7],
                    "start_joint_positions": goal,
                    "planner": "cspace",
                    "timeout_ms": 5000,
                },
            )
        )
        assert cancel_plan["collision_check"]["checked"] is False
        cancel_job = _data(
            connection.send_command(
                "motion.execute_trajectory", {"trajectory_id": cancel_plan["trajectory_id"], "timeout_ms": 10000}
            )
        )
        cancelled = connection.send_command("motion.cancel", {"job_id": cancel_job["job_id"]})
        assert cancelled["status"] == "cancelled", cancelled
        cancelled_data = cancelled["data"]
        assert cancelled_data["state"] == "cancelled" and cancelled_data["terminal"] is True

        timeout_job = _data(
            connection.send_command(
                "motion.execute_trajectory", {"trajectory_id": cancel_plan["trajectory_id"], "timeout_ms": 1}
            )
        )
        time.sleep(0.02)
        timed_out = _data(connection.send_command("motion.get_status", {"job_id": timeout_job["job_id"]}))
        assert timed_out["state"] == "timeout", timed_out

        final_state = _data(connection.send_command("robots.get_joint_state", {"prim_path": ROBOT_PATH}))
        assert all(math.isfinite(joint["position"]) for joint in final_state["joints"]), final_state
        report = {
            "pass": True,
            "runtime": capabilities["runtime"],
            "command_count": capabilities["extension"]["command_count"],
            "ik_position_error_m": ik_a["position_error"],
            "ik_deterministic_seed": 17,
            "rrt_collision_check": rrt["collision_check"],
            "completed_job": status,
            "cancelled_job": cancelled_data,
            "timeout_job": timed_out,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        try:
            connection.send_command("simulation.stop")
            if connection.send_command("scene.get_prim_info", {"prim_path": ROBOT_PATH})["status"] == "success":
                connection.send_command("objects.delete", {"prim_path": ROBOT_PATH})
        finally:
            connection.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
