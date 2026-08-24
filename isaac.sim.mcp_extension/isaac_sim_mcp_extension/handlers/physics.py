"""Validated typed physics authoring handlers."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence

from ..adapters.base import IsaacAdapterBase

_BODY_TYPES = {"dynamic", "kinematic", "static"}
_APPROXIMATIONS = {
    "none",
    "convex_hull",
    "convex_decomposition",
    "mesh_simplification",
    "bounding_cube",
    "bounding_sphere",
}
_JOINT_TYPES = {"fixed", "revolute", "prismatic"}


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["physics.configure_body"] = lambda **p: configure_body(adapter, **p)
    registry["physics.get_body"] = lambda **p: get_body(adapter, **p)
    registry["physics.create_collision_group"] = lambda **p: create_collision_group(adapter, **p)
    registry["physics.get_collision_group"] = lambda **p: get_collision_group(adapter, **p)
    registry["physics.create_joint"] = lambda **p: create_joint(adapter, **p)
    registry["physics.get_joint"] = lambda **p: get_joint(adapter, **p)


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, "applied": False}


def _require_stopped(adapter: IsaacAdapterBase) -> Optional[Dict[str, Any]]:
    state = str(adapter.get_simulation_state().get("timeline_state", "unknown")).lower()
    if state != "stopped":
        return _error("TIMELINE_NOT_STOPPED", f"Physics authoring requires stopped timeline; current state is {state}")
    return None


def _positive(value: Optional[float], name: str) -> None:
    if value is not None and (not math.isfinite(float(value)) or float(value) <= 0):
        raise ValueError(f"{name} must be finite and greater than zero")


def configure_body(
    adapter: IsaacAdapterBase,
    prim_path: Optional[str] = None,
    body_type: str = "dynamic",
    collider_enabled: bool = True,
    approximation: Optional[str] = None,
    mass_kg: Optional[float] = None,
    density_kg_m3: Optional[float] = None,
) -> Dict[str, Any]:
    try:
        if stopped := _require_stopped(adapter):
            return stopped
        if not prim_path:
            raise ValueError("prim_path is required")
        body_type = str(body_type).lower()
        if body_type not in _BODY_TYPES:
            raise ValueError("body_type must be dynamic, kinematic, or static")
        if approximation is not None and approximation not in _APPROXIMATIONS:
            raise ValueError(f"unsupported approximation: {approximation}")
        _positive(mass_kg, "mass_kg")
        _positive(density_kg_m3, "density_kg_m3")
        if mass_kg is not None and density_kg_m3 is not None:
            raise ValueError("mass_kg and density_kg_m3 are mutually exclusive")
        if body_type == "static" and (mass_kg is not None or density_kg_m3 is not None):
            raise ValueError("static bodies cannot author mass or density")
        readback = adapter.configure_physics_body(
            prim_path=prim_path,
            body_type=body_type,
            collider_enabled=bool(collider_enabled),
            approximation=approximation,
            mass_kg=mass_kg,
            density_kg_m3=density_kg_m3,
        )
        return {"status": "success", "applied": True, "atomic": True, "readback": readback}
    except ValueError as exc:
        return _error("INVALID_PHYSICS_BODY", str(exc))
    except Exception as exc:
        return _error("PHYSICS_BODY_AUTHORING_FAILED", str(exc))


def get_body(adapter: IsaacAdapterBase, prim_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not prim_path:
            raise ValueError("prim_path is required")
        return {"status": "success", **adapter.get_physics_body(prim_path)}
    except ValueError as exc:
        return _error("INVALID_PHYSICS_BODY", str(exc))
    except Exception as exc:
        return _error("PHYSICS_BODY_READ_FAILED", str(exc))


def create_collision_group(
    adapter: IsaacAdapterBase,
    group_path: Optional[str] = None,
    collider_paths: Optional[Sequence[str]] = None,
    filtered_group_paths: Optional[Sequence[str]] = None,
    invert_filtered_groups: bool = False,
    merge_group_name: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        if stopped := _require_stopped(adapter):
            return stopped
        if not group_path:
            raise ValueError("group_path is required")
        if not collider_paths or any(not path for path in collider_paths):
            raise ValueError("collider_paths must contain at least one prim path")
        readback = adapter.create_collision_group(
            group_path=group_path,
            collider_paths=list(collider_paths),
            filtered_group_paths=list(filtered_group_paths or []),
            invert_filtered_groups=bool(invert_filtered_groups),
            merge_group_name=merge_group_name,
        )
        return {"status": "success", "applied": True, "atomic": True, "readback": readback}
    except ValueError as exc:
        return _error("INVALID_COLLISION_GROUP", str(exc))
    except Exception as exc:
        return _error("COLLISION_GROUP_AUTHORING_FAILED", str(exc))


def get_collision_group(adapter: IsaacAdapterBase, group_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not group_path:
            raise ValueError("group_path is required")
        return {"status": "success", **adapter.get_collision_group(group_path)}
    except ValueError as exc:
        return _error("INVALID_COLLISION_GROUP", str(exc))
    except Exception as exc:
        return _error("COLLISION_GROUP_READ_FAILED", str(exc))


def _vector(value: Optional[Sequence[float]], length: int, name: str) -> Optional[list[float]]:
    if value is None:
        return None
    if len(value) != length:
        raise ValueError(f"{name} must contain {length} finite values")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must contain {length} finite values")
    if length == 4 and math.sqrt(sum(item * item for item in result)) <= 1e-12:
        raise ValueError(f"{name} quaternion cannot be zero")
    return result


def create_joint(
    adapter: IsaacAdapterBase,
    joint_path: Optional[str] = None,
    joint_type: str = "fixed",
    body1: Optional[str] = None,
    body0: Optional[str] = None,
    axis: Optional[str] = None,
    lower_limit: Optional[float] = None,
    upper_limit: Optional[float] = None,
    local_position0: Optional[Sequence[float]] = None,
    local_rotation0: Optional[Sequence[float]] = None,
    local_position1: Optional[Sequence[float]] = None,
    local_rotation1: Optional[Sequence[float]] = None,
    collision_enabled: bool = False,
) -> Dict[str, Any]:
    try:
        if stopped := _require_stopped(adapter):
            return stopped
        if not joint_path or not body1:
            raise ValueError("joint_path and body1 are required")
        joint_type = str(joint_type).lower()
        if joint_type not in _JOINT_TYPES:
            raise ValueError("joint_type must be fixed, revolute, or prismatic")
        if joint_type == "fixed":
            if axis is not None or lower_limit is not None or upper_limit is not None:
                raise ValueError("fixed joints do not accept axis or limits")
        else:
            axis = str(axis or "").upper()
            if axis not in {"X", "Y", "Z"}:
                raise ValueError("axis must be X, Y, or Z")
            if (lower_limit is None) != (upper_limit is None):
                raise ValueError("lower_limit and upper_limit must be supplied together")
            if lower_limit is not None:
                lower_limit, upper_limit = float(lower_limit), float(upper_limit)
                if not math.isfinite(lower_limit) or not math.isfinite(upper_limit) or lower_limit > upper_limit:
                    raise ValueError("joint limits must be finite and lower_limit <= upper_limit")
        kwargs = {
            "joint_path": joint_path,
            "joint_type": joint_type,
            "body1": body1,
            "body0": body0,
            "axis": axis,
            "lower_limit": lower_limit,
            "upper_limit": upper_limit,
            "local_position0": _vector(local_position0, 3, "local_position0"),
            "local_rotation0": _vector(local_rotation0, 4, "local_rotation0"),
            "local_position1": _vector(local_position1, 3, "local_position1"),
            "local_rotation1": _vector(local_rotation1, 4, "local_rotation1"),
            "collision_enabled": bool(collision_enabled),
        }
        readback = adapter.create_physics_joint(**kwargs)
        return {"status": "success", "applied": True, "atomic": True, "readback": readback}
    except ValueError as exc:
        return _error("INVALID_PHYSICS_JOINT", str(exc))
    except Exception as exc:
        return _error("PHYSICS_JOINT_AUTHORING_FAILED", str(exc))


def get_joint(adapter: IsaacAdapterBase, joint_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not joint_path:
            raise ValueError("joint_path is required")
        return {"status": "success", **adapter.get_physics_joint(joint_path)}
    except ValueError as exc:
        return _error("INVALID_PHYSICS_JOINT", str(exc))
    except Exception as exc:
        return _error("PHYSICS_JOINT_READ_FAILED", str(exc))
