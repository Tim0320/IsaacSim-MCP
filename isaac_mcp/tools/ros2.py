# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Typed ROS 2 publisher workflow MCP tools."""

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    def send(command: str, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            result = get_connection().send_command(command, params or {})
            return json.dumps(result, indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("get_ros2_status")
    def get_ros2_status() -> str:
        """Read ROS 2 bridge/core/nodes state, domain source, distro, and workflow count."""
        return send("ros2.get_status")

    @mcp.tool("list_ros2_workflows")
    def list_ros2_workflows(root_path: str = "/World") -> str:
        """List MCP-owned ROS 2 publisher graphs below a USD root."""
        return send("ros2.list_workflows", {"root_path": root_path})

    @mcp.tool("create_ros2_clock_publisher")
    def create_ros2_clock_publisher(
        graph_path: str = "/World/ROS2Clock",
        topic_name: str = "/clock",
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: str = "default",
        reset_on_stop: bool = True,
        preview: bool = True,
    ) -> str:
        """Preview or create a playback-driven ROS 2 Clock publisher graph."""
        return send(
            "ros2.create_clock_publisher",
            {
                "graph_path": graph_path,
                "topic_name": topic_name,
                "node_namespace": node_namespace,
                "domain_id": domain_id,
                "qos_profile": qos_profile,
                "reset_on_stop": reset_on_stop,
                "preview": preview,
            },
        )

    @mcp.tool("create_ros2_tf_publisher")
    def create_ros2_tf_publisher(
        graph_path: str,
        target_prims: List[str],
        parent_prim: Optional[str] = None,
        topic_name: str = "/tf",
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: str = "default",
        static_publisher: bool = False,
        preview: bool = True,
    ) -> str:
        """Preview or create a 6.0-style ComputeTransformTree to ROS 2 TF publisher."""
        return send(
            "ros2.create_tf_publisher",
            {
                "graph_path": graph_path,
                "target_prims": target_prims,
                "parent_prim": parent_prim,
                "topic_name": topic_name,
                "node_namespace": node_namespace,
                "domain_id": domain_id,
                "qos_profile": qos_profile,
                "static_publisher": static_publisher,
                "preview": preview,
            },
        )

    @mcp.tool("create_ros2_joint_state_publisher")
    def create_ros2_joint_state_publisher(
        graph_path: str,
        target_prim: str,
        topic_name: str = "/joint_states",
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: str = "default",
        preview: bool = True,
    ) -> str:
        """Preview or create an IsaacReadJointState ROS 2 JointState publisher graph."""
        return send(
            "ros2.create_joint_state_publisher",
            {
                "graph_path": graph_path,
                "target_prim": target_prim,
                "topic_name": topic_name,
                "node_namespace": node_namespace,
                "domain_id": domain_id,
                "qos_profile": qos_profile,
                "preview": preview,
            },
        )

    @mcp.tool("create_ros2_camera_publisher")
    def create_ros2_camera_publisher(
        graph_path: str,
        camera_prim_path: str,
        render_product_path: Optional[str] = None,
        topic_name: str = "/camera/image_raw",
        frame_id: str = "sim_camera",
        camera_type: str = "rgb",
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: str = "sensor_data",
        use_system_time: bool = False,
        preview: bool = True,
    ) -> str:
        """Preview or create a ROS2CameraHelper publisher for an MCP camera runtime.

        The camera prim must first be created with create_camera. Its owned render
        product is resolved automatically; render_product_path is an explicit
        override for externally-created render products.
        """
        return send(
            "ros2.create_camera_publisher",
            {
                "graph_path": graph_path,
                "camera_prim_path": camera_prim_path,
                "render_product_path": render_product_path,
                "topic_name": topic_name,
                "frame_id": frame_id,
                "camera_type": camera_type,
                "node_namespace": node_namespace,
                "domain_id": domain_id,
                "qos_profile": qos_profile,
                "use_system_time": use_system_time,
                "preview": preview,
            },
        )

    @mcp.tool("create_ros2_lidar_publisher")
    def create_ros2_lidar_publisher(
        graph_path: str,
        lidar_prim_path: str,
        render_product_path: Optional[str] = None,
        topic_name: str = "/lidar/points",
        frame_id: str = "sim_lidar",
        lidar_type: str = "point_cloud",
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: str = "sensor_data",
        use_system_time: bool = False,
        preview: bool = True,
    ) -> str:
        """Preview or create a ROS2RtxLidarHelper publisher for an MCP RTX LiDAR runtime.

        The LiDAR prim must first be created with create_lidar. Its owned render
        product is resolved automatically; render_product_path is an explicit
        override for externally-created render products.
        """
        return send(
            "ros2.create_lidar_publisher",
            {
                "graph_path": graph_path,
                "lidar_prim_path": lidar_prim_path,
                "render_product_path": render_product_path,
                "topic_name": topic_name,
                "frame_id": frame_id,
                "lidar_type": lidar_type,
                "node_namespace": node_namespace,
                "domain_id": domain_id,
                "qos_profile": qos_profile,
                "use_system_time": use_system_time,
                "preview": preview,
            },
        )

    @mcp.tool("delete_ros2_workflow")
    def delete_ros2_workflow(graph_path: str, preview: bool = True) -> str:
        """Preview or delete one MCP-owned ROS 2 workflow; foreign graphs are refused."""
        return send("ros2.delete_workflow", {"graph_path": graph_path, "preview": preview})
