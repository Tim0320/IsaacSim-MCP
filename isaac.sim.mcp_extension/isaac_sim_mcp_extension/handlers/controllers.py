"""Fail-closed controller profiles for grippers and mobile bases."""

from __future__ import annotations

import math
from typing import Any, Dict, Sequence

from ..adapters.base import IsaacAdapterBase
from ..controller_profiles import CONTROLLER_PROFILES, public_profiles
from .robots import _selected_joint_state


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["controllers.list_profiles"] = lambda **_p: list_profiles()
    registry["controllers.set_gripper_width"] = lambda **p: set_gripper_width(adapter, **p)
    registry["controllers.open_gripper"] = lambda **p: open_gripper(adapter, **p)
    registry["controllers.close_gripper"] = lambda **p: close_gripper(adapter, **p)
    registry["controllers.set_mobile_base_velocity"] = lambda **p: set_mobile_base_velocity(adapter, **p)
    registry["controllers.stop_mobile_base"] = lambda **p: stop_mobile_base(adapter, **p)


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, "applied": False}


def _finite(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _profile(name: str, kinds: set[str]) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    profile = CONTROLLER_PROFILES.get(str(name))
    if profile is None:
        return None, _error(
            "CONTROLLER_PROFILE_NOT_FOUND",
            f"Unknown profile {name!r}; call list_controller_profiles for supported names",
        )
    if profile["kind"] not in kinds:
        return None, _error(
            "CONTROLLER_PROFILE_KIND_MISMATCH",
            f"Profile {name!r} has kind {profile['kind']!r}, expected one of {sorted(kinds)}",
        )
    return profile, None


def _bind_profile(
    adapter: IsaacAdapterBase, prim_path: str, profile_name: str, profile: Dict[str, Any]
) -> tuple[list[int] | None, Dict[str, Any] | None]:
    info = adapter.get_robot_joint_info(prim_path)
    available = list(info.get("joint_names") or [])
    required = list(profile["joint_names"])
    missing = [name for name in required if name not in available]
    joint_types = {item.get("name"): item.get("type") for item in info.get("joint_limits", [])}
    wrong_types = [name for name in required if joint_types.get(name) != profile["joint_type"]]
    if missing or wrong_types:
        return None, _error(
            "CONTROLLER_PROFILE_MISMATCH",
            (
                f"Profile {profile_name!r} does not match {prim_path}: missing joints={missing}, "
                f"wrong joint types={wrong_types}; no command was applied"
            ),
        )
    return [available.index(name) for name in required], None


def _apply(
    adapter: IsaacAdapterBase,
    prim_path: str,
    profile_name: str,
    profile: Dict[str, Any],
    mode: str,
    values: Sequence[float],
) -> Dict[str, Any]:
    try:
        indices, error = _bind_profile(adapter, prim_path, profile_name, profile)
    except Exception as exc:
        return _error("CONTROLLER_PROFILE_BIND_FAILED", str(exc))
    if error:
        return error
    assert indices is not None
    try:
        adapter.set_joint_command(prim_path, mode, list(values), indices)
        raw = adapter.get_joint_state(prim_path)
        readback = _selected_joint_state(raw, indices)
    except NotImplementedError as exc:
        return {"status": "unsupported", "code": "CONTROLLER_PROFILE_UNSUPPORTED", "message": str(exc)}
    except Exception as exc:
        return _error("CONTROLLER_COMMAND_FAILED", str(exc))
    return {
        "status": "success",
        "code": "CONTROLLER_COMMAND_APPLIED",
        "message": f"Applied {profile_name} {mode} command",
        "applied": True,
        "prim_path": prim_path,
        "profile": profile_name,
        "profile_kind": profile["kind"],
        "joint_names": list(profile["joint_names"]),
        "joint_indices": indices,
        "readback": readback,
    }


def list_profiles() -> Dict[str, Any]:
    profiles = public_profiles()
    return {
        "status": "success",
        "code": "CONTROLLER_PROFILES",
        "message": f"{len(profiles)} explicit controller profiles",
        "profile_count": len(profiles),
        "profiles": profiles,
    }


def set_gripper_width(
    adapter: IsaacAdapterBase, prim_path: str, profile: str, width_m: float
) -> Dict[str, Any]:
    selected, error = _profile(profile, {"gripper"})
    if error:
        return error
    assert selected is not None
    try:
        width = _finite("width_m", width_m)
    except ValueError as exc:
        return _error("INVALID_GRIPPER_WIDTH", str(exc))
    if not selected["min_width_m"] <= width <= selected["max_width_m"]:
        return _error(
            "GRIPPER_WIDTH_OUT_OF_RANGE",
            f"width_m must be within [{selected['min_width_m']}, {selected['max_width_m']}] for {profile}",
        )
    values = [width / 2.0, width / 2.0]
    result = _apply(adapter, prim_path, profile, selected, "position", values)
    if result["status"] == "success":
        result.update(requested_width_m=width, finger_targets_m=values)
    return result


def open_gripper(adapter: IsaacAdapterBase, prim_path: str, profile: str) -> Dict[str, Any]:
    selected, error = _profile(profile, {"gripper"})
    if error:
        return error
    assert selected is not None
    return set_gripper_width(adapter, prim_path, profile, selected["open_width_m"])


def close_gripper(adapter: IsaacAdapterBase, prim_path: str, profile: str) -> Dict[str, Any]:
    selected, error = _profile(profile, {"gripper"})
    if error:
        return error
    assert selected is not None
    return set_gripper_width(adapter, prim_path, profile, selected["closed_width_m"])


def _mobile_values(profile: Dict[str, Any], forward: float, lateral: float, yaw: float) -> Dict[str, Any] | None:
    limits = (
        ("forward_mps", forward, profile["max_linear_speed_mps"]),
        ("lateral_mps", lateral, profile["max_lateral_speed_mps"]),
        ("yaw_radps", yaw, profile["max_yaw_speed_radps"]),
    )
    exceeded = {name: {"requested": value, "max_abs": maximum} for name, value, maximum in limits if abs(value) > maximum}
    return exceeded or None


def set_mobile_base_velocity(
    adapter: IsaacAdapterBase,
    prim_path: str,
    profile: str,
    forward_mps: float,
    lateral_mps: float = 0.0,
    yaw_radps: float = 0.0,
) -> Dict[str, Any]:
    selected, error = _profile(profile, {"differential_mobile_base", "holonomic_mobile_base"})
    if error:
        return error
    assert selected is not None
    try:
        forward = _finite("forward_mps", forward_mps)
        lateral = _finite("lateral_mps", lateral_mps)
        yaw = _finite("yaw_radps", yaw_radps)
    except ValueError as exc:
        return _error("INVALID_BASE_VELOCITY", str(exc))
    if selected["kind"] == "differential_mobile_base" and lateral != 0.0:
        return _error(
            "PROFILE_DOES_NOT_SUPPORT_LATERAL_VELOCITY",
            f"Profile {profile!r} requires lateral_mps=0",
        )
    exceeded = _mobile_values(selected, forward, lateral, yaw)
    if exceeded:
        return _error("BASE_VELOCITY_LIMIT_EXCEEDED", f"Profile limits exceeded: {exceeded}")
    if any(value != 0.0 for value in (forward, lateral, yaw)):
        try:
            state = adapter.get_simulation_state()
        except Exception as exc:
            return _error("SIMULATION_STATE_UNAVAILABLE", str(exc))
        if state.get("timeline_state") != "playing":
            return _error("TIMELINE_NOT_PLAYING", "Non-zero mobile-base commands require a playing timeline")

    if not any(value != 0.0 for value in (forward, lateral, yaw)):
        wheel_values = [0.0] * len(selected["joint_names"])
    elif selected["kind"] == "differential_mobile_base":
        radius = selected["wheel_radius_m"]
        half_base = selected["wheel_base_m"] / 2.0
        wheel_values = [(forward - yaw * half_base) / radius, (forward + yaw * half_base) / radius]
    else:
        try:
            wheel_values = adapter.compute_holonomic_wheel_velocities(
                prim_path,
                prim_path.rstrip("/") + selected["com_prim_suffix"],
                [forward, lateral, yaw],
                selected["joint_names"],
            )
        except NotImplementedError as exc:
            return {"status": "unsupported", "code": "HOLONOMIC_CONTROLLER_UNSUPPORTED", "message": str(exc)}
        except Exception as exc:
            return _error("HOLONOMIC_GEOMETRY_INVALID", str(exc))
    result = _apply(adapter, prim_path, profile, selected, "velocity", wheel_values)
    if result["status"] == "success":
        result.update(
            command={"forward_mps": forward, "lateral_mps": lateral, "yaw_radps": yaw},
            wheel_velocity_targets_radps=list(wheel_values),
            persistent_until_stopped=True,
        )
    return result


def stop_mobile_base(adapter: IsaacAdapterBase, prim_path: str, profile: str) -> Dict[str, Any]:
    result = set_mobile_base_velocity(adapter, prim_path, profile, 0.0, 0.0, 0.0)
    if result["status"] != "success":
        return result
    targets = [joint["targets"]["velocity"] for joint in result["readback"]["joints"]]
    stopped = all(value is not None and math.isclose(float(value), 0.0, abs_tol=1e-8) for value in targets)
    result.update(
        code="MOBILE_BASE_STOPPED" if stopped else "MOBILE_BASE_STOP_READBACK_FAILED",
        message="Mobile-base wheel velocity targets are zero" if stopped else "Stop command applied but zero targets were not read back",
        stopped=stopped,
    )
    if not stopped:
        result["status"] = "partial"
    return result
