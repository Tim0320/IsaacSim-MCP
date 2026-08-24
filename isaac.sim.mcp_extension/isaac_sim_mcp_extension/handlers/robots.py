# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Robot creation and control command handlers."""

from __future__ import annotations

import math
import traceback
from typing import Any, Dict, List, Optional, Sequence

from ..adapters.base import IsaacAdapterBase, JointDriveConfigApplyError

# Hardcoded fallback — used only if live discovery fails.
# Keys are lowercase robot names, asset_path is relative to the assets root.
FALLBACK_ROBOT_LIBRARY: Dict[str, Dict[str, str]] = {
    "frankapanda": {
        "asset_path": "/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd",
        "description": "FrankaRobotics FrankaPanda",
        "manufacturer": "FrankaRobotics",
    },
    "jetbot": {
        "asset_path": "/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd",
        "description": "NVIDIA Jetbot",
        "manufacturer": "NVIDIA",
    },
    "carter_v1": {
        "asset_path": "/Isaac/Robots/NVIDIA/Carter/carter_v1.usd",
        "description": "NVIDIA Carter",
        "manufacturer": "NVIDIA",
    },
    "novacarter": {
        "asset_path": "/Isaac/Robots/NVIDIA/NovaCarter/nova_carter.usd",
        "description": "NVIDIA NovaCarter",
        "manufacturer": "NVIDIA",
    },
    "g1": {"asset_path": "/Isaac/Robots/Unitree/G1/g1.usd", "description": "Unitree G1", "manufacturer": "Unitree"},
    "go1": {"asset_path": "/Isaac/Robots/Unitree/Go1/go1.usd", "description": "Unitree Go1", "manufacturer": "Unitree"},
    "spot": {
        "asset_path": "/Isaac/Robots/BostonDynamics/spot/spot.usd",
        "description": "BostonDynamics spot",
        "manufacturer": "BostonDynamics",
    },
}

# Cached discovered robots — populated on first call to list_robots.
_discovered_robots: Optional[Dict[str, Dict[str, str]]] = None


def _get_robot_library(adapter: IsaacAdapterBase) -> Dict[str, Dict[str, str]]:
    """Return the robot library, discovering from the asset server on first call.

    Falls back to FALLBACK_ROBOT_LIBRARY if discovery fails.
    """
    global _discovered_robots
    if _discovered_robots is not None:
        return _discovered_robots

    try:
        robots = adapter.discover_robots()
        if robots:
            _discovered_robots = robots
            print(f"Discovered {len(robots)} robots from asset server")
            return _discovered_robots
    except Exception as e:
        print(f"Robot discovery failed, using fallback: {e}")

    _discovered_robots = FALLBACK_ROBOT_LIBRARY
    return _discovered_robots


def _find_robot(adapter: IsaacAdapterBase, query: str) -> Optional[Dict[str, Any]]:
    """Find a robot by name. Tries exact key match, then partial match on key/description/manufacturer."""
    library = _get_robot_library(adapter)
    q = query.lower().strip()

    # Exact key match
    if q in library:
        return {"key": q, **library[q]}

    # Partial match on key, description, manufacturer
    matches = []
    for key, info in library.items():
        searchable = f"{key} {info.get('description', '')} {info.get('manufacturer', '')}".lower()
        if q in searchable:
            matches.append({"key": key, **info})

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Return closest match (shortest key that contains the query)
        matches.sort(key=lambda m: len(m["key"]))
        return matches[0]

    return None


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["robots.create"] = lambda **p: create(adapter, **p)
    registry["robots.list"] = lambda **p: list_robots(adapter, **p)
    registry["robots.refresh"] = lambda **p: refresh_robots(adapter, **p)
    registry["robots.get_info"] = lambda **p: get_info(adapter, **p)
    registry["robots.set_joints"] = lambda **p: set_joints(adapter, **p)
    registry["robots.get_joints"] = lambda **p: get_joints(adapter, **p)
    registry["robots.get_joint_state"] = lambda **p: get_joint_state(adapter, **p)
    registry["robots.set_joint_command"] = lambda **p: set_joint_command(adapter, **p)
    registry["robots.set_joint_drive_config"] = lambda **p: set_joint_drive_config(adapter, **p)


def create(
    adapter: IsaacAdapterBase,
    robot_type: str = "franka",
    position: Optional[Sequence[float]] = None,
    name: Optional[str] = None,
    prim_path: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        match = _find_robot(adapter, robot_type)
        if not match:
            library = _get_robot_library(adapter)
            available = list(library.keys())[:20]
            return {
                "status": "error",
                "message": f"Robot '{robot_type}' not found. Try robots.list to see available robots. Some options: {available}",
            }

        assets_root = adapter.get_assets_root_path()
        asset_path = assets_root + match["asset_path"]
        if prim_path is None:
            prim_name = name or match["key"].capitalize()
            prim_path = f"/{prim_name}"
        adapter.add_reference_to_stage(asset_path, prim_path)
        if position:
            # set_prim_transform works on both V5 (omni.isaac.core XFormPrim)
            # and V6 (experimental Articulation) — the experimental XformPrim
            # only exposes the batched set_world_poses(), not the singular form.
            adapter.set_prim_transform(prim_path, position=position)
        result = {
            "status": "success",
            "message": f"Created {match['description']} robot",
            "prim_path": prim_path,
            "robot_key": match["key"],
        }
        try:
            info = adapter.get_robot_joint_info(prim_path)
            result["joint_names"] = info.get("joint_names", [])
            result["num_dof"] = info.get("num_dof", 0)
        except Exception as e:
            print(f"create_robot: get_robot_joint_info failed for {prim_path}: {e}")
            traceback.print_exc()
        # Check for broken drive configs (zero stiffness + zero damping)
        try:
            joint_config = adapter.get_joint_config(prim_path)
            warnings = joint_config.get("warnings", [])
            if warnings:
                result["warnings"] = warnings
        except Exception as e:
            print(f"create_robot: get_joint_config failed for {prim_path}: {e}")
            traceback.print_exc()
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_robots(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    library = _get_robot_library(adapter)
    return {"status": "success", "robot_count": len(library), "robots": library}


def refresh_robots(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    """Force re-scan the asset server for available robots."""
    global _discovered_robots
    _discovered_robots = None
    library = _get_robot_library(adapter)
    return {
        "status": "success",
        "message": f"Refreshed robot library, found {len(library)} robots",
        "robot_count": len(library),
    }


def get_info(adapter: IsaacAdapterBase, prim_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not prim_path:
            return {"status": "error", "message": "prim_path is required"}
        info = adapter.get_robot_joint_info(prim_path)
        return {"status": "success", **info}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def set_joints(
    adapter: IsaacAdapterBase,
    prim_path: Optional[str] = None,
    joint_positions: Optional[Sequence[float]] = None,
    joint_indices: Optional[List[int]] = None,
) -> Dict[str, Any]:
    try:
        if not prim_path or joint_positions is None:
            return {"status": "error", "message": "prim_path and joint_positions are required"}
        adapter.set_joint_positions(prim_path, joint_positions, joint_indices)
        return {"status": "success", "message": f"Set joint positions on {prim_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_joints(adapter: IsaacAdapterBase, prim_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not prim_path:
            return {"status": "error", "message": "prim_path is required"}
        positions = adapter.get_joint_positions(prim_path)
        return {"status": "success", "joint_positions": positions}
    except Exception as e:
        return {"status": "error", "message": str(e)}


_COMMAND_MODES = {"position", "velocity", "effort"}


def _error(code: str, message: str, *, applied: bool = False) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, "applied": applied}


def _resolve_joint_indices(
    joint_names_available: Sequence[str],
    *,
    joint_names: Optional[Sequence[str]],
    joint_indices: Optional[Sequence[int]],
) -> tuple[Optional[List[int]], Optional[Dict[str, Any]]]:
    if joint_names is not None and joint_indices is not None:
        return None, _error("JOINT_SELECTOR_CONFLICT", "joint_names and joint_indices are mutually exclusive")

    count = len(joint_names_available)
    if joint_names is not None:
        requested = list(joint_names)
        if not requested:
            return None, _error("EMPTY_JOINT_SELECTOR", "joint_names must not be empty")
        if len(set(requested)) != len(requested):
            return None, _error("DUPLICATE_JOINT_SELECTOR", "joint_names contains duplicates")
        index_by_name = {name: index for index, name in enumerate(joint_names_available)}
        missing = [name for name in requested if name not in index_by_name]
        if missing:
            return None, _error(
                "JOINT_NOT_FOUND",
                f"Unknown joint name(s): {missing}. Available joints: {list(joint_names_available)}",
            )
        return [index_by_name[name] for name in requested], None

    if joint_indices is not None:
        requested_indices = list(joint_indices)
        if not requested_indices:
            return None, _error("EMPTY_JOINT_SELECTOR", "joint_indices must not be empty")
        if any(isinstance(index, bool) or not isinstance(index, int) for index in requested_indices):
            return None, _error("INVALID_JOINT_INDEX", "joint_indices must contain integers")
        if len(set(requested_indices)) != len(requested_indices):
            return None, _error("DUPLICATE_JOINT_SELECTOR", "joint_indices contains duplicates")
        invalid = [index for index in requested_indices if index < 0 or index >= count]
        if invalid:
            return None, _error(
                "JOINT_INDEX_OUT_OF_RANGE", f"Joint index out of range: {invalid}; valid range is 0..{count - 1}"
            )
        return requested_indices, None

    return list(range(count)), None


def _joint_units(joint_type: str) -> Dict[str, str]:
    if joint_type == "prismatic":
        return {"position": "meters", "velocity": "meters_per_second", "effort": "newtons"}
    if joint_type == "revolute":
        return {"position": "radians", "velocity": "radians_per_second", "effort": "newton_meters"}
    return {"position": "unknown", "velocity": "unknown", "effort": "unknown"}


def _selected_joint_state(
    raw_state: Dict[str, Any],
    selected_indices: Sequence[int],
) -> Dict[str, Any]:
    names = list(raw_state.get("joint_names") or [])
    types = list(raw_state.get("joint_types") or ["unknown"] * len(names))
    fields = {
        "position": raw_state.get("positions"),
        "velocity": raw_state.get("velocities"),
        "effort": raw_state.get("efforts"),
        "position_target": raw_state.get("position_targets"),
        "velocity_target": raw_state.get("velocity_targets"),
        "effort_target": raw_state.get("effort_targets"),
    }
    for field_name, values in fields.items():
        if values is not None and len(values) != len(names):
            raise ValueError(f"Adapter returned {len(values)} {field_name} values for {len(names)} joints")

    joints = []
    for index in selected_indices:
        joint_type = types[index] if index < len(types) else "unknown"
        joints.append(
            {
                "index": index,
                "name": names[index],
                "type": joint_type,
                "position": None if fields["position"] is None else fields["position"][index],
                "velocity": None if fields["velocity"] is None else fields["velocity"][index],
                "effort": None if fields["effort"] is None else fields["effort"][index],
                "targets": {
                    "position": None if fields["position_target"] is None else fields["position_target"][index],
                    "velocity": None if fields["velocity_target"] is None else fields["velocity_target"][index],
                    "effort": None if fields["effort_target"] is None else fields["effort_target"][index],
                },
                "units": _joint_units(joint_type),
            }
        )
    return {
        "prim_path": raw_state.get("prim_path"),
        "joint_count": len(names),
        "selection_count": len(joints),
        "joints": joints,
    }


def get_joint_state(
    adapter: IsaacAdapterBase,
    prim_path: Optional[str] = None,
    joint_names: Optional[Sequence[str]] = None,
    joint_indices: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    if not prim_path:
        return _error("INVALID_ARGUMENT", "prim_path is required")
    try:
        raw_state = adapter.get_joint_state(prim_path)
        names = list(raw_state.get("joint_names") or [])
        if not names:
            return _error("JOINT_STATE_UNAVAILABLE", f"No articulation DOFs found at {prim_path}")
        selected, error = _resolve_joint_indices(names, joint_names=joint_names, joint_indices=joint_indices)
        if error:
            return error
        return {"status": "success", **_selected_joint_state(raw_state, selected or [])}
    except NotImplementedError as exc:
        return {"status": "unsupported", "code": "JOINT_STATE_UNSUPPORTED", "message": str(exc)}
    except Exception as exc:
        return _error("JOINT_STATE_UNAVAILABLE", str(exc))


def set_joint_command(
    adapter: IsaacAdapterBase,
    prim_path: Optional[str] = None,
    mode: Optional[str] = None,
    values: Optional[Sequence[float]] = None,
    joint_names: Optional[Sequence[str]] = None,
    joint_indices: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    if not prim_path:
        return _error("INVALID_ARGUMENT", "prim_path is required")
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in _COMMAND_MODES:
        return _error(
            "INVALID_JOINT_COMMAND_MODE",
            f"mode must be one of {sorted(_COMMAND_MODES)}",
        )
    if values is None or isinstance(values, (str, bytes)):
        return _error("INVALID_ARGUMENT", "values must not be empty")
    try:
        raw_values = list(values)
        if not raw_values:
            return _error("INVALID_ARGUMENT", "values must not be empty")
        if any(isinstance(value, bool) for value in raw_values):
            return _error("INVALID_JOINT_VALUE", "values must contain finite numbers, not booleans")
        normalized_values = [float(value) for value in raw_values]
    except (TypeError, ValueError):
        return _error("INVALID_JOINT_VALUE", "values must contain finite numbers")
    if any(not math.isfinite(value) for value in normalized_values):
        return _error("INVALID_JOINT_VALUE", "values must contain finite numbers")

    try:
        info = adapter.get_robot_joint_info(prim_path)
        available_names = list(info.get("joint_names") or [])
        if not available_names:
            return _error("JOINT_STATE_UNAVAILABLE", f"No articulation DOFs found at {prim_path}")
        selected, error = _resolve_joint_indices(available_names, joint_names=joint_names, joint_indices=joint_indices)
        if error:
            return error
        assert selected is not None
        if len(normalized_values) != len(selected):
            return _error(
                "JOINT_VALUE_COUNT_MISMATCH",
                f"Received {len(normalized_values)} values for {len(selected)} selected joints",
            )

        adapter.set_joint_command(prim_path, normalized_mode, normalized_values, selected)
        try:
            raw_state = adapter.get_joint_state(prim_path)
            readback = _selected_joint_state(raw_state, selected)
        except Exception as exc:
            return {
                "status": "partial",
                "code": "JOINT_COMMAND_READBACK_FAILED",
                "message": f"Joint command was applied, but read-back failed: {exc}",
                "applied": True,
                "prim_path": prim_path,
                "mode": normalized_mode,
                "values": normalized_values,
                "joint_indices": selected,
                "joint_names": [available_names[index] for index in selected],
            }
        return {
            "status": "success",
            "message": f"Applied {normalized_mode} command to {len(selected)} joint(s) on {prim_path}",
            "applied": True,
            "prim_path": prim_path,
            "mode": normalized_mode,
            "values": normalized_values,
            "joint_indices": selected,
            "joint_names": [available_names[index] for index in selected],
            "readback": readback,
        }
    except NotImplementedError as exc:
        return {
            "status": "unsupported",
            "code": "JOINT_COMMAND_UNSUPPORTED",
            "message": str(exc),
            "applied": False,
        }
    except Exception as exc:
        return _error("JOINT_COMMAND_FAILED", str(exc))


_DRIVE_NUMERIC_FIELDS = ("stiffness", "damping", "max_force", "max_velocity")
_DRIVE_TYPES = {"force", "acceleration"}
_FLOAT32_MAX = 3.4028234663852886e38


def _selected_drive_config(raw_config: Dict[str, Any], selected_indices: Sequence[int]) -> Dict[str, Any]:
    joints = list(raw_config.get("joints") or [])
    by_index = {joint.get("index"): joint for joint in joints}
    missing = [index for index in selected_indices if index not in by_index]
    if missing:
        raise ValueError(f"Drive read-back is missing DOF indices: {missing}")
    return {
        "prim_path": raw_config.get("prim_path"),
        "joint_count": raw_config.get("joint_count", len(joints)),
        "selection_count": len(selected_indices),
        "joints": [by_index[index] for index in selected_indices],
    }


def set_joint_drive_config(
    adapter: IsaacAdapterBase,
    prim_path: Optional[str] = None,
    stiffness: Optional[float] = None,
    damping: Optional[float] = None,
    max_force: Optional[float] = None,
    max_velocity: Optional[float] = None,
    drive_type: Optional[str] = None,
    joint_names: Optional[Sequence[str]] = None,
    joint_indices: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    if not prim_path:
        return _error("INVALID_ARGUMENT", "prim_path is required")

    raw_config = {
        "stiffness": stiffness,
        "damping": damping,
        "max_force": max_force,
        "max_velocity": max_velocity,
        "drive_type": drive_type,
    }
    if all(value is None for value in raw_config.values()):
        return _error("EMPTY_JOINT_DRIVE_CONFIG", "At least one drive configuration field is required")

    config: Dict[str, Any] = {}
    for field in _DRIVE_NUMERIC_FIELDS:
        value = raw_config[field]
        if value is None:
            continue
        if isinstance(value, bool):
            return _error("INVALID_JOINT_DRIVE_VALUE", f"{field} must be a finite non-negative number")
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return _error("INVALID_JOINT_DRIVE_VALUE", f"{field} must be a finite non-negative number")
        if not math.isfinite(normalized) or normalized < 0 or normalized > _FLOAT32_MAX:
            return _error(
                "INVALID_JOINT_DRIVE_VALUE",
                f"{field} must be a finite number in the range 0..{_FLOAT32_MAX}",
            )
        config[field] = normalized

    if drive_type is not None:
        normalized_drive_type = str(drive_type).strip().lower()
        if normalized_drive_type not in _DRIVE_TYPES:
            return _error("INVALID_JOINT_DRIVE_TYPE", f"drive_type must be one of {sorted(_DRIVE_TYPES)}")
        config["drive_type"] = normalized_drive_type

    try:
        simulation_state = adapter.get_simulation_state()
        timeline_state = str(simulation_state.get("timeline_state", "unknown")).lower()
        if timeline_state != "stopped":
            return _error(
                "JOINT_DRIVE_TIMELINE_ACTIVE",
                f"Drive configuration requires a stopped timeline; current state is {timeline_state}",
            )
        engine = str(simulation_state.get("engine", "unknown")).lower()
        if engine == "newton" and "max_velocity" in config:
            return {
                "status": "unsupported",
                "code": "JOINT_DRIVE_FIELD_UNSUPPORTED",
                "message": "max_velocity uses PhysxJointAPI and is unavailable under Newton",
                "applied": False,
            }

        info = adapter.get_robot_joint_info(prim_path)
        available_names = list(info.get("joint_names") or [])
        if not available_names:
            return _error("JOINT_STATE_UNAVAILABLE", f"No articulation DOFs found at {prim_path}")
        selected, error = _resolve_joint_indices(
            available_names,
            joint_names=joint_names,
            joint_indices=joint_indices,
        )
        if error:
            return error
        assert selected is not None

        adapter.set_joint_drive_config(prim_path, config, selected)
        try:
            readback = _selected_drive_config(adapter.get_joint_drive_config(prim_path), selected)
        except Exception as exc:
            return {
                "status": "partial",
                "code": "JOINT_DRIVE_READBACK_FAILED",
                "message": f"Drive configuration was applied, but read-back failed: {exc}",
                "applied": True,
                "prim_path": prim_path,
                "config": config,
                "joint_indices": selected,
                "joint_names": [available_names[index] for index in selected],
            }
        return {
            "status": "success",
            "message": f"Updated drive configuration on {len(selected)} joint(s) at {prim_path}",
            "applied": True,
            "prim_path": prim_path,
            "config": config,
            "joint_indices": selected,
            "joint_names": [available_names[index] for index in selected],
            "readback": readback,
        }
    except NotImplementedError as exc:
        return {
            "status": "unsupported",
            "code": "JOINT_DRIVE_CONFIG_UNSUPPORTED",
            "message": str(exc),
            "applied": False,
        }
    except JointDriveConfigApplyError as exc:
        if exc.rollback_succeeded:
            return _error("JOINT_DRIVE_CONFIG_FAILED", str(exc))
        return {
            "status": "partial",
            "code": "JOINT_DRIVE_ROLLBACK_FAILED",
            "message": str(exc),
            "applied": None,
            "rollback_succeeded": False,
        }
    except Exception as exc:
        return _error("JOINT_DRIVE_CONFIG_FAILED", str(exc))
