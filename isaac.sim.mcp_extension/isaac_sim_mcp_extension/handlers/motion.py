"""Motion-generation handlers with a bounded, non-blocking job lifecycle."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable

from ..adapters.base import IsaacAdapterBase


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["motion.compute_ik"] = lambda **p: compute_ik(adapter, **p)
    registry["motion.plan_joint_trajectory"] = lambda **p: plan_joint_trajectory(adapter, **p)
    registry["motion.execute_trajectory"] = lambda **p: execute_trajectory(adapter, **p)
    registry["motion.cancel"] = lambda **p: cancel_motion(adapter, **p)
    registry["motion.get_status"] = lambda **p: get_motion_status(adapter, **p)


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, "applied": False}


def _vector(name: str, value: Iterable[Any], length: int | None = None) -> list[float]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a numeric list")
    result = list(value)
    if length is not None and len(result) != length:
        raise ValueError(f"{name} must contain exactly {length} values")
    if not result or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain finite numbers")
    return [float(v) for v in result]


def _bounds(timeout_ms: int, max_iterations: int | None = None) -> None:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 1 <= timeout_ms <= 120000:
        raise ValueError("timeout_ms must be an integer from 1 through 120000")
    if max_iterations is not None and (
        isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or not 1 <= max_iterations <= 100000
    ):
        raise ValueError("max_iterations must be an integer from 1 through 100000")


def compute_ik(adapter: IsaacAdapterBase, **params: Any) -> Dict[str, Any]:
    try:
        params["target_position"] = _vector("target_position", params["target_position"], 3)
        if params.get("target_orientation") is not None:
            params["target_orientation"] = _vector("target_orientation", params["target_orientation"], 4)
        if params.get("seed_joint_positions") is not None:
            params["seed_joint_positions"] = _vector("seed_joint_positions", params["seed_joint_positions"])
        _bounds(params.get("timeout_ms", 2000), params.get("max_iterations", 100))
        return adapter.compute_ik(**params)
    except (KeyError, TypeError, ValueError) as exc:
        return _error("INVALID_MOTION_REQUEST", str(exc))
    except NotImplementedError as exc:
        return {"status": "unsupported", "code": "MOTION_UNSUPPORTED", "message": str(exc), "applied": False}
    except Exception as exc:
        return _error("IK_FAILED", str(exc))


def plan_joint_trajectory(adapter: IsaacAdapterBase, **params: Any) -> Dict[str, Any]:
    try:
        params["goal_joint_positions"] = _vector("goal_joint_positions", params["goal_joint_positions"])
        if params.get("start_joint_positions") is not None:
            params["start_joint_positions"] = _vector("start_joint_positions", params["start_joint_positions"])
        if params.get("planner", "rrt") not in {"rrt", "cspace"}:
            raise ValueError("planner must be 'rrt' or 'cspace'")
        _bounds(params.get("timeout_ms", 5000), params.get("max_iterations", 5000))
        return adapter.plan_joint_trajectory(**params)
    except (KeyError, TypeError, ValueError) as exc:
        return _error("INVALID_MOTION_REQUEST", str(exc))
    except NotImplementedError as exc:
        return {"status": "unsupported", "code": "MOTION_UNSUPPORTED", "message": str(exc), "applied": False}
    except TimeoutError as exc:
        return {"status": "timeout", "code": "MOTION_PLAN_TIMEOUT", "message": str(exc), "applied": False}
    except Exception as exc:
        return _error("MOTION_PLAN_FAILED", str(exc))


def execute_trajectory(adapter: IsaacAdapterBase, trajectory_id: str, timeout_ms: int = 30000) -> Dict[str, Any]:
    try:
        _bounds(timeout_ms)
        return adapter.execute_trajectory(trajectory_id=trajectory_id, timeout_ms=timeout_ms)
    except (TypeError, ValueError) as exc:
        return _error("INVALID_MOTION_REQUEST", str(exc))
    except Exception as exc:
        return _error("MOTION_EXECUTION_FAILED", str(exc))


def cancel_motion(adapter: IsaacAdapterBase, job_id: str) -> Dict[str, Any]:
    try:
        return adapter.cancel_motion(job_id=job_id)
    except (TypeError, ValueError) as exc:
        return _error("MOTION_JOB_NOT_FOUND", str(exc))
    except Exception as exc:
        return _error("MOTION_CANCEL_FAILED", str(exc))


def get_motion_status(adapter: IsaacAdapterBase, job_id: str) -> Dict[str, Any]:
    try:
        return adapter.get_motion_status(job_id=job_id)
    except (TypeError, ValueError) as exc:
        return _error("MOTION_JOB_NOT_FOUND", str(exc))
    except Exception as exc:
        return _error("MOTION_STATUS_FAILED", str(exc))
