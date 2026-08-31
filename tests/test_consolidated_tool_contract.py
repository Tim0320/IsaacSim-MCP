"""Argument routing contracts for the consolidated MCP profile."""

from __future__ import annotations

import json

import pytest

from isaac_mcp.tools import register_all_tools


class _FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def send_command(self, command: str, params=None):
        self.calls.append((command, params or {}))
        return {"status": "success", "data": {}}


def _tools(monkeypatch):
    monkeypatch.setenv("ISAAC_MCP_TOOL_PROFILE", "consolidated")
    mcp = _FakeMCP()
    connection = _Connection()
    register_all_tools(mcp, lambda: connection)
    return mcp.tools, connection


def _call(tool, **kwargs):
    response = json.loads(tool(**kwargs))
    assert response["status"] == "success"


def test_scene_physics_and_timeline_dispatch(monkeypatch) -> None:
    tools, connection = _tools(monkeypatch)

    _call(tools["query_prim"], action="list", root_path="/World", prim_type="Mesh")
    _call(tools["query_prim"], action="get", prim_path="/World/Cube")
    _call(tools["physics_body_config"], action="get", prim_path="/World/Cube")
    _call(tools["control_timeline"], action="pause")

    assert connection.calls == [
        ("scene.list_prims", {"root_path": "/World", "prim_type": "Mesh"}),
        ("scene.get_prim_info", {"prim_path": "/World/Cube"}),
        ("physics.get_body", {"prim_path": "/World/Cube"}),
        ("simulation.pause", {}),
    ]


def test_robot_camera_and_job_dispatch(monkeypatch) -> None:
    tools, connection = _tools(monkeypatch)

    _call(
        tools["control_gripper"],
        action="set_width",
        prim_path="/World/Panda",
        profile="franka_parallel_gripper",
        width_m=0.03,
    )
    _call(
        tools["capture_camera_output"],
        prim_path="/World/Camera",
        output_type="rgb",
        return_mode="artifact",
        inline_max_bytes=4096,
    )
    _call(tools["motion_job"], action="cancel", job_id="motion-1")

    assert connection.calls == [
        (
            "controllers.set_gripper_width",
            {"prim_path": "/World/Panda", "profile": "franka_parallel_gripper", "width_m": 0.03},
        ),
        (
            "sensors.capture_image",
            {
                "prim_path": "/World/Camera",
                "return_mode": "artifact",
                "inline_max_bytes": 4096,
            },
        ),
        ("motion.cancel", {"job_id": "motion-1"}),
    ]


def test_ros_human_and_graph_dispatch(monkeypatch) -> None:
    tools, connection = _tools(monkeypatch)

    _call(
        tools["create_ros2_publisher"],
        publisher_type="joint_state",
        graph_path="/World/ROS2JointState",
        target_prim="/World/Panda",
        preview=True,
    )
    _call(
        tools["set_human_action"],
        action="look_at",
        human_path="/World/Characters/Human",
        target_prim_path="/World/Cube",
        preview=True,
    )
    _call(
        tools["action_graph_connection"],
        action="disconnect",
        graph_path="/World/ActionGraph",
        source_attr="A.outputs:value",
        target_attr="B.inputs:value",
        preview=False,
    )

    assert connection.calls == [
        (
            "ros2.create_joint_state_publisher",
            {
                "graph_path": "/World/ROS2JointState",
                "target_prim": "/World/Panda",
                "topic_name": "/joint_states",
                "node_namespace": "",
                "domain_id": None,
                "qos_profile": "default",
                "preview": True,
            },
        ),
        (
            "humans.look_at",
            {
                "human_path": "/World/Characters/Human",
                "target_prim_path": "/World/Cube",
                "duration_seconds": 0.0,
                "preview": True,
            },
        ),
        (
            "graphs.disconnect_action_graph",
            {
                "graph_path": "/World/ActionGraph",
                "source_attr": "A.outputs:value",
                "target_attr": "B.inputs:value",
                "preview": False,
            },
        ),
    ]


def test_required_branch_argument_returns_clear_error(monkeypatch) -> None:
    tools, connection = _tools(monkeypatch)

    response = json.loads(tools["query_prim"](action="get"))

    assert response["status"] == "error"
    assert response["code"] == "INVALID_ARGUMENT"
    assert "prim_path" in response["message"]
    assert connection.calls == []


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "expected_command"),
    [
        ("semantic_labels", {"action": "get", "prim_path": "/World/Cube"}, "stage.get_semantics"),
        (
            "semantic_labels",
            {"action": "set", "prim_path": "/World/Cube", "taxonomy": "class", "labels": ["cube"]},
            "stage.set_semantics",
        ),
        (
            "typed_attribute",
            {"action": "get", "prim_path": "/World/Cube", "attribute": "test:value"},
            "stage.get_attribute",
        ),
        (
            "typed_attribute",
            {
                "action": "set",
                "prim_path": "/World/Cube",
                "attribute": "test:value",
                "type_name": "int",
                "value": 0,
            },
            "stage.set_attribute",
        ),
        (
            "physics_body_config",
            {"action": "configure", "prim_path": "/World/Cube"},
            "physics.configure_body",
        ),
        ("collision_group", {"action": "get", "group_path": "/World/Group"}, "physics.get_collision_group"),
        (
            "collision_group",
            {"action": "create", "group_path": "/World/Group", "collider_paths": ["/World/Cube"]},
            "physics.create_collision_group",
        ),
        ("physics_joint", {"action": "get", "joint_path": "/World/Joint"}, "physics.get_joint"),
        (
            "physics_joint",
            {"action": "create", "joint_path": "/World/Joint", "joint_type": "fixed", "body1": "/World/Cube"},
            "physics.create_joint",
        ),
        ("control_timeline", {"action": "play"}, "simulation.play"),
        ("control_timeline", {"action": "stop"}, "simulation.stop"),
        ("robot_library", {"action": "list"}, "robots.list"),
        ("robot_library", {"action": "refresh"}, "robots.refresh"),
        (
            "get_joint_state",
            {"prim_path": "/World/Panda", "joint_names": None, "joint_indices": None},
            "robots.get_joint_state",
        ),
        (
            "set_joint_command",
            {"prim_path": "/World/Panda", "mode": "position", "values": [0.0]},
            "robots.set_joint_command",
        ),
        (
            "control_gripper",
            {"action": "open", "prim_path": "/World/Panda", "profile": "franka_parallel_gripper"},
            "controllers.open_gripper",
        ),
        (
            "control_gripper",
            {"action": "close", "prim_path": "/World/Panda", "profile": "franka_parallel_gripper"},
            "controllers.close_gripper",
        ),
        (
            "control_mobile_base_velocity",
            {
                "action": "set",
                "prim_path": "/World/Jetbot",
                "profile": "nvidia_jetbot_differential",
                "forward_mps": 0.2,
            },
            "controllers.set_mobile_base_velocity",
        ),
        (
            "control_mobile_base_velocity",
            {"action": "stop", "prim_path": "/World/Jetbot", "profile": "nvidia_jetbot_differential"},
            "controllers.stop_mobile_base",
        ),
        ("motion_job", {"action": "get", "job_id": "motion-1"}, "motion.get_status"),
        (
            "material_definition",
            {"action": "create", "material_type": "pbr"},
            "materials.create",
        ),
        (
            "material_definition",
            {"action": "get", "material_path": "/World/Looks/Material"},
            "materials.get",
        ),
        (
            "material_binding",
            {"action": "get", "target_prim_path": "/World/Cube"},
            "materials.get_binding",
        ),
        (
            "material_binding",
            {"action": "apply", "target_prim_path": "/World/Cube", "material_path": "/World/Looks/Material"},
            "materials.apply",
        ),
        ("light_config", {"action": "create"}, "lighting.create"),
        ("light_config", {"action": "modify", "prim_path": "/World/Light"}, "lighting.modify"),
        ("query_human", {"action": "list"}, "humans.list"),
        ("query_human", {"action": "get", "human_path": "/World/Characters/Human"}, "humans.get"),
        (
            "set_human_action",
            {"action": "target", "human_path": "/World/Characters/Human", "target_position": [1.0, 0.0, 0.0]},
            "humans.set_target",
        ),
        (
            "set_human_action",
            {"action": "idle", "human_path": "/World/Characters/Human"},
            "humans.idle",
        ),
        ("create_ros2_publisher", {"publisher_type": "clock"}, "ros2.create_clock_publisher"),
        (
            "create_ros2_publisher",
            {"publisher_type": "tf", "graph_path": "/World/TF", "target_prims": ["/World/Panda"]},
            "ros2.create_tf_publisher",
        ),
        (
            "create_ros2_publisher",
            {"publisher_type": "camera", "graph_path": "/World/CameraGraph", "camera_prim_path": "/World/Camera"},
            "ros2.create_camera_publisher",
        ),
        (
            "create_ros2_publisher",
            {"publisher_type": "lidar", "graph_path": "/World/LidarGraph", "lidar_prim_path": "/World/Lidar"},
            "ros2.create_lidar_publisher",
        ),
        ("sdg_job_control", {"action": "get", "job_id": "sdg-1"}, "replicator.get_job_status"),
        ("sdg_job_control", {"action": "cancel", "job_id": "sdg-1"}, "replicator.cancel_job"),
        ("job_control", {"action": "get", "job_id": "job-1"}, "job.get_status"),
        ("job_control", {"action": "cancel", "job_id": "job-1"}, "job.cancel"),
        ("query_action_graph", {"action": "list"}, "graphs.list_action_graphs"),
        (
            "query_action_graph",
            {"action": "get", "graph_path": "/World/ActionGraph"},
            "graphs.get_action_graph",
        ),
        (
            "action_graph_connection",
            {
                "action": "connect",
                "graph_path": "/World/ActionGraph",
                "source_attr": "A.outputs:value",
                "target_attr": "B.inputs:value",
            },
            "graphs.connect_action_graph",
        ),
        (
            "script_node_source",
            {"action": "configure", "graph_path": "/World/ActionGraph", "inline_script": "def compute(db): pass"},
            "graphs.configure_script_node",
        ),
        (
            "script_node_source",
            {"action": "reload", "graph_path": "/World/ActionGraph"},
            "graphs.reload_script_node",
        ),
    ],
)
def test_every_consolidated_branch_routes_to_existing_contract(
    monkeypatch, tool_name: str, kwargs: dict, expected_command: str
) -> None:
    tools, connection = _tools(monkeypatch)

    _call(tools[tool_name], **kwargs)

    assert connection.calls[-1][0] == expected_command
