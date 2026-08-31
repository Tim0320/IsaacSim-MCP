"""Conversation-oriented wrappers for the consolidated MCP tool profile."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: Any, _get_connection: "Callable[[], IsaacConnection]") -> None:
    def error(message: str) -> str:
        return json.dumps({"status": "error", "code": "INVALID_ARGUMENT", "message": message})

    def invoke(tool_name: str, **kwargs: Any) -> str:
        return mcp.call_registered_tool(tool_name, **kwargs)

    def require(values: Dict[str, Any], *names: str) -> Optional[str]:
        missing = [name for name in names if values.get(name) is None]
        return error(f"{', '.join(missing)} is required for this action") if missing else None

    @mcp.tool("query_prim")
    def query_prim(
        action: Literal["list", "get"],
        root_path: str = "/",
        prim_type: Optional[str] = None,
        prim_path: Optional[str] = None,
    ) -> str:
        """List a USD subtree or get one Prim. Use action=list or action=get."""
        if action == "list":
            return invoke("list_prims", root_path=root_path, prim_type=prim_type)
        invalid = require(locals(), "prim_path")
        return invalid or invoke("get_prim_info", prim_path=prim_path)

    @mcp.tool("semantic_labels")
    def semantic_labels(
        action: Literal["get", "set"],
        prim_path: str,
        taxonomy: Optional[str] = None,
        labels: Optional[List[str]] = None,
        overwrite: bool = False,
        preview: bool = True,
    ) -> str:
        """Read or set Isaac Sim semantic labels on one Prim."""
        if action == "get":
            return invoke("get_semantic_labels", prim_path=prim_path)
        invalid = require(locals(), "taxonomy", "labels")
        return invalid or invoke(
            "set_semantic_labels",
            prim_path=prim_path,
            taxonomy=taxonomy,
            labels=labels,
            overwrite=overwrite,
            preview=preview,
        )

    @mcp.tool("typed_attribute")
    def typed_attribute(
        action: Literal["get", "set"],
        prim_path: str,
        attribute: str,
        type_name: Optional[str] = None,
        value: Any = None,
        custom: bool = True,
        overwrite: bool = False,
        preview: bool = True,
    ) -> str:
        """Read or set one explicitly typed USD attribute."""
        if action == "get":
            return invoke("get_typed_attribute", prim_path=prim_path, attribute=attribute)
        invalid = require(locals(), "type_name", "value")
        return invalid or invoke(
            "set_typed_attribute",
            prim_path=prim_path,
            attribute=attribute,
            type_name=type_name,
            value=value,
            custom=custom,
            overwrite=overwrite,
            preview=preview,
        )

    @mcp.tool("physics_body_config")
    def physics_body_config(
        action: Literal["get", "configure"],
        prim_path: str,
        body_type: str = "dynamic",
        collider_enabled: bool = True,
        approximation: Optional[str] = None,
        mass_kg: Optional[float] = None,
        density_kg_m3: Optional[float] = None,
    ) -> str:
        """Read or atomically configure rigid-body and collider properties."""
        if action == "get":
            return invoke("get_physics_body", prim_path=prim_path)
        return invoke(
            "configure_physics_body",
            prim_path=prim_path,
            body_type=body_type,
            collider_enabled=collider_enabled,
            approximation=approximation,
            mass_kg=mass_kg,
            density_kg_m3=density_kg_m3,
        )

    @mcp.tool("collision_group")
    def collision_group(
        action: Literal["get", "create"],
        group_path: str,
        collider_paths: Optional[List[str]] = None,
        filtered_group_paths: Optional[List[str]] = None,
        invert_filtered_groups: bool = False,
        merge_group_name: Optional[str] = None,
    ) -> str:
        """Read or create a USD collision group."""
        if action == "get":
            return invoke("get_collision_group", group_path=group_path)
        invalid = require(locals(), "collider_paths")
        return invalid or invoke(
            "create_collision_group",
            group_path=group_path,
            collider_paths=collider_paths,
            filtered_group_paths=filtered_group_paths,
            invert_filtered_groups=invert_filtered_groups,
            merge_group_name=merge_group_name,
        )

    @mcp.tool("physics_joint")
    def physics_joint(
        action: Literal["get", "create"],
        joint_path: str,
        joint_type: Optional[str] = None,
        body1: Optional[str] = None,
        body0: Optional[str] = None,
        axis: Optional[str] = None,
        lower_limit: Optional[float] = None,
        upper_limit: Optional[float] = None,
        local_position0: Optional[List[float]] = None,
        local_rotation0: Optional[List[float]] = None,
        local_position1: Optional[List[float]] = None,
        local_rotation1: Optional[List[float]] = None,
        collision_enabled: bool = False,
    ) -> str:
        """Read or create one fixed, revolute, or prismatic physics joint."""
        if action == "get":
            return invoke("get_physics_joint", joint_path=joint_path)
        invalid = require(locals(), "joint_type", "body1")
        return invalid or invoke(
            "create_physics_joint",
            joint_path=joint_path,
            joint_type=joint_type,
            body1=body1,
            body0=body0,
            axis=axis,
            lower_limit=lower_limit,
            upper_limit=upper_limit,
            local_position0=local_position0,
            local_rotation0=local_rotation0,
            local_position1=local_position1,
            local_rotation1=local_rotation1,
            collision_enabled=collision_enabled,
        )

    @mcp.tool("control_timeline")
    def control_timeline(action: Literal["play", "pause", "stop"]) -> str:
        """Play, pause, or stop the Isaac Sim timeline."""
        return invoke({"play": "play_simulation", "pause": "pause_simulation", "stop": "stop_simulation"}[action])

    @mcp.tool("robot_library")
    def robot_library(action: Literal["list", "refresh"] = "list") -> str:
        """List the robot asset library or refresh its discovery cache."""
        return invoke("list_available_robots" if action == "list" else "refresh_robot_library")

    @mcp.tool("control_gripper")
    def control_gripper(
        action: Literal["set_width", "open", "close"],
        prim_path: str,
        profile: str,
        width_m: Optional[float] = None,
    ) -> str:
        """Set a gripper width, open it, or close it using an explicit profile."""
        if action == "set_width":
            invalid = require(locals(), "width_m")
            return invalid or invoke("set_gripper_width", prim_path=prim_path, profile=profile, width_m=width_m)
        return invoke(f"{action}_gripper", prim_path=prim_path, profile=profile)

    @mcp.tool("control_mobile_base_velocity")
    def control_mobile_base_velocity(
        action: Literal["set", "stop"],
        prim_path: str,
        profile: str,
        forward_mps: Optional[float] = None,
        lateral_mps: float = 0.0,
        yaw_radps: float = 0.0,
    ) -> str:
        """Set mobile-base velocity or stop it with a verified zero command."""
        if action == "stop":
            return invoke("stop_mobile_base", prim_path=prim_path, profile=profile)
        invalid = require(locals(), "forward_mps")
        return invalid or invoke(
            "set_mobile_base_velocity",
            prim_path=prim_path,
            profile=profile,
            forward_mps=forward_mps,
            lateral_mps=lateral_mps,
            yaw_radps=yaw_radps,
        )

    @mcp.tool("motion_job")
    def motion_job(action: Literal["get", "cancel"], job_id: str) -> str:
        """Get or cancel an asynchronous robot-motion job."""
        return invoke("get_motion_status" if action == "get" else "cancel_motion", job_id=job_id)

    @mcp.tool("material_definition")
    def material_definition(
        action: Literal["get", "create"],
        material_path: Optional[str] = None,
        material_type: str = "pbr",
        prim_path: Optional[str] = None,
        color: Optional[List[float]] = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
        static_friction: float = 0.5,
        dynamic_friction: float = 0.5,
        restitution: float = 0.0,
    ) -> str:
        """Read a material definition or create a visual/physics material."""
        if action == "get":
            invalid = require(locals(), "material_path")
            return invalid or invoke("get_material", material_path=material_path)
        return invoke(
            "create_material",
            material_type=material_type,
            prim_path=prim_path,
            color=color,
            roughness=roughness,
            metallic=metallic,
            static_friction=static_friction,
            dynamic_friction=dynamic_friction,
            restitution=restitution,
        )

    @mcp.tool("material_binding")
    def material_binding(
        action: Literal["get", "apply"],
        target_prim_path: str,
        material_path: Optional[str] = None,
        material_purpose: Optional[str] = None,
    ) -> str:
        """Read or apply a material binding on one Prim."""
        if action == "get":
            return invoke(
                "get_material_binding",
                target_prim_path=target_prim_path,
                material_purpose=material_purpose or "physics",
            )
        invalid = require(locals(), "material_path")
        return invalid or invoke(
            "apply_material",
            material_path=material_path,
            target_prim_path=target_prim_path,
            material_purpose=material_purpose or "auto",
        )

    @mcp.tool("light_config")
    def light_config(
        action: Literal["create", "modify"],
        prim_path: Optional[str] = None,
        light_type: str = "DistantLight",
        position: Optional[List[float]] = None,
        intensity: Optional[float] = None,
        color: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
    ) -> str:
        """Create a light or modify the supported properties of an existing light."""
        if action == "modify":
            invalid = require(locals(), "prim_path")
            return invalid or invoke("modify_light", prim_path=prim_path, intensity=intensity, color=color)
        return invoke(
            "create_light",
            light_type=light_type,
            position=position,
            intensity=1000.0 if intensity is None else intensity,
            color=color,
            rotation=rotation,
            prim_path=prim_path,
        )

    @mcp.tool("query_human")
    def query_human(
        action: Literal["list", "get"],
        root_prim_path: str = "/World/Characters",
        include_external: bool = True,
        human_path: Optional[str] = None,
    ) -> str:
        """List humans below a root or get one human's state."""
        if action == "list":
            return invoke("list_humans", root_prim_path=root_prim_path, include_external=include_external)
        invalid = require(locals(), "human_path")
        return invalid or invoke("get_human", human_path=human_path)

    @mcp.tool("set_human_action")
    def set_human_action(
        action: Literal["target", "look_at", "idle"],
        human_path: str,
        target_position: Optional[List[float]] = None,
        target_prim_path: Optional[str] = None,
        speed_mps: Optional[float] = None,
        auto_brake: bool = True,
        duration_seconds: float = 0.0,
        facing_position: Optional[List[float]] = None,
        facing_prim_path: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Move, orient, or idle one Behavior Agent human."""
        if action == "target":
            return invoke(
                "set_human_target",
                human_path=human_path,
                target_position=target_position,
                target_prim_path=target_prim_path,
                speed_mps=speed_mps,
                auto_brake=auto_brake,
                preview=preview,
            )
        if action == "look_at":
            return invoke(
                "set_human_look_at",
                human_path=human_path,
                target_position=target_position,
                target_prim_path=target_prim_path,
                duration_seconds=duration_seconds,
                preview=preview,
            )
        return invoke(
            "set_human_idle",
            human_path=human_path,
            facing_position=facing_position,
            facing_prim_path=facing_prim_path,
            preview=preview,
        )

    @mcp.tool("create_ros2_publisher")
    def create_ros2_publisher(
        publisher_type: Literal["clock", "tf", "joint_state", "camera", "lidar"],
        graph_path: Optional[str] = None,
        topic_name: Optional[str] = None,
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: Optional[str] = None,
        preview: bool = True,
        reset_on_stop: bool = True,
        target_prims: Optional[List[str]] = None,
        parent_prim: Optional[str] = None,
        static_publisher: bool = False,
        target_prim: Optional[str] = None,
        camera_prim_path: Optional[str] = None,
        lidar_prim_path: Optional[str] = None,
        render_product_path: Optional[str] = None,
        frame_id: Optional[str] = None,
        camera_type: str = "rgb",
        lidar_type: str = "point_cloud",
        use_system_time: bool = False,
    ) -> str:
        """Create a Clock, TF, JointState, Camera, or LiDAR ROS 2 publisher."""
        if publisher_type == "clock":
            return invoke(
                "create_ros2_clock_publisher",
                graph_path=graph_path or "/World/ROS2Clock",
                topic_name=topic_name or "/clock",
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "default",
                reset_on_stop=reset_on_stop,
                preview=preview,
            )
        invalid = require(locals(), "graph_path")
        if invalid:
            return invalid
        if publisher_type == "tf":
            invalid = require(locals(), "target_prims")
            return invalid or invoke(
                "create_ros2_tf_publisher",
                graph_path=graph_path,
                target_prims=target_prims,
                parent_prim=parent_prim,
                topic_name=topic_name or "/tf",
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "default",
                static_publisher=static_publisher,
                preview=preview,
            )
        if publisher_type == "joint_state":
            invalid = require(locals(), "target_prim")
            return invalid or invoke(
                "create_ros2_joint_state_publisher",
                graph_path=graph_path,
                target_prim=target_prim,
                topic_name=topic_name or "/joint_states",
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "default",
                preview=preview,
            )
        if publisher_type == "camera":
            invalid = require(locals(), "camera_prim_path")
            return invalid or invoke(
                "create_ros2_camera_publisher",
                graph_path=graph_path,
                camera_prim_path=camera_prim_path,
                render_product_path=render_product_path,
                topic_name=topic_name or "/camera/image_raw",
                frame_id=frame_id or "sim_camera",
                camera_type=camera_type,
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "sensor_data",
                use_system_time=use_system_time,
                preview=preview,
            )
        invalid = require(locals(), "lidar_prim_path")
        return invalid or invoke(
            "create_ros2_lidar_publisher",
            graph_path=graph_path,
            lidar_prim_path=lidar_prim_path,
            render_product_path=render_product_path,
            topic_name=topic_name or "/lidar/points",
            frame_id=frame_id or "sim_lidar",
            lidar_type=lidar_type,
            node_namespace=node_namespace,
            domain_id=domain_id,
            qos_profile=qos_profile or "sensor_data",
            use_system_time=use_system_time,
            preview=preview,
        )

    @mcp.tool("sdg_job_control")
    def sdg_job_control(action: Literal["get", "cancel"], job_id: str, preview: bool = True) -> str:
        """Get or cancel one Replicator SDG job."""
        if action == "get":
            return invoke("get_sdg_job_status", job_id=job_id)
        return invoke("cancel_sdg_job", job_id=job_id, preview=preview)

    @mcp.tool("job_control")
    def job_control(action: Literal["get", "cancel"], job_id: str) -> str:
        """Get or cancel one generic managed background job."""
        return invoke("get_job_status" if action == "get" else "cancel_job", job_id=job_id)

    @mcp.tool("query_action_graph")
    def query_action_graph(
        action: Literal["list", "get"],
        root_path: str = "/World",
        include_disabled: bool = True,
        graph_path: Optional[str] = None,
        include_values: bool = False,
        include_script_source: bool = False,
    ) -> str:
        """List Action Graphs or inspect one exact graph."""
        if action == "list":
            return invoke("list_action_graphs", root_path=root_path, include_disabled=include_disabled)
        invalid = require(locals(), "graph_path")
        return invalid or invoke(
            "get_action_graph",
            graph_path=graph_path,
            include_values=include_values,
            include_script_source=include_script_source,
        )

    @mcp.tool("action_graph_connection")
    def action_graph_connection(
        action: Literal["connect", "disconnect"],
        graph_path: str,
        source_attr: str,
        target_attr: str,
        preview: bool = True,
    ) -> str:
        """Connect or disconnect one exact Action Graph edge."""
        return invoke(
            f"{action}_action_graph",
            graph_path=graph_path,
            source_attr=source_attr,
            target_attr=target_attr,
            preview=preview,
        )

    @mcp.tool("script_node_source")
    def script_node_source(
        action: Literal["configure", "reload"],
        graph_path: str,
        node_path: str = "ScriptNode",
        mode: Optional[str] = None,
        inline_script: Optional[str] = None,
        script_file: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Configure or reload one exact ScriptNode source."""
        if action == "configure":
            return invoke(
                "configure_script_node",
                graph_path=graph_path,
                node_path=node_path,
                mode=mode or "inline",
                inline_script=inline_script,
                script_file=script_file,
                preview=preview,
            )
        return invoke(
            "reload_script_node",
            graph_path=graph_path,
            node_path=node_path,
            mode=mode,
            inline_script=inline_script,
            script_file=script_file,
            preview=preview,
        )
