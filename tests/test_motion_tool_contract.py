"""Contract tests for task 2.3 motion tools and handlers."""

from __future__ import annotations

import json

from isaac_sim_mcp_extension.handlers import motion

from isaac_mcp.tools.motion import register_tools


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    def __init__(self):
        self.calls = []

    def send_command(self, command, params=None):
        self.calls.append((command, params))
        return {"status": "success", "command": command}


class _Adapter:
    def __init__(self):
        self.calls = []

    def compute_ik(self, **params):
        self.calls.append(("ik", params))
        return {"status": "success", "collision_check": {"checked": False}}

    def plan_joint_trajectory(self, **params):
        self.calls.append(("plan", params))
        return {"status": "success", "trajectory_id": "traj-1"}

    def execute_trajectory(self, **params):
        self.calls.append(("execute", params))
        return {"status": "success", "job_id": "job-1", "non_blocking": True}

    def cancel_motion(self, **params):
        self.calls.append(("cancel", params))
        return {"status": "cancelled", "job_id": params["job_id"]}

    def get_motion_status(self, **params):
        self.calls.append(("status", params))
        return {"status": "success", "job_id": params["job_id"], "state": "running"}


def test_five_named_tools_forward_to_motion_commands():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    assert set(mcp.tools) == {
        "compute_ik",
        "plan_joint_trajectory",
        "execute_trajectory",
        "cancel_motion",
        "get_motion_status",
    }
    json.loads(mcp.tools["compute_ik"]("/World/Franka", [0.4, 0.0, 0.5]))
    json.loads(mcp.tools["plan_joint_trajectory"]("/World/Franka", [0.0] * 7))
    json.loads(mcp.tools["execute_trajectory"]("traj-1"))
    json.loads(mcp.tools["cancel_motion"]("job-1"))
    json.loads(mcp.tools["get_motion_status"]("job-1"))

    assert [command for command, _params in connection.calls] == [
        "motion.compute_ik",
        "motion.plan_joint_trajectory",
        "motion.execute_trajectory",
        "motion.cancel",
        "motion.get_status",
    ]
    for _command, params in connection.calls:
        assert all(not callable(value) for value in params.values())
        json.dumps(params)


def test_handler_validates_inputs_before_adapter_calls():
    adapter = _Adapter()
    bad_ik = motion.compute_ik(adapter, prim_path="/World/F", target_position=[0.0, float("nan"), 0.2])
    bad_plan = motion.plan_joint_trajectory(
        adapter, prim_path="/World/F", goal_joint_positions=[0.0] * 7, planner="magic", timeout_ms=10
    )

    assert bad_ik["code"] == "INVALID_MOTION_REQUEST"
    assert bad_plan["code"] == "INVALID_MOTION_REQUEST"
    assert adapter.calls == []


def test_handler_exposes_non_blocking_lifecycle_and_collision_truth():
    adapter = _Adapter()
    ik = motion.compute_ik(
        adapter,
        prim_path="/World/F",
        target_position=[0.4, 0.0, 0.5],
        max_iterations=20,
        timeout_ms=100,
    )
    plan = motion.plan_joint_trajectory(
        adapter,
        prim_path="/World/F",
        goal_joint_positions=[0.0] * 7,
        planner="rrt",
        max_iterations=20,
        timeout_ms=100,
    )
    execute = motion.execute_trajectory(adapter, "traj-1", timeout_ms=100)
    cancel = motion.cancel_motion(adapter, "job-1")
    status = motion.get_motion_status(adapter, "job-1")

    assert ik["collision_check"]["checked"] is False
    assert plan["trajectory_id"] == "traj-1"
    assert execute["non_blocking"] is True
    assert cancel["status"] == "cancelled"
    assert status["state"] == "running"
