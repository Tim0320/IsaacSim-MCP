# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Read-only runtime capability discovery."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .. import __version__
from ..adapters.base import IsaacAdapterBase
from ..adapters.version import version_string

CAPABILITIES_SCHEMA_VERSION = "1.0"
EXTENSION_ID = "isaac.sim.mcp_extension"

RELEVANT_EXTENSIONS = (
    EXTENSION_ID,
    "isaacsim.core.simulation_manager",
    "isaacsim.sensors.experimental.rtx",
    "omni.replicator.core",
    "isaacsim.replicator.agent.core",
    "isaacsim.ros2.bridge",
    "isaacsim.robot_motion.motion_generation",
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


def _feature_flags(adapter_generation: Optional[int], physics_backend: str) -> Dict[str, Dict[str, Any]]:
    lidar_config_state = "supported" if adapter_generation == 5 else "accepted_not_applied"
    backend_verification = "verified" if physics_backend == "physx" else "unverified"
    return {
        "scene.basic_crud": {"state": "supported"},
        "camera.rgb_file": {"state": "supported", "warmup_required": True},
        "camera.rgb_pixels": {
            "state": "unsupported",
            "reason": "capture_image returns a file or shape metadata, not RGB pixel payloads",
        },
        "camera.annotators": {"state": "unsupported"},
        "lidar.point_count": {"state": "supported", "warmup_required": True},
        "lidar.point_cloud_data": {
            "state": "unsupported",
            "reason": "the handler discards decoded points and returns point_count only",
        },
        "lidar.config": {
            "state": lidar_config_state,
            "reason": (
                "Isaac Sim 6.x requires schema attribute authoring after Lidar creation"
                if adapter_generation == 6
                else None
            ),
        },
        "physics.gravity": {"state": "supported"},
        "physics.time_step": {"state": "unsupported"},
        "physics.gpu_enabled": {"state": "unsupported"},
        "physics.backend_verification": {
            "state": backend_verification,
            "backend": physics_backend,
        },
        "robot.joint_position": {"state": "supported"},
        "robot.joint_velocity": {"state": "unsupported"},
        "robot.joint_effort": {"state": "unsupported"},
        "motion.ik_and_planning": {"state": "unsupported"},
        "omnigraph.create_edit": {"state": "partial"},
        "omnigraph.lifecycle": {"state": "unsupported"},
        "ros2.named_tools": {"state": "unsupported"},
        "replicator.sdg_workflows": {"state": "unsupported"},
        "human.spawn": {"state": "supported"},
        "human.lifecycle": {"state": "partial"},
        "execute_script": {"state": "supported", "risk": "high"},
    }


def _unsupported_arguments(adapter_generation: Optional[int]) -> Dict[str, Dict[str, Dict[str, str]]]:
    result = {
        "set_physics_params": {
            "time_step": {
                "state": "unsupported",
                "reason": "accepted by the MCP schema but rejected by the extension handler",
            },
            "gpu_enabled": {
                "state": "unsupported",
                "reason": "accepted by the MCP schema but rejected by the extension handler",
            },
        }
    }
    if adapter_generation == 6:
        result["create_lidar"] = {
            "config": {
                "state": "accepted_not_applied",
                "reason": "Isaac Sim 6.x Lidar presets require schema attribute authoring",
            }
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
    return {
        "status": "success",
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "runtime": runtime,
        "extension": {
            "id": EXTENSION_ID,
            "version": __version__,
            "command_count": len(commands),
            "command_names": commands,
        },
        "extensions": _extension_states(extension_manager),
        "feature_flags": _feature_flags(runtime["adapter_generation"], runtime["physics_backend"]),
        "unsupported_arguments": _unsupported_arguments(runtime["adapter_generation"]),
        "sensor_warmup": _sensor_warmup(adapter),
    }
