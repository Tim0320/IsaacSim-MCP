# MIT License
# Copyright (c) 2026 whats2000

"""Offline handler contracts for Task 17 ROS 2 workflows."""

from isaac_sim_mcp_extension.handlers import ros2


class _StoppedAdapter:
    def get_simulation_state(self):
        return {"timeline_state": "stopped", "playing": False}


def _enabled_states():
    return {name: {"state": "enabled", "enabled": True, "version": "test"} for name in ros2.REQUIRED_EXTENSIONS}


def test_disabled_bridge_returns_stable_prerequisite(monkeypatch):
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: None)
    monkeypatch.setattr(
        ros2,
        "_extension_states",
        lambda: {
            name: {"state": "disabled", "enabled": False, "version": None}
            for name in ros2.REQUIRED_EXTENSIONS
        },
    )

    result = ros2.create_clock_publisher(_StoppedAdapter(), preview=False)

    assert result["status"] == "unsupported"
    assert result["code"] == "ROS2_PREREQUISITE_MISSING"
    assert result["data"]["missing_extensions"] == list(ros2.REQUIRED_EXTENSIONS)


def test_clock_preview_is_non_mutating_and_explicit(monkeypatch):
    monkeypatch.setattr(ros2, "_extension_states", _enabled_states)
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: None)

    result = ros2.create_clock_publisher(_StoppedAdapter(), domain_id=17, preview=True)

    assert result["status"] == "success"
    assert result["code"] == "ROS2_WORKFLOW_PREVIEW"
    assert result["data"]["preview"] is True
    assert result["data"]["domain"] == {"source": "explicit", "domain_id": 17}
    assert result["data"]["active_on_play_only"] is True


def test_tf_spec_uses_isaac_sim_6_compute_transform_pipeline():
    spec = ros2._workflow_spec(
        "tf",
        topic_name="/tf",
        node_namespace="",
        domain_id=None,
        qos_profile="default",
        target_prims=["/World/Robot"],
        parent_prim="/World",
        static_publisher=False,
    )
    node_types = {node["type"] for node in spec["nodes"]}
    edges = {tuple(edge) for edge in spec["connections"]}

    assert "isaacsim.core.nodes.IsaacComputeTransformTree" in node_types
    assert "isaacsim.ros2.bridge.ROS2PublishTransformTree" in node_types
    assert ("ComputeTF.outputs:parentFrames", "Publisher.inputs:parentFrames") in edges
    assert ("ComputeTF.outputs:orientations", "Publisher.inputs:orientations") in edges
    assert ("QoSProfile.outputs:qosProfile", "Publisher.inputs:qosProfile") in edges


def test_joint_spec_uses_preferred_6_0_sensor_outputs():
    spec = ros2._workflow_spec(
        "joint_state",
        topic_name="/joint_states",
        node_namespace="",
        domain_id=None,
        qos_profile="default",
        target_prim="/World/Robot",
    )
    edges = {tuple(edge) for edge in spec["connections"]}

    assert ("ReadJointState.outputs:jointNames", "Publisher.inputs:jointNames") in edges
    assert ("ReadJointState.outputs:jointDofTypes", "Publisher.inputs:jointDofTypes") in edges
    assert ("ReadJointState.outputs:sensorTime", "Publisher.inputs:sensorTime") in edges


def test_sensor_specs_use_sensor_qos_and_exact_helpers():
    common = {
        "topic_name": "/sensor/data",
        "frame_id": "sensor_frame",
        "node_namespace": "",
        "domain_id": None,
        "qos_profile": "sensor_data",
        "render_product_path": "/Render/Product",
        "use_system_time": False,
    }
    camera = ros2._workflow_spec("camera", camera_type="rgb", **common)
    lidar = ros2._workflow_spec("lidar", lidar_type="point_cloud", **common)

    assert camera["nodes"][-1]["type"] == "isaacsim.ros2.bridge.ROS2CameraHelper"
    assert lidar["nodes"][-1]["type"] == "isaacsim.ros2.bridge.ROS2RtxLidarHelper"
    assert {tuple(edge) for edge in camera["connections"]} >= {
        ("QoSProfile.outputs:qosProfile", "Publisher.inputs:qosProfile")
    }


def test_input_contract_rejects_invalid_domain_topic_qos_and_frame(monkeypatch):
    monkeypatch.setattr(ros2, "_valid_prim", lambda _path: True)

    assert ros2.create_clock_publisher(_StoppedAdapter(), domain_id=233)["code"] == "INVALID_ROS2_DOMAIN_ID"
    assert ros2.create_clock_publisher(_StoppedAdapter(), topic_name="bad topic")["code"] == "INVALID_ROS2_TOPIC"
    assert ros2.create_clock_publisher(_StoppedAdapter(), qos_profile="magic")["code"] == "INVALID_ROS2_QOS_PROFILE"
    assert (
        ros2.create_camera_publisher(
            _StoppedAdapter(), "/World/G", "/World/Camera", "/Render/Product", frame_id="/absolute"
        )["code"]
        == "INVALID_ROS2_FRAME_ID"
    )


def test_apply_marks_ownership_and_reports_external_verification_boundary(monkeypatch):
    captured = {}
    monkeypatch.setattr(ros2, "_extension_states", _enabled_states)
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: None)

    def create(_adapter, **kwargs):
        captured.update(kwargs)
        return {"status": "success", "readback": {"node_count": len(kwargs["nodes"])}}

    monkeypatch.setattr(ros2.graphs, "create_action_graph", create)
    monkeypatch.setattr(
        ros2,
        "_set_marker",
        lambda graph_path, workflow_type, topic_name: {
            "schema_version": "1.0",
            "workflow_type": workflow_type,
            "topic_name": topic_name,
        },
    )

    result = ros2.create_clock_publisher(_StoppedAdapter(), preview=False)

    assert result["status"] == "success"
    assert result["code"] == "ROS2_WORKFLOW_CREATED"
    assert captured["evaluator"] == "execution"
    assert result["readback"]["ownership"]["workflow_type"] == "clock"
    assert result["readback"]["external_subscriber_verified"] is False


def test_camera_resolves_owned_runtime_render_product(monkeypatch):
    class _Texture:
        path = "/Render/CameraProduct"

    class _Sensor:
        _hydra_texture = _Texture()

    adapter = _StoppedAdapter()
    adapter._camera_sensors = {"/World/Camera": _Sensor()}
    monkeypatch.setattr(ros2, "_valid_prim", lambda _path: True)
    monkeypatch.setattr(ros2, "_extension_states", _enabled_states)
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: None)

    result = ros2.create_camera_publisher(adapter, "/World/CameraROS", "/World/Camera", preview=True)

    assert result["status"] == "success"
    assert result["data"]["workflow_type"] == "camera"


def test_sensor_without_owned_runtime_fails_closed(monkeypatch):
    adapter = _StoppedAdapter()
    adapter._lidar_sensors = {}
    monkeypatch.setattr(ros2, "_valid_prim", lambda _path: True)

    result = ros2.create_lidar_publisher(adapter, "/World/LidarROS", "/World/Lidar", preview=True)

    assert result["code"] == "ROS2_SENSOR_RUNTIME_NOT_FOUND"


def test_delete_refuses_foreign_graph(monkeypatch):
    monkeypatch.setattr(ros2, "_marker", lambda _path: None)
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: object())

    result = ros2.delete_ros2_workflow(_StoppedAdapter(), "/World/Foreign", preview=False)

    assert result["code"] == "ROS2_WORKFLOW_NOT_OWNED"
