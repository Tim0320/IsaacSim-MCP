"""Capability contract tests for the MCP server and Isaac extension."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomllib
from isaac_sim_mcp_extension import __version__ as extension_version
from isaac_sim_mcp_extension.adapters.base import IsaacAdapterBase
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.handlers.capabilities import get_capabilities

from isaac_mcp import __version__ as server_version
from isaac_mcp.tools.capabilities import register_tools


class _AdapterV6:
    _backend_capability = staticmethod(IsaacAdapterBase._backend_capability)

    def __init__(self) -> None:
        self._camera_sensors = {"/World/Camera": object()}
        self._lidar_sensors = {}

    def get_simulation_state(self):
        return {"engine": "physx", "isaacsim_version": "6.0.1-rc.7"}

    def get_stage(self):
        return None

    @property
    def _engine(self):
        return self.get_simulation_state()["engine"]

    def get_backend_capability_matrix(self):
        return IsaacAdapterV6.get_backend_capability_matrix(self)


class _ExtensionManager:
    enabled = {
        "isaac.sim.mcp_extension",
        "isaacsim.core.simulation_manager",
        "omni.graph.core",
        "omni.graph.action",
        "omni.graph.scriptnode",
        "isaacsim.replicator.agent.core",
        "omni.anim.behavior.core",
        "omni.anim.navigation.core",
    }

    def is_extension_enabled(self, name):
        return name in self.enabled

    def get_enabled_extension_id(self, name):
        return f"{name}-0.6.0" if name in self.enabled else ""

    def get_extension_dict(self, _extension_id):
        return {"package": {"version": "0.6.0"}}


def test_handler_returns_stable_runtime_capability_contract():
    registry = {"system.get_capabilities": object(), "scene.get_info": object()}

    result = get_capabilities(_AdapterV6(), registry, extension_manager=_ExtensionManager())

    assert result["status"] == "success"
    assert result["schema_version"] == "1.1"
    assert result["capability_schema_version"] == "1.1"
    assert result["runtime"] == {
        "isaac_sim_version": "6.0.1-rc.7",
        "adapter": "_AdapterV6",
        "adapter_generation": 6,
        "physics_backend": "physx",
        "stage_available": False,
    }
    assert result["extension"]["command_count"] == 2
    assert result["extension"]["command_names"] == ["scene.get_info", "system.get_capabilities"]
    assert result["extensions"]["isaac.sim.mcp_extension"]["state"] == "enabled"
    assert result["extensions"]["isaacsim.ros2.bridge"]["state"] == "disabled"
    assert result["extensions"]["isaacsim.ros2.core"]["state"] == "disabled"
    assert result["extensions"]["isaacsim.ros2.nodes"]["state"] == "disabled"
    matrix = result["backend_matrix"]
    assert matrix["schema_version"] == "1.0"
    assert matrix["active_backend"] == "physx"
    assert len(matrix["features"]) == 21
    assert matrix["policy"]["supported_requires_live_verification"] is True
    assert all(record["physx_supported"] is True for record in matrix["features"].values())
    assert all(record["backends"]["physx"]["verification"] == "verified" for record in matrix["features"].values())
    assert matrix["features"]["sensor.camera"]["newton_supported"] is None
    assert matrix["features"]["sensor.camera"]["untested"] == ["newton"]
    assert matrix["features"]["physics.time_step"]["newton_supported"] is False
    assert matrix["features"]["physics.time_step"]["backends"]["newton"]["state"] == "unsupported"
    assert matrix["features"]["physics.body_authoring"]["newton_supported"] is None
    assert matrix["features"]["physics.materials"]["newton_supported"] is None
    assert result["feature_flags"]["physics.body_authoring"]["tools"] == [
        "configure_physics_body",
        "get_physics_body",
    ]
    assert result["feature_flags"]["physics.joint_authoring"]["revolute_limit_unit"] == "degrees"
    assert result["feature_flags"]["physics.materials"]["physics_binding_purpose"] == "physics"
    assert result["feature_flags"]["stage.composition"] == {
        "state": "supported",
        "tools": [
            "new_stage",
            "open_stage",
            "save_stage_as",
            "get_stage_composition",
            "edit_sublayer",
            "edit_composition_arc",
            "set_variant_selection",
            "get_semantic_labels",
            "set_semantic_labels",
            "get_typed_attribute",
            "set_typed_attribute",
            "apply_stage_batch",
        ],
        "requires_stopped_timeline": True,
        "scratch_guarded_lifecycle": True,
        "preview_default": True,
        "source_overwrite_default": False,
        "atomic_batch_rollback": True,
    }
    assert result["feature_flags"]["omnigraph.lifecycle"] == {
        "state": "supported",
        "tools": [
            "create_action_graph",
            "edit_action_graph",
            "list_action_graphs",
            "get_action_graph",
            "delete_action_graph",
            "connect_action_graph",
            "disconnect_action_graph",
            "set_action_graph_enabled",
            "get_action_graph_status",
            "configure_script_node",
            "reload_script_node",
            "evaluate_action_graph",
        ],
        "required_extensions": ["omni.graph.core", "omni.graph.action", "omni.graph.scriptnode"],
        "query_readback": True,
        "preview_default_for_new_writes": True,
        "operation_specific_rollback": True,
        "enabled_state_runtime_only": True,
        "script_modes": ["inline", "file"],
        "graph_scoped_script_reload": True,
        "runtime_error_messages": True,
    }
    assert result["feature_flags"]["human.lifecycle"] == {
        "state": "supported",
        "tools": [
            "spawn_human",
            "list_humans",
            "get_human",
            "delete_human",
            "set_human_target",
            "set_human_look_at",
            "set_human_idle",
            "set_human_behavior",
            "get_navmesh_status",
            "bake_navmesh",
        ],
        "required_extensions": [
            "isaacsim.replicator.agent.core",
            "omni.anim.behavior.core",
            "omni.anim.navigation.core",
        ],
        "preview_default_for_writes": True,
        "ownership_guarded_control_and_delete": True,
        "task_commands_require_playing_timeline": True,
        "bake_and_delete_require_stopped_timeline": True,
        "runtime_task_api": "IBehaviorAgent",
    }
    assert result["feature_flags"]["ros2.named_tools"] == {
        "state": "unavailable",
        "tools": [
            "get_ros2_status",
            "list_ros2_workflows",
            "create_ros2_clock_publisher",
            "create_ros2_tf_publisher",
            "create_ros2_joint_state_publisher",
            "create_ros2_camera_publisher",
            "create_ros2_lidar_publisher",
            "delete_ros2_workflow",
        ],
        "required_extensions": ["isaacsim.ros2.bridge", "isaacsim.ros2.core", "isaacsim.ros2.nodes"],
        "qos_profiles": ["default", "sensor_data", "system_default", "services"],
        "requires_stopped_timeline_for_writes": True,
        "preview_default": True,
        "publishers_active_on_play_only": True,
        "ownership_guarded_delete": True,
        "external_subscriber_verification_required": True,
    }
    assert result["feature_flags"]["replicator.sdg_workflows"] == {
        "state": "unavailable",
        "tools": [
            "get_replicator_status",
            "create_sdg_job",
            "start_sdg_job",
            "get_sdg_job_status",
            "cancel_sdg_job",
            "get_sdg_manifest",
            "delete_sdg_job",
        ],
        "required_extensions": ["omni.replicator.core"],
        "writer": "BasicWriter",
        "trigger_modes": ["manual"],
        "randomizer_types": ["transform", "light"],
        "fixed_seed": True,
        "managed_artifacts": True,
        "preview_default": True,
        "single_active_job": True,
        "cleanup_readback": True,
    }
    assert result["feature_flags"]["sensor.lifecycle"] == {
        "state": "supported",
        "delete_tool": "delete_sensor",
        "requires_non_playing_timeline": True,
        "post_delete_updates_default": 8,
        "post_delete_updates_max": 240,
        "verifies": [
            "prim_absent",
            "actual_prim_absent",
            "render_product_absent",
            "adapter_cache_absent",
            "lidar_metadata_absent",
        ],
    }
    assert result["feature_flags"]["artifact.transport"] == {
        "state": "supported",
        "handle_scheme": "artifact://managed/<opaque-id>",
        "tools": ["get_artifact_info", "read_artifact", "delete_artifact", "cleanup_artifacts"],
        "ttl_default_seconds": 3600,
        "max_chunk_default_bytes": 1048576,
        "max_artifact_default_bytes": 268435456,
        "max_total_default_bytes": 536870912,
    }
    assert result["feature_flags"]["camera.rgb_pixels"] == {
        "state": "supported",
        "return_modes": ["metadata", "artifact", "inline"],
        "default_return_mode": "artifact",
        "inline_default_max_bytes": 1048576,
        "inline_hard_max_bytes": 4194304,
        "warmup_required": True,
    }
    assert result["feature_flags"]["camera.annotators"] == {
        "state": "supported",
        "adapter_generation": 6,
        "outputs": [
            "depth",
            "distance_to_image_plane",
            "semantic_segmentation",
            "instance_segmentation",
            "instance_id_segmentation",
            "normals",
            "motion_vectors",
        ],
        "return_modes": ["metadata", "artifact", "inline"],
        "artifact_format": "npy",
        "warmup_required": True,
    }
    assert result["feature_flags"]["camera.calibration"] == {
        "state": "supported",
        "adapter_generation": 6,
    }
    assert result["feature_flags"]["lidar.point_cloud"] == {
        "state": "supported",
        "adapter_generation": 6,
        "required_fields": ["points", "range", "azimuth", "elevation"],
        "optional_fields": ["intensity", "object_id", "semantic_id"],
        "return_modes": ["metadata", "artifact", "inline"],
        "artifact_format": "npz",
        "warmup_required": True,
    }
    assert result["feature_flags"]["lidar.config"] == {
        "state": "supported",
        "adapter_generation": 6,
        "preset_configs": True,
        "generic_schema_config": True,
        "readback": True,
        "generic_fields": [
            "horizontal_fov_deg",
            "vertical_fov_deg",
            "horizontal_resolution_deg",
            "vertical_resolution_deg",
            "rotation_rate_hz",
            "min_range_m",
            "max_range_m",
        ],
        "reason": None,
    }
    assert result["feature_flags"]["robot.joint_state"] == {
        "state": "supported",
        "adapter_generation": 6,
        "backend_verification": "verified",
        "tool": "get_joint_state",
        "measured_fields": ["position", "velocity", "effort"],
        "target_fields": ["position", "velocity", "effort"],
        "subset_selectors": ["joint_names", "joint_indices"],
    }
    assert result["feature_flags"]["robot.joint_command"] == {
        "state": "supported",
        "adapter_generation": 6,
        "backend_verification": "verified",
        "tool": "set_joint_command",
        "modes": ["position", "velocity", "effort"],
        "atomic_validation": True,
        "readback": True,
    }
    assert result["feature_flags"]["robot.joint_drive_config"] == {
        "state": "supported",
        "adapter_generation": 6,
        "backend": "physx",
        "backend_verification": "verified",
        "tool": "set_joint_drive_config",
        "read_tool": "get_joint_config",
        "fields": {
            "stiffness": "supported",
            "damping": "supported",
            "max_force": "supported",
            "max_velocity": "supported",
            "drive_type": "supported",
        },
        "drive_types": ["force", "acceleration"],
        "subset_selectors": ["joint_names", "joint_indices"],
        "requires_stopped_timeline": True,
        "atomic_validation": True,
        "rollback_on_apply_error": True,
        "readback": True,
    }
    assert result["feature_flags"]["robot.joint_effort"]["renew_each_update"] is True
    assert "create_lidar" not in result["unsupported_arguments"]
    assert result["feature_flags"]["physics.gravity"] == {
        "state": "supported",
        "tool": "set_physics_params",
        "readback": True,
    }
    assert result["feature_flags"]["physics.time_step"] == {
        "state": "supported",
        "tool": "set_physics_params",
        "adapter_generation": 6,
        "backend": "physx",
        "requires_stopped_timeline": True,
        "range_seconds": [0.0001, 1.0],
        "integer_steps_per_second_required": True,
        "synchronizes_stage_time_codes": True,
        "synchronizes_min_frame_rate": True,
        "usd_and_runtime_readback": True,
    }
    assert result["feature_flags"]["physics.gpu_enabled"]["state"] == "supported"
    assert result["feature_flags"]["physics.gpu_enabled"]["changes_physics_gpu_ordinal"] is False
    assert "set_physics_params" not in result["unsupported_arguments"]
    assert result["sensor_warmup"]["camera"]["state"] == "per_sensor_unknown"
    assert result["sensor_warmup"]["lidar"]["state"] == "not_created"


def test_extension_manager_failure_is_reported_as_unknown_without_failing_query():
    class _UnavailableManager:
        def is_extension_enabled(self, _name):
            raise RuntimeError("not ready")

    result = get_capabilities(_AdapterV6(), {}, extension_manager=_UnavailableManager())

    assert result["status"] == "success"
    assert all(item == {"state": "unknown", "enabled": None, "version": None} for item in result["extensions"].values())


def test_v5_reports_physx_and_supported_lidar_config():
    class _AdapterV5:
        _camera_sensors = {}
        _lidar_sensors = {}

        def get_simulation_state(self):
            return {}

        def get_stage(self):
            return object()

    result = get_capabilities(_AdapterV5(), {}, extension_manager=_ExtensionManager())

    assert result["runtime"]["adapter_generation"] == 5
    assert result["runtime"]["physics_backend"] == "physx"
    assert result["feature_flags"]["lidar.config"]["state"] == "partial"
    assert result["feature_flags"]["lidar.config"]["preset_configs"] is True
    assert result["feature_flags"]["lidar.config"]["generic_schema_config"] is False
    assert result["feature_flags"]["robot.joint_state"]["state"] == "partial"
    assert result["feature_flags"]["robot.joint_command"]["state"] == "unsupported"
    assert result["feature_flags"]["robot.joint_drive_config"]["state"] == "unsupported"
    assert result["feature_flags"]["physics.time_step"]["state"] == "unsupported"
    assert result["unsupported_arguments"]["set_physics_params"]["gpu_enabled"]["state"] == "unsupported"
    assert result["unsupported_arguments"]["create_lidar"]["horizontal_fov_deg"]["state"] == "unsupported"


def test_newton_reports_physx_only_fields_and_keeps_unverified_paths_untested():
    class _AdapterV6Newton(_AdapterV6):
        def get_simulation_state(self):
            return {"engine": "newton", "isaacsim_version": "6.0.1-rc.7"}

    result = get_capabilities(_AdapterV6Newton(), {}, extension_manager=_ExtensionManager())
    feature = result["feature_flags"]["robot.joint_drive_config"]

    assert result["feature_flags"]["physics.time_step"]["state"] == "unsupported"
    assert result["feature_flags"]["physics.gpu_enabled"]["state"] == "unsupported"
    assert result["unsupported_arguments"]["set_physics_params"]["time_step"]["state"] == "unsupported"

    assert result["backend_matrix"]["active_backend"] == "newton"
    assert feature["state"] == "untested"
    assert feature["backend"] == "newton"
    assert feature["backend_verification"] == "untested"
    assert feature["fields"] == {
        "stiffness": "untested",
        "damping": "untested",
        "max_force": "untested",
        "max_velocity": "unsupported",
        "drive_type": "untested",
    }
    assert result["feature_flags"]["camera.rgb_pixels"]["state"] == "untested"
    assert result["feature_flags"]["lidar.point_cloud"]["state"] == "untested"
    assert result["feature_flags"]["robot.joint_position"]["state"] == "untested"
    assert result["feature_flags"]["robot.joint_command"]["state"] == "untested"
    assert all(record["newton_supported"] is not True for record in result["backend_matrix"]["features"].values())


def test_adapter_backend_guard_allows_verified_physx_and_rejects_newton_states():
    physx = _AdapterV6()
    accepted = IsaacAdapterBase.require_backend_capability(physx, "physics.time_step")
    assert accepted["state"] == "supported"
    assert accepted["verification"] == "verified"

    class _Newton(_AdapterV6):
        def get_simulation_state(self):
            return {"engine": "newton", "isaacsim_version": "6.0.1-rc.7"}

    newton = _Newton()
    with pytest.raises(NotImplementedError, match="physics.time_step.*unsupported.*newton"):
        IsaacAdapterBase.require_backend_capability(newton, "physics.time_step")
    with pytest.raises(NotImplementedError, match="sensor.camera.*untested.*newton"):
        IsaacAdapterBase.require_backend_capability(newton, "sensor.camera")


def test_tool_adds_mcp_server_metadata_and_uses_system_command():
    class _MCP:
        def __init__(self):
            self.tools = {}

        def tool(self, name):
            def decorator(function):
                self.tools[name] = function
                return function

            return decorator

    class _Connection:
        port = 8766

        def __init__(self):
            self.commands = []

        def send_command(self, command):
            self.commands.append(command)
            return {"status": "success", "schema_version": "1.0"}

    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    result = json.loads(mcp.tools["get_capabilities"]())

    assert connection.commands == ["system.get_capabilities"]
    assert result["data"]["mcp_server"] == {
        "name": "isaacsim-mcp-server",
        "version": server_version,
        "transport": "stdio_to_tcp",
        "live_control_port": 8766,
    }


def test_server_extension_and_manifest_versions_match():
    root = Path(__file__).parents[1]
    manifest = tomllib.loads(
        (root / "isaac.sim.mcp_extension" / "config" / "extension.toml").read_text(encoding="utf-8")
    )

    assert server_version == extension_version == manifest["package"]["version"]
