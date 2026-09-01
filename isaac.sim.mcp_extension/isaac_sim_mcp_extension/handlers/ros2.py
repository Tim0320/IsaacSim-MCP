# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""ROS 2 publisher-workflow command handlers for Isaac Sim 6.0."""

from __future__ import annotations

import asyncio
import inspect
import os
import re
from typing import Any, Dict, List, Optional, Sequence

from ..adapters.base import IsaacAdapterBase
from . import graphs

SCHEMA_VERSION = "1.0"
REQUIRED_EXTENSIONS = ("isaacsim.ros2.bridge", "isaacsim.ros2.core", "isaacsim.ros2.nodes")
MARKER_SCHEMA = "isaacSimMcpRos2Schema"
MARKER_TYPE = "isaacSimMcpRos2Workflow"
MARKER_TOPIC = "isaacSimMcpRos2Topic"
QOS_PROFILES = {
    "default": "Default for publishers/subscribers",
    "sensor_data": "Sensor Data",
    "system_default": "System Default",
    "services": "Services",
}
CAMERA_TYPES = {
    "rgb",
    "rgb_h264",
    "depth",
    "depth_pcl",
    "instance_segmentation",
    "semantic_segmentation",
    "bbox_2d_tight",
    "bbox_2d_loose",
    "bbox_3d",
}
LIDAR_TYPES = {"laser_scan", "point_cloud"}
_ROS_NAME_RE = re.compile(r"^/?(?:[A-Za-z_][A-Za-z0-9_]*)(?:/[A-Za-z_][A-Za-z0-9_]*)*$")
_FRAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_/]*$")


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["ros2.get_status"] = lambda **p: get_ros2_status(adapter, **p)
    registry["ros2.list_workflows"] = lambda **p: list_ros2_workflows(adapter, **p)
    registry["ros2.create_clock_publisher"] = lambda **p: create_clock_publisher(adapter, **p)
    registry["ros2.create_tf_publisher"] = lambda **p: create_tf_publisher(adapter, **p)
    registry["ros2.create_joint_state_publisher"] = lambda **p: create_joint_state_publisher(adapter, **p)
    registry["ros2.create_camera_publisher"] = lambda **p: create_camera_publisher(adapter, **p)
    registry["ros2.create_lidar_publisher"] = lambda **p: create_lidar_publisher(adapter, **p)
    registry["ros2.delete_workflow"] = lambda **p: delete_ros2_workflow(adapter, **p)


def _error(code: str, message: str, *, status: str = "error", **fields: Any) -> Dict[str, Any]:
    return {"status": status, "code": code, "message": message, **fields}


def _success(code: str, message: str, data: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    return {"status": "success", "code": code, "message": message, "data": data, **fields}


def _run_or_return(awaitable):
    """Run direct offline calls, but let Kit's dispatcher await on its loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    return awaitable


async def _await_maybe(value):
    return await value if inspect.isawaitable(value) else value


def _extension_states() -> Dict[str, Dict[str, Any]]:
    try:
        import omni.kit.app

        manager = omni.kit.app.get_app().get_extension_manager()
    except Exception:
        manager = None
    result: Dict[str, Dict[str, Any]] = {}
    for name in REQUIRED_EXTENSIONS:
        if manager is None:
            result[name] = {"state": "unknown", "enabled": None, "version": None}
            continue
        try:
            enabled = bool(manager.is_extension_enabled(name))
            version = None
            if enabled:
                extension_id = manager.get_enabled_extension_id(name)
                raw = manager.get_extension_dict(extension_id) if extension_id else {}
                raw = raw.get_dict() if hasattr(raw, "get_dict") else raw
                package = raw.get("package", {}) if isinstance(raw, dict) else {}
                package = package.get_dict() if hasattr(package, "get_dict") else package
                version = package.get("version") if isinstance(package, dict) else None
            result[name] = {"state": "enabled" if enabled else "disabled", "enabled": enabled, "version": version}
        except Exception:
            result[name] = {"state": "unknown", "enabled": None, "version": None}
    return result


def _prerequisite_error(states: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    missing = [name for name in REQUIRED_EXTENSIONS if states.get(name, {}).get("enabled") is not True]
    if not missing:
        return None
    return _error(
        "ROS2_PREREQUISITE_MISSING",
        "ROS 2 publisher workflows require the bridge, core, and nodes extensions to be enabled before use",
        status="unsupported",
        data={
            "missing_extensions": missing,
            "extensions": states,
            "launch_requirement": "Enable isaacsim.ros2.bridge with a sourced or bundled ROS 2 environment, then restart Isaac Sim",
        },
    )


def _validate_topic(value: str) -> Optional[Dict[str, Any]]:
    if not value or not _ROS_NAME_RE.fullmatch(str(value)):
        return _error("INVALID_ROS2_TOPIC", f"Invalid ROS 2 topic name: {value!r}")
    return None


def _validate_namespace(value: str) -> Optional[Dict[str, Any]]:
    if value and not _ROS_NAME_RE.fullmatch(str(value)):
        return _error("INVALID_ROS2_NAMESPACE", f"Invalid ROS 2 node namespace: {value!r}")
    return None


def _validate_frame(value: str) -> Optional[Dict[str, Any]]:
    if not value or value.startswith("/") or not _FRAME_RE.fullmatch(str(value)):
        return _error("INVALID_ROS2_FRAME_ID", f"frame_id must be non-empty and relative: {value!r}")
    return None


def _validate_domain(domain_id: Optional[int]) -> Optional[Dict[str, Any]]:
    if domain_id is not None and (
        isinstance(domain_id, bool) or not isinstance(domain_id, int) or not 0 <= domain_id <= 232
    ):
        return _error(
            "INVALID_ROS2_DOMAIN_ID", "domain_id must be an integer from 0 through 232, or null to use ROS_DOMAIN_ID"
        )
    return None


def _validate_qos(qos_profile: str) -> Optional[Dict[str, Any]]:
    if qos_profile not in QOS_PROFILES:
        return _error("INVALID_ROS2_QOS_PROFILE", f"qos_profile must be one of: {', '.join(QOS_PROFILES)}")
    return None


def _stage():
    import omni.usd

    return omni.usd.get_context().get_stage()


def _valid_prim(path: str) -> bool:
    try:
        prim = _stage().GetPrimAtPath(str(path))
        return bool(prim and prim.IsValid())
    except Exception:
        return False


def _marker(graph_path: str) -> Optional[Dict[str, str]]:
    try:
        prim = _stage().GetPrimAtPath(graph_path)
        if not prim or not prim.IsValid():
            return None
        workflow = prim.GetCustomDataByKey(MARKER_TYPE)
        schema = prim.GetCustomDataByKey(MARKER_SCHEMA)
        if not workflow or schema != SCHEMA_VERSION:
            return None
        return {
            "schema_version": str(schema),
            "workflow_type": str(workflow),
            "topic_name": str(prim.GetCustomDataByKey(MARKER_TOPIC) or ""),
        }
    except Exception:
        return None


def _set_marker(graph_path: str, workflow_type: str, topic_name: str) -> Dict[str, str]:
    prim = _stage().GetPrimAtPath(graph_path)
    if not prim or not prim.IsValid():
        raise RuntimeError(f"Created graph has no backing USD prim: {graph_path}")
    prim.SetCustomDataByKey(MARKER_SCHEMA, SCHEMA_VERSION)
    prim.SetCustomDataByKey(MARKER_TYPE, workflow_type)
    prim.SetCustomDataByKey(MARKER_TOPIC, topic_name)
    marker = _marker(graph_path)
    if marker is None or marker["workflow_type"] != workflow_type or marker["topic_name"] != topic_name:
        raise RuntimeError("ROS 2 workflow ownership marker read-back mismatch")
    return marker


def _base_spec(domain_id: Optional[int], qos_profile: str, *, include_time: bool = True) -> Dict[str, Any]:
    nodes = [
        {"path": "OnPlaybackTick", "type": "omni.graph.action.OnPlaybackTick"},
        {"path": "Context", "type": "isaacsim.ros2.bridge.ROS2Context"},
        {"path": "QoSProfile", "type": "isaacsim.ros2.bridge.ROS2QoSProfile"},
    ]
    values = [
        {"attr": "Context.inputs:useDomainIDEnvVar", "value": domain_id is None},
        {"attr": "Context.inputs:domain_id", "value": int(domain_id or 0)},
        {"attr": "QoSProfile.inputs:createProfile", "value": QOS_PROFILES[qos_profile]},
    ]
    if include_time:
        nodes.append({"path": "ReadSimTime", "type": "isaacsim.core.nodes.IsaacReadSimulationTime"})
    return {"nodes": nodes, "values": values, "connections": []}


def _publisher_connections(
    publisher: str, *, include_time: bool = True, exec_source: str = "OnPlaybackTick.outputs:tick"
) -> List[List[str]]:
    result = [
        [exec_source, f"{publisher}.inputs:execIn"],
        ["Context.outputs:context", f"{publisher}.inputs:context"],
        ["QoSProfile.outputs:qosProfile", f"{publisher}.inputs:qosProfile"],
    ]
    if include_time:
        result.append(["ReadSimTime.outputs:simulationTime", f"{publisher}.inputs:timeStamp"])
    return result


def _workflow_spec(workflow_type: str, **params: Any) -> Dict[str, Any]:
    domain_id = params.get("domain_id")
    qos_profile = params["qos_profile"]
    topic_name = params["topic_name"]
    namespace = params.get("node_namespace", "")
    include_time = workflow_type not in {"camera", "lidar"}
    spec = _base_spec(domain_id, qos_profile, include_time=include_time)
    nodes: List[Dict[str, str]] = spec["nodes"]
    values: List[Dict[str, Any]] = spec["values"]
    connections: List[List[str]] = spec["connections"]

    if workflow_type == "clock":
        nodes.append({"path": "Publisher", "type": "isaacsim.ros2.bridge.ROS2PublishClock"})
        values.extend(
            [
                {"attr": "ReadSimTime.inputs:resetOnStop", "value": bool(params["reset_on_stop"])},
                {"attr": "Publisher.inputs:topicName", "value": topic_name},
                {"attr": "Publisher.inputs:nodeNamespace", "value": namespace},
            ]
        )
        connections.extend(_publisher_connections("Publisher"))
    elif workflow_type == "tf":
        nodes.extend(
            [
                {"path": "ComputeTF", "type": "isaacsim.core.nodes.IsaacComputeTransformTree"},
                {"path": "Publisher", "type": "isaacsim.ros2.bridge.ROS2PublishTransformTree"},
            ]
        )
        values.extend(
            [
                {"attr": "ComputeTF.inputs:targetPrims", "value": list(params["target_prims"])},
                {"attr": "Publisher.inputs:topicName", "value": topic_name},
                {"attr": "Publisher.inputs:nodeNamespace", "value": namespace},
                {"attr": "Publisher.inputs:staticPublisher", "value": bool(params["static_publisher"])},
            ]
        )
        if params.get("parent_prim"):
            values.append({"attr": "ComputeTF.inputs:parentPrim", "value": params["parent_prim"]})
        connections.extend(
            [
                ["OnPlaybackTick.outputs:tick", "ComputeTF.inputs:execIn"],
                ["ComputeTF.outputs:execOut", "Publisher.inputs:execIn"],
                ["ComputeTF.outputs:parentFrames", "Publisher.inputs:parentFrames"],
                ["ComputeTF.outputs:childFrames", "Publisher.inputs:childFrames"],
                ["ComputeTF.outputs:translations", "Publisher.inputs:translations"],
                ["ComputeTF.outputs:orientations", "Publisher.inputs:orientations"],
                ["Context.outputs:context", "Publisher.inputs:context"],
                ["QoSProfile.outputs:qosProfile", "Publisher.inputs:qosProfile"],
                ["ReadSimTime.outputs:simulationTime", "Publisher.inputs:timeStamp"],
            ]
        )
    elif workflow_type == "joint_state":
        nodes.extend(
            [
                {"path": "ReadJointState", "type": "isaacsim.sensors.physics.IsaacReadJointState"},
                {"path": "Publisher", "type": "isaacsim.ros2.bridge.ROS2PublishJointState"},
            ]
        )
        values.extend(
            [
                {"attr": "ReadJointState.inputs:prim", "value": [params["target_prim"]]},
                {"attr": "Publisher.inputs:topicName", "value": topic_name},
                {"attr": "Publisher.inputs:nodeNamespace", "value": namespace},
            ]
        )
        connections.extend(
            [
                ["OnPlaybackTick.outputs:tick", "ReadJointState.inputs:execIn"],
                ["ReadJointState.outputs:execOut", "Publisher.inputs:execIn"],
                ["ReadJointState.outputs:jointNames", "Publisher.inputs:jointNames"],
                ["ReadJointState.outputs:jointPositions", "Publisher.inputs:jointPositions"],
                ["ReadJointState.outputs:jointVelocities", "Publisher.inputs:jointVelocities"],
                ["ReadJointState.outputs:jointEfforts", "Publisher.inputs:jointEfforts"],
                ["ReadJointState.outputs:jointDofTypes", "Publisher.inputs:jointDofTypes"],
                ["ReadJointState.outputs:stageMetersPerUnit", "Publisher.inputs:stageMetersPerUnit"],
                ["ReadJointState.outputs:sensorTime", "Publisher.inputs:sensorTime"],
                ["ReadSimTime.outputs:simulationTime", "Publisher.inputs:timeStamp"],
                ["Context.outputs:context", "Publisher.inputs:context"],
                ["QoSProfile.outputs:qosProfile", "Publisher.inputs:qosProfile"],
            ]
        )
    else:
        is_camera = workflow_type == "camera"
        node_type = "isaacsim.ros2.bridge.ROS2CameraHelper" if is_camera else "isaacsim.ros2.bridge.ROS2RtxLidarHelper"
        sensor_type = params["camera_type"] if is_camera else params["lidar_type"]
        nodes.append({"path": "Publisher", "type": node_type})
        values.extend(
            [
                {"attr": "Publisher.inputs:renderProductPath", "value": params["render_product_path"]},
                {"attr": "Publisher.inputs:type", "value": sensor_type},
                {"attr": "Publisher.inputs:topicName", "value": topic_name},
                {"attr": "Publisher.inputs:frameId", "value": params["frame_id"]},
                {"attr": "Publisher.inputs:nodeNamespace", "value": namespace},
                {"attr": "Publisher.inputs:useSystemTime", "value": bool(params["use_system_time"])},
            ]
        )
        connections.extend(_publisher_connections("Publisher", include_time=False))
    return spec


def _common_validation(
    graph_path: str, topic_name: str, node_namespace: str, domain_id: Optional[int], qos_profile: str
) -> Optional[Dict[str, Any]]:
    for result in (
        graphs._validate_graph_path(graph_path),
        _validate_topic(topic_name),
        _validate_namespace(node_namespace),
        _validate_domain(domain_id),
        _validate_qos(qos_profile),
    ):
        if result:
            return result
    return None


async def _create_workflow(
    adapter: IsaacAdapterBase,
    workflow_type: str,
    *,
    graph_path: str,
    topic_name: str,
    preview: bool,
    **params: Any,
) -> Dict[str, Any]:
    namespace = str(params.get("node_namespace", ""))
    domain_id = params.get("domain_id")
    qos_profile = str(params.get("qos_profile", "default"))
    invalid = _common_validation(graph_path, topic_name, namespace, domain_id, qos_profile)
    if invalid:
        return invalid
    stopped = graphs._require_stopped(adapter)
    if stopped:
        return stopped
    prerequisite = _prerequisite_error(_extension_states())
    if prerequisite:
        return prerequisite
    if graphs._graph_or_none(graph_path) is not None:
        return _error("GRAPH_ALREADY_EXISTS", f"Action Graph already exists: {graph_path}")
    spec_params = dict(params)
    spec_params.update(
        topic_name=topic_name,
        node_namespace=namespace,
        domain_id=domain_id,
        qos_profile=qos_profile,
    )
    spec = _workflow_spec(workflow_type, **spec_params)
    plan = {
        "preview": bool(preview),
        "graph_path": graph_path,
        "workflow_type": workflow_type,
        "topic_name": topic_name,
        "domain": {"source": "ROS_DOMAIN_ID" if domain_id is None else "explicit", "domain_id": domain_id},
        "qos_profile": qos_profile,
        "active_on_play_only": True,
        "node_count": len(spec["nodes"]),
        "connection_count": len(spec["connections"]),
    }
    if preview:
        return _success("ROS2_WORKFLOW_PREVIEW", "ROS 2 workflow preview validated", plan)
    created = await _await_maybe(
        graphs.create_action_graph(
            adapter,
            graph_path=graph_path,
            nodes=spec["nodes"],
            connections=spec["connections"],
            values=spec["values"],
            evaluator="execution",
        )
    )
    if created.get("status") != "success":
        return created
    try:
        marker = _set_marker(graph_path, workflow_type, topic_name)
    except Exception as exc:
        rollback = await _await_maybe(graphs.delete_action_graph(adapter, graph_path, preview=False))
        rolled_back = rollback.get("status") == "success"
        return _error(
            "ROS2_WORKFLOW_ROLLED_BACK" if rolled_back else "ROS2_WORKFLOW_ROLLBACK_FAILED",
            f"Workflow graph was created but ownership marker failed: {exc}",
            readback={"rolled_back": rolled_back, "graph_present": graphs._graph_or_none(graph_path) is not None},
        )
    data = dict(plan)
    data["preview"] = False
    return _success(
        "ROS2_WORKFLOW_CREATED",
        f"Created ROS 2 {workflow_type} workflow at {graph_path}",
        data,
        readback={
            "ownership": marker,
            "graph": created.get("readback"),
            "external_subscriber_verified": False,
        },
    )


def get_ros2_status(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    del adapter
    states = _extension_states()
    prerequisite = _prerequisite_error(states)
    try:
        import carb.settings

        settings = carb.settings.get_settings()
        ros_distro_setting = settings.get("/exts/isaacsim.ros2.bridge/ros_distro")
    except Exception:
        ros_distro_setting = None
    listed = list_ros2_workflows(None)
    workflow_count = listed.get("data", {}).get("workflow_count") if listed.get("status") == "success" else None
    env_domain = os.environ.get("ROS_DOMAIN_ID")
    data = {
        "extensions": states,
        "prerequisites_met": prerequisite is None,
        "missing_extensions": prerequisite.get("data", {}).get("missing_extensions", []) if prerequisite else [],
        "domain": {
            "environment_value": int(env_domain) if env_domain and env_domain.isdigit() else env_domain,
            "default_when_unset": 0,
            "per_workflow_override_supported": True,
        },
        "ros_distro": os.environ.get("ROS_DISTRO"),
        "ros_distro_setting": ros_distro_setting,
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION"),
        "publishers_active_on_play_only": True,
        "external_subscriber_verified": False,
        "workflow_count": workflow_count,
    }
    return _success("ROS2_STATUS_READ", "Read ROS 2 runtime status", data)


def list_ros2_workflows(adapter: Optional[IsaacAdapterBase], root_path: str = "/World") -> Dict[str, Any]:
    del adapter
    invalid = graphs._validate_graph_path(root_path)
    if invalid:
        return invalid
    try:
        import omni.graph.core as og

        prefix = root_path.rstrip("/") + "/"
        records = []
        for graph in og.get_all_graphs():
            if graph is None or not graph.is_valid():
                continue
            path = str(graph.get_path_to_graph())
            if path != root_path and not path.startswith(prefix):
                continue
            marker = _marker(path)
            if marker is None:
                continue
            records.append(
                {
                    "graph_path": path,
                    **marker,
                    "enabled": not bool(graph.is_disabled()),
                    "node_count": len(graph.get_nodes()),
                    "active_on_play_only": True,
                }
            )
        records.sort(key=lambda item: item["graph_path"])
        return _success(
            "ROS2_WORKFLOWS_LISTED",
            f"Found {len(records)} MCP-owned ROS 2 workflow(s)",
            {"root_path": root_path, "workflow_count": len(records), "workflows": records},
        )
    except Exception as exc:
        return _error("ROS2_WORKFLOW_QUERY_FAILED", str(exc))


def create_clock_publisher(
    adapter: IsaacAdapterBase,
    graph_path: str = "/World/ROS2Clock",
    topic_name: str = "/clock",
    node_namespace: str = "",
    domain_id: Optional[int] = None,
    qos_profile: str = "default",
    reset_on_stop: bool = True,
    preview: bool = True,
) -> Dict[str, Any]:
    return _run_or_return(
        _create_workflow(
            adapter,
            "clock",
            graph_path=graph_path,
            topic_name=topic_name,
            node_namespace=node_namespace,
            domain_id=domain_id,
            qos_profile=qos_profile,
            reset_on_stop=reset_on_stop,
            preview=bool(preview),
        )
    )


def create_tf_publisher(
    adapter: IsaacAdapterBase,
    graph_path: str,
    target_prims: Sequence[str],
    parent_prim: Optional[str] = None,
    topic_name: str = "/tf",
    node_namespace: str = "",
    domain_id: Optional[int] = None,
    qos_profile: str = "default",
    static_publisher: bool = False,
    preview: bool = True,
) -> Dict[str, Any]:
    targets = [str(path) for path in target_prims or []]
    if not targets or any(not path.startswith("/") or not _valid_prim(path) for path in targets):
        return _error(
            "ROS2_TARGET_PRIM_NOT_FOUND", "Every target_prims entry must reference an existing absolute USD prim"
        )
    if parent_prim and (not str(parent_prim).startswith("/") or not _valid_prim(str(parent_prim))):
        return _error("ROS2_PARENT_PRIM_NOT_FOUND", f"Parent prim not found: {parent_prim}")
    return _run_or_return(
        _create_workflow(
            adapter,
            "tf",
            graph_path=graph_path,
            topic_name=topic_name,
            target_prims=targets,
            parent_prim=parent_prim,
            node_namespace=node_namespace,
            domain_id=domain_id,
            qos_profile=qos_profile,
            static_publisher=static_publisher,
            preview=bool(preview),
        )
    )


def create_joint_state_publisher(
    adapter: IsaacAdapterBase,
    graph_path: str,
    target_prim: str,
    topic_name: str = "/joint_states",
    node_namespace: str = "",
    domain_id: Optional[int] = None,
    qos_profile: str = "default",
    preview: bool = True,
) -> Dict[str, Any]:
    if not str(target_prim).startswith("/") or not _valid_prim(target_prim):
        return _error("ROS2_TARGET_PRIM_NOT_FOUND", f"Target prim not found: {target_prim}")
    return _run_or_return(
        _create_workflow(
            adapter,
            "joint_state",
            graph_path=graph_path,
            topic_name=topic_name,
            target_prim=target_prim,
            node_namespace=node_namespace,
            domain_id=domain_id,
            qos_profile=qos_profile,
            preview=bool(preview),
        )
    )


def _create_sensor_publisher(
    adapter: IsaacAdapterBase,
    workflow_type: str,
    *,
    graph_path: str,
    sensor_prim_path: str,
    render_product_path: Optional[str],
    topic_name: str,
    frame_id: str,
    sensor_type: str,
    node_namespace: str,
    domain_id: Optional[int],
    qos_profile: str,
    use_system_time: bool,
    preview: bool,
) -> Dict[str, Any]:
    frame_error = _validate_frame(frame_id)
    if frame_error:
        return frame_error
    if not str(sensor_prim_path).startswith("/") or not _valid_prim(sensor_prim_path):
        return _error("ROS2_SENSOR_PRIM_NOT_FOUND", f"Sensor prim not found: {sensor_prim_path}")
    if render_product_path is None:
        cache_name = "_camera_sensors" if workflow_type == "camera" else "_lidar_sensors"
        sensor = (getattr(adapter, cache_name, None) or {}).get(sensor_prim_path)
        if sensor is None:
            return _error(
                "ROS2_SENSOR_RUNTIME_NOT_FOUND",
                f"No owned {workflow_type} runtime is cached for {sensor_prim_path}; create and warm the sensor first",
            )
        hydra_texture = getattr(sensor, "_hydra_texture", None)
        render_product_path = str(getattr(hydra_texture, "path", "")) or str(
            getattr(sensor, "_render_product_path", "") or ""
        )
    if not str(render_product_path).startswith("/") or not _valid_prim(render_product_path):
        return _error("ROS2_RENDER_PRODUCT_NOT_FOUND", f"Render product prim not found: {render_product_path}")
    type_key = "camera_type" if workflow_type == "camera" else "lidar_type"
    allowed = CAMERA_TYPES if workflow_type == "camera" else LIDAR_TYPES
    if sensor_type not in allowed:
        return _error("INVALID_ROS2_SENSOR_TYPE", f"{type_key} must be one of: {', '.join(sorted(allowed))}")
    return _run_or_return(
        _create_workflow(
            adapter,
            workflow_type,
            graph_path=graph_path,
            topic_name=topic_name,
            render_product_path=render_product_path,
            sensor_prim_path=sensor_prim_path,
            frame_id=frame_id,
            node_namespace=node_namespace,
            domain_id=domain_id,
            qos_profile=qos_profile,
            use_system_time=use_system_time,
            preview=bool(preview),
            **{type_key: sensor_type},
        )
    )


def create_camera_publisher(
    adapter: IsaacAdapterBase,
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
) -> Dict[str, Any]:
    return _create_sensor_publisher(
        adapter,
        "camera",
        graph_path=graph_path,
        sensor_prim_path=camera_prim_path,
        render_product_path=render_product_path,
        topic_name=topic_name,
        frame_id=frame_id,
        sensor_type=camera_type,
        node_namespace=node_namespace,
        domain_id=domain_id,
        qos_profile=qos_profile,
        use_system_time=use_system_time,
        preview=preview,
    )


def create_lidar_publisher(
    adapter: IsaacAdapterBase,
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
) -> Dict[str, Any]:
    return _create_sensor_publisher(
        adapter,
        "lidar",
        graph_path=graph_path,
        sensor_prim_path=lidar_prim_path,
        render_product_path=render_product_path,
        topic_name=topic_name,
        frame_id=frame_id,
        sensor_type=lidar_type,
        node_namespace=node_namespace,
        domain_id=domain_id,
        qos_profile=qos_profile,
        use_system_time=use_system_time,
        preview=preview,
    )


def delete_ros2_workflow(
    adapter: IsaacAdapterBase,
    graph_path: str,
    preview: bool = True,
) -> Dict[str, Any]:
    return _run_or_return(_delete_ros2_workflow(adapter, graph_path, preview=preview))


async def _delete_ros2_workflow(
    adapter: IsaacAdapterBase,
    graph_path: str,
    preview: bool = True,
) -> Dict[str, Any]:
    invalid = graphs._validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = graphs._require_stopped(adapter)
    if stopped:
        return stopped
    marker = _marker(graph_path)
    if marker is None:
        if graphs._graph_or_none(graph_path) is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        return _error("ROS2_WORKFLOW_NOT_OWNED", "Refusing to delete a graph without the MCP ROS 2 ownership marker")
    deleted = await _await_maybe(graphs.delete_action_graph(adapter, graph_path, preview=bool(preview)))
    if deleted.get("status") != "success":
        return deleted
    if preview:
        return _success(
            "ROS2_WORKFLOW_DELETE_PREVIEW",
            "ROS 2 workflow deletion preview validated",
            {"preview": True, "graph_path": graph_path, "ownership": marker},
        )
    return _success(
        "ROS2_WORKFLOW_DELETED",
        f"Deleted MCP-owned ROS 2 workflow {graph_path}",
        {"graph_path": graph_path, "workflow_type": marker["workflow_type"]},
        readback={"graph_present": False, "prim_present": False, "ownership_marker_present": False},
    )
