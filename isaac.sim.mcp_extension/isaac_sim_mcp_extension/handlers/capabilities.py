# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Read-only runtime capability discovery."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .. import __version__
from ..adapters.base import IsaacAdapterBase
from ..adapters.version import version_string
from ..artifact_store import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_MAX_CHUNK_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    DEFAULT_TTL_SECONDS,
)
from .sensors import DEFAULT_INLINE_MAX_BYTES, MAX_INLINE_MAX_BYTES

CAPABILITIES_SCHEMA_VERSION = "1.1"
EXTENSION_ID = "isaac.sim.mcp_extension"

RELEVANT_EXTENSIONS = (
    EXTENSION_ID,
    "isaacsim.core.simulation_manager",
    "isaacsim.sensors.experimental.rtx",
    "omni.replicator.core",
    "isaacsim.replicator.agent.core",
    "isaacsim.ros2.bridge",
    "isaacsim.robot_motion.motion_generation",
    "isaacsim.robot.experimental.wheeled_robots",
    "isaacsim.physics.newton",
)


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    # The closure intentionally reads registry at call time. All handler modules
    # have been registered by then, so command_count and command_names describe
    # the live extension rather than a duplicated static list.
    registry["system.get_capabilities"] = lambda **_p: get_capabilities(adapter, registry)


def _extension_manager():
    import omni.kit.app

    return omni.kit.app.get_app().get_extension_manager()


def _as_python_dict(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "get_dict"):
        value = value.get_dict()
    return value if isinstance(value, Mapping) else {}


def _extension_states(manager=None) -> Dict[str, Dict[str, Any]]:
    if manager is None:
        try:
            manager = _extension_manager()
        except Exception:
            manager = None

    states: Dict[str, Dict[str, Any]] = {}
    for extension_name in RELEVANT_EXTENSIONS:
        if manager is None:
            states[extension_name] = {"state": "unknown", "enabled": None, "version": None}
            continue
        try:
            enabled = bool(manager.is_extension_enabled(extension_name))
            version = None
            if enabled:
                extension_id = manager.get_enabled_extension_id(extension_name)
                if extension_id:
                    extension_data = _as_python_dict(manager.get_extension_dict(extension_id))
                    package = _as_python_dict(extension_data.get("package", {}))
                    version = package.get("version")
            if extension_name == EXTENSION_ID and enabled and not version:
                version = __version__
            states[extension_name] = {
                "state": "enabled" if enabled else "disabled",
                "enabled": enabled,
                "version": version,
            }
        except Exception:
            states[extension_name] = {"state": "unknown", "enabled": None, "version": None}
    return states


def _runtime_info(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    adapter_name = type(adapter).__name__
    adapter_generation = 6 if "V6" in adapter_name else 5 if "V5" in adapter_name else None

    try:
        from isaacsim.core.version import get_version

        isaac_sim_version = version_string(get_version())
    except Exception:
        isaac_sim_version = str(getattr(adapter, "_isaacsim_version", "unknown"))

    physics_backend = "unknown"
    try:
        state = adapter.get_simulation_state()
        if isinstance(state, Mapping):
            physics_backend = str(state.get("engine") or physics_backend)
            isaac_sim_version = str(state.get("isaacsim_version") or isaac_sim_version)
    except Exception:
        state = {}
    if physics_backend == "unknown" and adapter_generation == 5:
        physics_backend = "physx"
    elif physics_backend == "unknown":
        try:
            physics_backend = str(getattr(adapter, "_engine"))
        except Exception:
            pass

    try:
        stage_available = adapter.get_stage() is not None
    except Exception:
        stage_available = None

    return {
        "isaac_sim_version": isaac_sim_version,
        "adapter": adapter_name,
        "adapter_generation": adapter_generation,
        "physics_backend": physics_backend,
        "stage_available": stage_available,
    }


def _backend_matrix(adapter: IsaacAdapterBase, active_backend: str) -> Dict[str, Any]:
    """Read the adapter-owned matrix without allowing discovery to fail."""
    try:
        matrix = adapter.get_backend_capability_matrix()
    except Exception:
        matrix = {}
    if not isinstance(matrix, Mapping):
        matrix = {}
    return {
        "schema_version": str(matrix.get("schema_version") or "1.0"),
        "active_backend": str(matrix.get("active_backend") or active_backend),
        "policy": dict(matrix.get("policy") or {}),
        "features": dict(matrix.get("features") or {}),
    }


def _backend_feature(
    matrix: Mapping[str, Any],
    feature: str,
    backend: str,
    *,
    fallback_state: str,
    fallback_verification: str,
) -> tuple[str, str]:
    record = matrix.get("features", {}).get(feature, {})
    backend_record = record.get("backends", {}).get(backend, {}) if isinstance(record, Mapping) else {}
    if not isinstance(backend_record, Mapping):
        return fallback_state, fallback_verification
    return (
        str(backend_record.get("state") or fallback_state),
        str(backend_record.get("verification") or fallback_verification),
    )


def _active_backend_flag(
    matrix: Mapping[str, Any], feature: str, backend: str, fallback_verification: str
) -> Dict[str, Any]:
    state, verification = _backend_feature(
        matrix,
        feature,
        backend,
        fallback_state="unknown",
        fallback_verification=fallback_verification,
    )
    return {"state": state, "backend": backend, "backend_verification": verification}


def _feature_flags(
    adapter_generation: Optional[int],
    physics_backend: str,
    backend_matrix: Mapping[str, Any],
    motion_generation_enabled: Optional[bool] = None,
    wheeled_robots_enabled: Optional[bool] = None,
) -> Dict[str, Dict[str, Any]]:
    lidar_config_state = "supported" if adapter_generation == 6 else "partial"
    fallback_verification = "verified" if physics_backend == "physx" else "unverified"
    camera_backend_state, _camera_verification = _backend_feature(
        backend_matrix,
        "sensor.camera",
        physics_backend,
        fallback_state="supported",
        fallback_verification=fallback_verification,
    )
    camera_v6_state = camera_backend_state if adapter_generation == 6 else "unsupported"
    lidar_backend_state, _lidar_verification = _backend_feature(
        backend_matrix,
        "sensor.lidar",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "partial",
        fallback_verification=fallback_verification,
    )
    sensor_lifecycle_state, _sensor_lifecycle_verification = _backend_feature(
        backend_matrix,
        "sensor.lifecycle",
        physics_backend,
        fallback_state="supported",
        fallback_verification=fallback_verification,
    )
    joint_v6_state, joint_verification = _backend_feature(
        backend_matrix,
        "robot.joint_command",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "unsupported",
        fallback_verification=fallback_verification,
    )
    joint_state_state, joint_state_verification = _backend_feature(
        backend_matrix,
        "robot.joint_state",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "partial",
        fallback_verification=fallback_verification,
    )
    drive_config_state, drive_verification = _backend_feature(
        backend_matrix,
        "robot.joint_drive_config",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "unsupported",
        fallback_verification=fallback_verification,
    )
    max_velocity_state, _ = _backend_feature(
        backend_matrix,
        "robot.joint_drive_config.max_velocity",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 and physics_backend == "physx" else "unsupported",
        fallback_verification=fallback_verification,
    )
    physics_time_state, physics_verification = _backend_feature(
        backend_matrix,
        "physics.time_step",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 and physics_backend == "physx" else "unsupported",
        fallback_verification=fallback_verification,
    )
    physics_gpu_state, _ = _backend_feature(
        backend_matrix,
        "physics.gpu_enabled",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 and physics_backend == "physx" else "unsupported",
        fallback_verification=fallback_verification,
    )
    physics_gravity_state, _ = _backend_feature(
        backend_matrix,
        "physics.gravity",
        physics_backend,
        fallback_state="supported",
        fallback_verification=fallback_verification,
    )
    motion_backend_state, motion_verification = _backend_feature(
        backend_matrix,
        "motion.ik_and_planning",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "unsupported",
        fallback_verification=fallback_verification,
    )
    gripper_backend_state, gripper_verification = _backend_feature(
        backend_matrix,
        "robot.gripper_profiles",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "unsupported",
        fallback_verification=fallback_verification,
    )
    mobile_backend_state, mobile_verification = _backend_feature(
        backend_matrix,
        "robot.mobile_base_profiles",
        physics_backend,
        fallback_state="supported" if adapter_generation == 6 else "unsupported",
        fallback_verification=fallback_verification,
    )
    if adapter_generation != 6:
        drive_field_state = "unsupported"
    else:
        drive_field_state = drive_config_state
    return {
        "scene.basic_crud": {"state": "supported"},
        "sensor.lifecycle": {
            "state": sensor_lifecycle_state,
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
        },
        "artifact.transport": {
            "state": "supported",
            "handle_scheme": "artifact://managed/<opaque-id>",
            "tools": ["get_artifact_info", "read_artifact", "delete_artifact", "cleanup_artifacts"],
            "ttl_default_seconds": DEFAULT_TTL_SECONDS,
            "max_chunk_default_bytes": DEFAULT_MAX_CHUNK_BYTES,
            "max_artifact_default_bytes": DEFAULT_MAX_ARTIFACT_BYTES,
            "max_total_default_bytes": DEFAULT_MAX_TOTAL_BYTES,
        },
        "camera.rgb_file": {
            "state": camera_backend_state,
            "warmup_required": True,
        },
        "camera.rgb_pixels": {
            "state": camera_backend_state,
            "return_modes": ["metadata", "artifact", "inline"],
            "default_return_mode": "artifact",
            "inline_default_max_bytes": DEFAULT_INLINE_MAX_BYTES,
            "inline_hard_max_bytes": MAX_INLINE_MAX_BYTES,
            "warmup_required": True,
        },
        "camera.annotators": {
            "state": camera_v6_state,
            "adapter_generation": adapter_generation,
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
        },
        "camera.calibration": {
            "state": camera_v6_state,
            "adapter_generation": adapter_generation,
        },
        "lidar.point_cloud": {
            "state": lidar_backend_state,
            "adapter_generation": adapter_generation,
            "required_fields": ["points", "range", "azimuth", "elevation"],
            "optional_fields": ["intensity", "object_id", "semantic_id"],
            "return_modes": ["metadata", "artifact", "inline"],
            "artifact_format": "npz",
            "warmup_required": True,
        },
        "lidar.config": {
            "state": lidar_backend_state if adapter_generation == 6 else lidar_config_state,
            "adapter_generation": adapter_generation,
            "preset_configs": True,
            "generic_schema_config": adapter_generation == 6,
            "readback": adapter_generation == 6,
            "generic_fields": [
                "horizontal_fov_deg",
                "vertical_fov_deg",
                "horizontal_resolution_deg",
                "vertical_resolution_deg",
                "rotation_rate_hz",
                "min_range_m",
                "max_range_m",
            ],
            "reason": None if adapter_generation == 6 else "Isaac Sim 5.x supports named presets only",
        },
        "simulation.timeline": _active_backend_flag(
            backend_matrix, "simulation.timeline", physics_backend, fallback_verification
        ),
        "simulation.step": _active_backend_flag(
            backend_matrix, "simulation.step", physics_backend, fallback_verification
        ),
        "simulation.reset": _active_backend_flag(
            backend_matrix, "simulation.reset", physics_backend, fallback_verification
        ),
        "physics.state": _active_backend_flag(backend_matrix, "physics.state", physics_backend, fallback_verification),
        "physics.gravity": {
            "state": physics_gravity_state,
            "tool": "set_physics_params",
            "readback": True,
        },
        "physics.time_step": {
            "state": physics_time_state,
            "tool": "set_physics_params",
            "adapter_generation": adapter_generation,
            "backend": physics_backend,
            "requires_stopped_timeline": True,
            "range_seconds": [0.0001, 1.0],
            "integer_steps_per_second_required": True,
            "synchronizes_stage_time_codes": True,
            "synchronizes_min_frame_rate": True,
            "usd_and_runtime_readback": physics_time_state == "supported",
        },
        "physics.gpu_enabled": {
            "state": physics_gpu_state,
            "tool": "set_physics_params",
            "adapter_generation": adapter_generation,
            "backend": physics_backend,
            "requires_stopped_timeline": True,
            "true_broadphase": "GPU",
            "false_broadphase": "MBP",
            "changes_physics_gpu_ordinal": False,
            "usd_and_runtime_readback": physics_gpu_state == "supported",
        },
        "physics.body_authoring": {
            **_active_backend_flag(
                backend_matrix, "physics.body_authoring", physics_backend, fallback_verification
            ),
            "tools": ["configure_physics_body", "get_physics_body"],
            "requires_stopped_timeline": True,
            "body_types": ["dynamic", "kinematic", "static"],
            "mass_unit": "kg",
            "density_unit": "kg/m^3",
            "atomic": True,
        },
        "physics.collision_groups": {
            **_active_backend_flag(
                backend_matrix, "physics.collision_groups", physics_backend, fallback_verification
            ),
            "tools": ["create_collision_group", "get_collision_group"],
            "requires_stopped_timeline": True,
            "readback": True,
        },
        "physics.joint_authoring": {
            **_active_backend_flag(
                backend_matrix, "physics.joint_authoring", physics_backend, fallback_verification
            ),
            "tools": ["create_physics_joint", "get_physics_joint"],
            "requires_stopped_timeline": True,
            "joint_types": ["fixed", "revolute", "prismatic"],
            "axes": ["X", "Y", "Z"],
            "position_unit": "m",
            "revolute_limit_unit": "degrees",
            "prismatic_limit_unit": "m",
        },
        "physics.backend_verification": {
            "state": physics_verification,
            "backend": physics_backend,
        },
        "robot.joint_position": {
            "state": joint_v6_state if adapter_generation == 6 else "supported",
            "adapter_generation": adapter_generation,
        },
        "robot.joint_velocity": {"state": joint_v6_state, "adapter_generation": adapter_generation},
        "robot.joint_effort": {
            "state": joint_v6_state,
            "adapter_generation": adapter_generation,
            "renew_each_update": True,
        },
        "robot.joint_state": {
            "state": joint_state_state,
            "adapter_generation": adapter_generation,
            "backend_verification": joint_state_verification,
            "tool": "get_joint_state",
            "measured_fields": ["position", "velocity", "effort"],
            "target_fields": ["position", "velocity", "effort"],
            "subset_selectors": ["joint_names", "joint_indices"],
        },
        "robot.joint_command": {
            "state": joint_v6_state,
            "adapter_generation": adapter_generation,
            "backend_verification": joint_verification,
            "tool": "set_joint_command",
            "modes": ["position", "velocity", "effort"],
            "atomic_validation": True,
            "readback": True,
        },
        "robot.joint_drive_config": {
            "state": drive_config_state,
            "adapter_generation": adapter_generation,
            "backend": physics_backend,
            "backend_verification": drive_verification,
            "tool": "set_joint_drive_config",
            "read_tool": "get_joint_config",
            "fields": {
                "stiffness": drive_field_state,
                "damping": drive_field_state,
                "max_force": drive_field_state,
                "max_velocity": max_velocity_state,
                "drive_type": drive_field_state,
            },
            "drive_types": ["force", "acceleration"],
            "subset_selectors": ["joint_names", "joint_indices"],
            "requires_stopped_timeline": True,
            "atomic_validation": True,
            "rollback_on_apply_error": True,
            "readback": True,
        },
        "motion.ik_and_planning": {
            "state": (
                motion_backend_state
                if motion_backend_state != "supported"
                else "supported"
                if motion_generation_enabled is True
                else "unavailable"
                if motion_generation_enabled is False
                else "unknown"
            ),
            "backend_verification": motion_verification,
            "adapter_generation": adapter_generation,
            "required_extension": "isaacsim.robot_motion.motion_generation",
            "tools": [
                "compute_ik",
                "plan_joint_trajectory",
                "execute_trajectory",
                "cancel_motion",
                "get_motion_status",
            ],
            "planners": ["rrt", "cspace"],
            "non_blocking_execution": True,
            "bounded_iterations": True,
            "deterministic_seed": True,
            "ik_collision_check": False,
        },
        "robot.gripper_profiles": {
            "state": gripper_backend_state,
            "backend_verification": gripper_verification,
            "profiles": ["franka_parallel_gripper"],
            "tools": ["set_gripper_width", "open_gripper", "close_gripper"],
            "explicit_profile_required": True,
            "signature_validation": True,
        },
        "robot.mobile_base_profiles": {
            "state": mobile_backend_state,
            "backend_verification": mobile_verification,
            "profiles": ["nvidia_jetbot_differential", "nvidia_kaya_holonomic"],
            "profile_states": {
                "nvidia_jetbot_differential": mobile_backend_state,
                "nvidia_kaya_holonomic": (
                    mobile_backend_state
                    if mobile_backend_state != "supported"
                    else "supported"
                    if wheeled_robots_enabled is True
                    else "unavailable"
                    if wheeled_robots_enabled is False
                    else "unknown"
                ),
            },
            "profile_requirements": {"nvidia_kaya_holonomic": "isaacsim.robot.experimental.wheeled_robots"},
            "tools": ["set_mobile_base_velocity", "stop_mobile_base"],
            "explicit_profile_required": True,
            "signature_validation": True,
            "nonzero_command_requires_playing_timeline": True,
            "stop_readback": True,
        },
        "omnigraph.create_edit": {"state": "partial"},
        "omnigraph.lifecycle": {"state": "unsupported"},
        "ros2.named_tools": {"state": "unsupported"},
        "replicator.sdg_workflows": {"state": "unsupported"},
        "human.spawn": {"state": "supported"},
        "human.lifecycle": {"state": "partial"},
        "execute_script": {"state": "supported", "risk": "high"},
    }


def _unsupported_arguments(
    adapter_generation: Optional[int], physics_backend: str
) -> Dict[str, Dict[str, Dict[str, str]]]:
    result: Dict[str, Dict[str, Dict[str, str]]] = {}
    if adapter_generation != 6 or physics_backend != "physx":
        result["set_physics_params"] = {
            "time_step": {
                "state": "unsupported",
                "reason": "Requires the Isaac Sim 6.x PhysX scene adapter",
            },
            "gpu_enabled": {
                "state": "unsupported",
                "reason": "Requires the Isaac Sim 6.x PhysX scene adapter",
            },
        }
    if adapter_generation == 5:
        result["create_lidar"] = {
            name: {"state": "unsupported", "reason": "Generic schema configuration requires Isaac Sim 6.x"}
            for name in (
                "variant",
                "horizontal_fov_deg",
                "vertical_fov_deg",
                "horizontal_resolution_deg",
                "vertical_resolution_deg",
                "rotation_rate_hz",
                "min_range_m",
                "max_range_m",
            )
        }
    return result


def _sensor_warmup(adapter: IsaacAdapterBase) -> Dict[str, Dict[str, Any]]:
    camera_count = len(getattr(adapter, "_camera_sensors", {}) or {})
    lidar_count = len(getattr(adapter, "_lidar_sensors", {}) or {})
    return {
        "camera": {
            "required": True,
            "state": "not_created" if camera_count == 0 else "per_sensor_unknown",
            "cached_sensor_count": camera_count,
            "requirement": "render frames must be produced before capture",
        },
        "lidar": {
            "required": True,
            "state": "not_created" if lidar_count == 0 else "per_sensor_unknown",
            "cached_sensor_count": lidar_count,
            "requirement": "timeline play and multiple frames are required before point data is available",
        },
    }


def get_capabilities(
    adapter: IsaacAdapterBase,
    registry: Mapping[str, Any],
    *,
    extension_manager=None,
) -> Dict[str, Any]:
    """Return a side-effect-free, machine-readable capability snapshot."""
    runtime = _runtime_info(adapter)
    commands = sorted(registry)
    extensions = _extension_states(extension_manager)
    motion_enabled = extensions["isaacsim.robot_motion.motion_generation"]["enabled"]
    wheeled_enabled = extensions["isaacsim.robot.experimental.wheeled_robots"]["enabled"]
    backend_matrix = _backend_matrix(adapter, runtime["physics_backend"])
    return {
        "status": "success",
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "capability_schema_version": CAPABILITIES_SCHEMA_VERSION,
        "runtime": runtime,
        "extension": {
            "id": EXTENSION_ID,
            "version": __version__,
            "command_count": len(commands),
            "command_names": commands,
        },
        "extensions": extensions,
        "backend_matrix": backend_matrix,
        "feature_flags": _feature_flags(
            runtime["adapter_generation"],
            runtime["physics_backend"],
            backend_matrix,
            motion_enabled,
            wheeled_enabled,
        ),
        "unsupported_arguments": _unsupported_arguments(runtime["adapter_generation"], runtime["physics_backend"]),
        "sensor_warmup": _sensor_warmup(adapter),
    }
