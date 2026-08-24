"""Joint-state and command-mode contract tests for task 2.1."""

from __future__ import annotations

import json

from isaac_sim_mcp_extension.handlers.robots import get_joint_state, set_joint_command

from isaac_mcp.tools.robots import register_tools


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
        return {"status": "success", "data": {}}


class _Adapter:
    def __init__(self):
        self.commands = []

    def get_robot_joint_info(self, _prim_path):
        return {
            "joint_names": ["shoulder", "finger"],
            "num_dof": 2,
            "joint_limits": [
                {"name": "shoulder", "type": "revolute"},
                {"name": "finger", "type": "prismatic"},
            ],
        }

    def get_joint_state(self, prim_path):
        return {
            "prim_path": prim_path,
            "joint_names": ["shoulder", "finger"],
            "joint_types": ["revolute", "prismatic"],
            "positions": [0.1, 0.02],
            "velocities": [0.2, 0.03],
            "efforts": [1.5, 2.5],
            "position_targets": [0.15, 0.025],
            "velocity_targets": [0.25, 0.035],
            "effort_targets": [1.0, 2.0],
        }

    def set_joint_command(self, prim_path, mode, values, joint_indices=None):
        self.commands.append((prim_path, mode, list(values), joint_indices))


def test_named_tools_forward_joint_state_and_command_arguments():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    state = json.loads(
        mcp.tools["get_joint_state"](prim_path="/World/Robot", joint_names=["finger"], joint_indices=None)
    )
    command = json.loads(
        mcp.tools["set_joint_command"](
            prim_path="/World/Robot",
            mode="velocity",
            values=[0.5],
            joint_names=["shoulder"],
            joint_indices=None,
        )
    )

    assert state["status"] == "success"
    assert command["status"] == "success"
    assert connection.calls == [
        ("robots.get_joint_state", {"prim_path": "/World/Robot", "joint_names": ["finger"]}),
        (
            "robots.set_joint_command",
            {
                "prim_path": "/World/Robot",
                "mode": "velocity",
                "values": [0.5],
                "joint_names": ["shoulder"],
            },
        ),
    ]


def test_joint_state_returns_typed_subset_with_explicit_units():
    result = get_joint_state(_Adapter(), prim_path="/World/Robot", joint_names=["finger"])

    assert result["status"] == "success"
    assert result["prim_path"] == "/World/Robot"
    assert result["joint_count"] == 2
    assert result["selection_count"] == 1
    assert result["joints"] == [
        {
            "index": 1,
            "name": "finger",
            "type": "prismatic",
            "position": 0.02,
            "velocity": 0.03,
            "effort": 2.5,
            "targets": {"position": 0.025, "velocity": 0.035, "effort": 2.0},
            "units": {"position": "meters", "velocity": "meters_per_second", "effort": "newtons"},
        }
    ]


def test_command_resolves_names_before_applying_and_returns_readback():
    adapter = _Adapter()

    result = set_joint_command(
        adapter,
        prim_path="/World/Robot",
        mode="effort",
        values=[3.0],
        joint_names=["finger"],
    )

    assert result["status"] == "success"
    assert result["mode"] == "effort"
    assert result["applied"] is True
    assert result["joint_indices"] == [1]
    assert result["joint_names"] == ["finger"]
    assert adapter.commands == [("/World/Robot", "effort", [3.0], [1])]
    assert result["readback"]["joints"][0]["name"] == "finger"


def test_invalid_joint_name_is_atomic_and_never_calls_adapter_command():
    adapter = _Adapter()

    result = set_joint_command(
        adapter,
        prim_path="/World/Robot",
        mode="position",
        values=[0.2],
        joint_names=["missing"],
    )

    assert result["status"] == "error"
    assert result["code"] == "JOINT_NOT_FOUND"
    assert result["applied"] is False
    assert adapter.commands == []


def test_invalid_selector_value_and_mode_fail_before_apply():
    adapter = _Adapter()

    cases = [
        ({"mode": "torque", "values": [1.0]}, "INVALID_JOINT_COMMAND_MODE"),
        (
            {"mode": "position", "values": [1.0], "joint_names": ["shoulder"], "joint_indices": [0]},
            "JOINT_SELECTOR_CONFLICT",
        ),
        ({"mode": "position", "values": [1.0], "joint_indices": [2]}, "JOINT_INDEX_OUT_OF_RANGE"),
        ({"mode": "position", "values": [float("nan")], "joint_indices": [0]}, "INVALID_JOINT_VALUE"),
        ({"mode": "position", "values": [True], "joint_indices": [0]}, "INVALID_JOINT_VALUE"),
        ({"mode": "position", "values": [1.0, 2.0], "joint_indices": [0]}, "JOINT_VALUE_COUNT_MISMATCH"),
        ({"mode": "position", "values": [1.0], "joint_indices": [0, 0]}, "DUPLICATE_JOINT_SELECTOR"),
    ]
    for params, expected_code in cases:
        result = set_joint_command(adapter, prim_path="/World/Robot", **params)
        assert result["status"] == "error"
        assert result["code"] == expected_code
        assert result["applied"] is False

    assert adapter.commands == []


def test_successful_apply_with_failed_readback_is_reported_as_partial():
    class _ReadbackFailure(_Adapter):
        def get_joint_state(self, _prim_path):
            raise RuntimeError("tensor view expired")

    adapter = _ReadbackFailure()
    result = set_joint_command(
        adapter,
        prim_path="/World/Robot",
        mode="velocity",
        values=[0.5],
        joint_indices=[0],
    )

    assert result["status"] == "partial"
    assert result["code"] == "JOINT_COMMAND_READBACK_FAILED"
    assert result["applied"] is True
    assert adapter.commands == [("/World/Robot", "velocity", [0.5], [0])]
