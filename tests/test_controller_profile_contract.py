"""Contract tests for task 2.4 explicit controller profiles."""

from __future__ import annotations

import json
import math

from isaac_sim_mcp_extension.handlers import controllers

from isaac_mcp.tools.controllers import register_tools


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
        return {"status": "success"}


class _Adapter:
    def __init__(self, names, types, timeline_state="playing"):
        self.names = names
        self.types = types
        self.timeline_state = timeline_state
        self.commands = []

    def get_robot_joint_info(self, _prim_path):
        return {
            "joint_names": self.names,
            "joint_limits": [{"name": name, "type": joint_type} for name, joint_type in zip(self.names, self.types)],
        }

    def get_simulation_state(self):
        return {"timeline_state": self.timeline_state}

    def set_joint_command(self, prim_path, mode, values, joint_indices=None):
        self.commands.append((prim_path, mode, list(values), list(joint_indices)))

    def get_joint_state(self, prim_path):
        targets = [0.0] * len(self.names)
        for _path, mode, values, indices in self.commands:
            if mode == "position":
                position_targets = targets.copy()
                for index, value in zip(indices, values):
                    position_targets[index] = value
            elif mode == "velocity":
                velocity_targets = targets.copy()
                for index, value in zip(indices, values):
                    velocity_targets[index] = value
        return {
            "prim_path": prim_path,
            "joint_names": self.names,
            "joint_types": self.types,
            "positions": targets,
            "velocities": targets,
            "efforts": targets,
            "position_targets": locals().get("position_targets", targets),
            "velocity_targets": locals().get("velocity_targets", targets),
            "effort_targets": targets,
        }

    def compute_holonomic_wheel_velocities(self, prim_path, com_prim_path, command, joint_names):
        assert prim_path == "/World/Kaya"
        assert com_prim_path == "/World/Kaya/base_link/control_offset"
        assert joint_names == ["axle_0_joint", "axle_1_joint", "axle_2_joint"]
        if command == [0.0, 0.0, 0.0]:
            return [0.0, 0.0, 0.0]
        assert command == [0.2, -0.1, 0.3]
        return [1.0, 2.0, 3.0]


def test_six_named_tools_forward_explicit_profile():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)
    assert set(mcp.tools) == {
        "list_controller_profiles",
        "set_gripper_width",
        "open_gripper",
        "close_gripper",
        "set_mobile_base_velocity",
        "stop_mobile_base",
    }
    json.loads(mcp.tools["list_controller_profiles"]())
    json.loads(mcp.tools["open_gripper"]("/World/F", "franka_parallel_gripper"))
    json.loads(mcp.tools["close_gripper"]("/World/F", "franka_parallel_gripper"))
    json.loads(mcp.tools["set_gripper_width"]("/World/F", "franka_parallel_gripper", 0.04))
    json.loads(mcp.tools["set_mobile_base_velocity"]("/World/J", "nvidia_jetbot_differential", 0.1))
    json.loads(mcp.tools["stop_mobile_base"]("/World/J", "nvidia_jetbot_differential"))
    assert [command for command, _params in connection.calls] == [
        "controllers.list_profiles",
        "controllers.open_gripper",
        "controllers.close_gripper",
        "controllers.set_gripper_width",
        "controllers.set_mobile_base_velocity",
        "controllers.stop_mobile_base",
    ]
    for _command, params in connection.calls:
        assert all(not callable(value) for value in params.values())
        json.dumps(params)


def test_franka_width_maps_symmetrically_and_reads_back():
    names = ["panda_joint1", "panda_finger_joint1", "panda_finger_joint2"]
    adapter = _Adapter(names, ["revolute", "prismatic", "prismatic"])
    result = controllers.set_gripper_width(adapter, "/World/Franka", "franka_parallel_gripper", width_m=0.06)
    assert result["status"] == "success"
    assert result["requested_width_m"] == 0.06
    assert adapter.commands == [("/World/Franka", "position", [0.03, 0.03], [1, 2])]
    assert [joint["targets"]["position"] for joint in result["readback"]["joints"]] == [0.03, 0.03]


def test_profile_mismatch_and_invalid_width_apply_nothing():
    adapter = _Adapter(["finger_left", "finger_right"], ["prismatic", "prismatic"])
    mismatch = controllers.open_gripper(adapter, "/World/Other", "franka_parallel_gripper")
    invalid = controllers.set_gripper_width(adapter, "/World/Other", "franka_parallel_gripper", width_m=math.nan)
    unknown = controllers.close_gripper(adapter, "/World/Other", "unknown")
    assert mismatch["code"] == "CONTROLLER_PROFILE_MISMATCH"
    assert invalid["code"] == "INVALID_GRIPPER_WIDTH"
    assert unknown["code"] == "CONTROLLER_PROFILE_NOT_FOUND"
    assert adapter.commands == []


def test_jetbot_differential_mapping_and_lateral_rejection():
    adapter = _Adapter(["left_wheel_joint", "right_wheel_joint"], ["revolute", "revolute"])
    result = controllers.set_mobile_base_velocity(
        adapter,
        "/World/Jetbot",
        "nvidia_jetbot_differential",
        forward_mps=0.12,
        lateral_mps=0.0,
        yaw_radps=0.4,
    )
    expected = [(0.12 - 0.4 * 0.1125 / 2) / 0.03, (0.12 + 0.4 * 0.1125 / 2) / 0.03]
    assert result["wheel_velocity_targets_radps"] == expected
    assert adapter.commands[-1] == ("/World/Jetbot", "velocity", expected, [0, 1])
    rejected = controllers.set_mobile_base_velocity(
        adapter, "/World/Jetbot", "nvidia_jetbot_differential", 0.1, lateral_mps=0.1
    )
    assert rejected["code"] == "PROFILE_DOES_NOT_SUPPORT_LATERAL_VELOCITY"


def test_kaya_uses_usd_geometry_and_stop_verifies_zero_targets():
    adapter = _Adapter(["axle_0_joint", "axle_1_joint", "axle_2_joint"], ["revolute"] * 3)
    command = controllers.set_mobile_base_velocity(
        adapter,
        "/World/Kaya",
        "nvidia_kaya_holonomic",
        forward_mps=0.2,
        lateral_mps=-0.1,
        yaw_radps=0.3,
    )
    assert command["wheel_velocity_targets_radps"] == [1.0, 2.0, 3.0]
    stopped = controllers.stop_mobile_base(adapter, "/World/Kaya", "nvidia_kaya_holonomic")
    assert stopped["status"] == "success"
    assert stopped["stopped"] is True
    assert all(joint["targets"]["velocity"] == 0.0 for joint in stopped["readback"]["joints"])


def test_kaya_geometry_failure_applies_nothing_with_stable_code():
    class BrokenGeometryAdapter(_Adapter):
        def compute_holonomic_wheel_velocities(self, *_args):
            raise ValueError("USD mecanum joints do not match")

    adapter = BrokenGeometryAdapter(["axle_0_joint", "axle_1_joint", "axle_2_joint"], ["revolute"] * 3)
    result = controllers.set_mobile_base_velocity(adapter, "/World/Kaya", "nvidia_kaya_holonomic", forward_mps=0.1)
    assert result["status"] == "error"
    assert result["code"] == "HOLONOMIC_GEOMETRY_INVALID"
    assert result["applied"] is False
    assert adapter.commands == []


def test_nonzero_mobile_command_requires_playing_timeline():
    adapter = _Adapter(["left_wheel_joint", "right_wheel_joint"], ["revolute", "revolute"], timeline_state="paused")
    result = controllers.set_mobile_base_velocity(
        adapter, "/World/Jetbot", "nvidia_jetbot_differential", forward_mps=0.1
    )
    assert result["code"] == "TIMELINE_NOT_PLAYING"
    assert adapter.commands == []
