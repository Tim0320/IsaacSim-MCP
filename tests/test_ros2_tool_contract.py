# MIT License
# Copyright (c) 2026 whats2000

"""Public forwarding contracts for Task 17 ROS 2 named workflows."""

import json

from isaac_mcp.tools.ros2 import register_tools


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorate(function):
            self.tools[name] = function
            return function

        return decorate


class _Connection:
    def __init__(self):
        self.calls = []

    def send_command(self, command, params=None):
        self.calls.append((command, params or {}))
        return {"status": "success"}


def _registered():
    mcp, connection = _MCP(), _Connection()
    register_tools(mcp, lambda: connection)
    return mcp.tools, connection


ROS2_TOOLS = {
    "get_ros2_status",
    "list_ros2_workflows",
    "create_ros2_clock_publisher",
    "create_ros2_tf_publisher",
    "create_ros2_joint_state_publisher",
    "create_ros2_camera_publisher",
    "create_ros2_lidar_publisher",
    "delete_ros2_workflow",
}


def test_all_task_17_tools_are_named_and_registered():
    tools, _ = _registered()
    assert set(tools) == ROS2_TOOLS


def test_status_list_and_delete_forward_exact_defaults():
    tools, connection = _registered()

    json.loads(tools["get_ros2_status"]())
    json.loads(tools["list_ros2_workflows"]())
    json.loads(tools["delete_ros2_workflow"]("/World/ROS2Clock"))

    assert connection.calls == [
        ("ros2.get_status", {}),
        ("ros2.list_workflows", {"root_path": "/World"}),
        ("ros2.delete_workflow", {"graph_path": "/World/ROS2Clock", "preview": True}),
    ]


def test_clock_and_tf_default_to_preview_with_explicit_qos():
    tools, connection = _registered()

    tools["create_ros2_clock_publisher"]()
    tools["create_ros2_tf_publisher"]("/World/ROS2TF", ["/World/Robot"])

    assert connection.calls[0] == (
        "ros2.create_clock_publisher",
        {
            "graph_path": "/World/ROS2Clock",
            "topic_name": "/clock",
            "node_namespace": "",
            "domain_id": None,
            "qos_profile": "default",
            "reset_on_stop": True,
            "preview": True,
        },
    )
    assert connection.calls[1] == (
        "ros2.create_tf_publisher",
        {
            "graph_path": "/World/ROS2TF",
            "target_prims": ["/World/Robot"],
            "parent_prim": None,
            "topic_name": "/tf",
            "node_namespace": "",
            "domain_id": None,
            "qos_profile": "default",
            "static_publisher": False,
            "preview": True,
        },
    )


def test_sensor_publishers_default_to_sensor_data_qos():
    tools, connection = _registered()

    tools["create_ros2_camera_publisher"]("/World/CameraROS", "/World/Camera")
    tools["create_ros2_lidar_publisher"]("/World/LidarROS", "/World/Lidar")

    camera = connection.calls[0]
    lidar = connection.calls[1]
    assert camera[0] == "ros2.create_camera_publisher"
    assert camera[1]["camera_prim_path"] == "/World/Camera"
    assert camera[1]["render_product_path"] is None
    assert camera[1]["qos_profile"] == "sensor_data"
    assert camera[1]["camera_type"] == "rgb"
    assert camera[1]["preview"] is True
    assert lidar[0] == "ros2.create_lidar_publisher"
    assert lidar[1]["lidar_prim_path"] == "/World/Lidar"
    assert lidar[1]["render_product_path"] is None
    assert lidar[1]["qos_profile"] == "sensor_data"
    assert lidar[1]["lidar_type"] == "point_cloud"
    assert lidar[1]["preview"] is True
