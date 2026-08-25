"""Unified bounded lifecycle for long-running MCP work."""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional

MAX_JOBS = 64
MAX_DEADLINE_MS = 300000
TERMINAL_STATES = {"succeeded", "failed", "cancelled", "timed_out"}
ASYNC_COMMANDS = {
    "assets.import_urdf",
    "assets.load_usd",
    "assets.spawn_nvidia",
    "sensors.capture_image",
    "sensors.capture_camera_output",
    "sensors.get_point_cloud",
}

_JOBS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_REGISTRY: Dict[str, Callable[..., Any]] = {}


def register(registry: Dict[str, Any], _adapter: Any) -> None:
    global _REGISTRY
    _REGISTRY = registry
    registry["job.start"] = lambda **p: start_job(**p)
    registry["job.get_status"] = lambda **p: get_job_status(**p)
    registry["job.cancel"] = lambda **p: cancel_job(**p)
    registry["job.list"] = lambda **p: list_jobs(**p)


def _error(code: str, message: str, *, status: str = "error") -> Dict[str, Any]:
    return {"status": status, "code": code, "message": message, "applied": False}


def _validate_deadline(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_DEADLINE_MS:
        raise ValueError(f"deadline_ms must be an integer from 1 through {MAX_DEADLINE_MS}")
    return value


def _snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    result = {
        "job_id": job["job_id"],
        "command_type": job["command_type"],
        "state": job["state"],
        "terminal": job["state"] in TERMINAL_STATES,
        "progress": job["progress"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "deadline_at": job["deadline_at"],
        "remaining_ms": max(0, round((job["deadline_at"] - now) * 1000)),
        "error": job["error"],
        "result": job["result"],
        "artifacts": job["artifacts"],
    }
    return result


def _evict_terminal() -> None:
    while len(_JOBS) >= MAX_JOBS:
        victim = next((job_id for job_id, job in _JOBS.items() if job["state"] in TERMINAL_STATES), None)
        if victim is None:
            raise RuntimeError(f"at most {MAX_JOBS} active or retained jobs are allowed")
        _JOBS.pop(victim, None)


async def _run(job: Dict[str, Any], handler: Callable[..., Any], params: Dict[str, Any]) -> None:
    job["state"] = "running"
    job["started_at"] = time.time()
    try:
        remaining = max(0.001, job["deadline_at"] - time.time())

        async def invoke() -> Any:
            value = handler(**params)
            return await value if inspect.isawaitable(value) else value

        result = await asyncio.wait_for(invoke(), timeout=remaining)
        if time.time() > job["deadline_at"]:
            job["state"] = "timed_out"
            job["error"] = "Job deadline exceeded"
        elif isinstance(result, dict) and result.get("status") in {"error", "partial", "unsupported", "timeout"}:
            job["state"] = "timed_out" if result.get("status") == "timeout" else "failed"
            job["error"] = str(result.get("message") or "Command did not complete")
            job["result"] = result
        else:
            job["state"] = "succeeded"
            job["result"] = result
            if isinstance(result, dict):
                job["artifacts"] = list(result.get("artifacts") or [])
        job["progress"] = 1.0
    except asyncio.TimeoutError:
        job["state"] = "timed_out"
        job["error"] = "Job deadline exceeded"
    except asyncio.CancelledError:
        job["state"] = "cancelled"
        job["error"] = "Cancellation requested"
    except Exception as exc:
        job["state"] = "failed"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = time.time()


def start_job(command_type: str, params: Optional[Dict[str, Any]] = None, deadline_ms: int = 30000) -> Dict[str, Any]:
    try:
        deadline_ms = _validate_deadline(deadline_ms)
        if command_type not in ASYNC_COMMANDS:
            return _error("JOB_COMMAND_NOT_ALLOWED", f"command_type is not eligible for managed jobs: {command_type}")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        handler = _REGISTRY.get(command_type)
        if handler is None:
            return _error("JOB_COMMAND_UNAVAILABLE", f"command handler is unavailable: {command_type}")
        loop = asyncio.get_running_loop()
        _evict_terminal()
        now = time.time()
        job_id = f"job-{uuid.uuid4()}"
        job = {
            "job_id": job_id,
            "command_type": command_type,
            "state": "queued",
            "progress": 0.0,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "deadline_at": now + deadline_ms / 1000.0,
            "error": None,
            "result": None,
            "artifacts": [],
            "task": None,
        }
        _JOBS[job_id] = job
        job["task"] = loop.create_task(_run(job, handler, dict(params)))
        return {
            "status": "success",
            "code": "JOB_STARTED",
            "message": "Managed job queued",
            "data": _snapshot(job),
            "readback": {"job_id": job_id, "state": "queued"},
        }
    except (TypeError, ValueError) as exc:
        return _error("INVALID_JOB_REQUEST", str(exc))
    except RuntimeError as exc:
        return _error("JOB_RUNTIME_UNAVAILABLE", str(exc), status="unsupported")


def _provider_status(job_id: str) -> Optional[Dict[str, Any]]:
    if job_id.startswith("motion-"):
        handler = _REGISTRY.get("motion.get_status")
    elif job_id.startswith("sdg-"):
        handler = _REGISTRY.get("replicator.get_job_status")
    else:
        return None
    return handler(job_id=job_id) if handler else None


def get_job_status(job_id: str) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is not None:
        return {"status": "success", "code": "JOB_STATUS", "message": "Managed job status", "data": _snapshot(job)}
    provider = _provider_status(job_id)
    if provider is not None:
        return provider
    return _error("JOB_NOT_FOUND", f"job not found: {job_id}")


def cancel_job(job_id: str) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is not None:
        if job["state"] in TERMINAL_STATES:
            return {"status": "success", "code": "JOB_ALREADY_TERMINAL", "message": "Job is already terminal", "data": _snapshot(job)}
        job["task"].cancel()
        job["state"] = "cancelled"
        job["finished_at"] = time.time()
        job["error"] = "Cancellation requested"
        return {"status": "cancelled", "code": "JOB_CANCELLED", "message": "Job cancellation requested", "data": _snapshot(job)}
    if job_id.startswith("motion-"):
        handler = _REGISTRY.get("motion.cancel")
        return handler(job_id=job_id) if handler else _error("JOB_PROVIDER_UNAVAILABLE", "motion provider unavailable")
    if job_id.startswith("sdg-"):
        handler = _REGISTRY.get("replicator.cancel_job")
        return handler(job_id=job_id, preview=False) if handler else _error("JOB_PROVIDER_UNAVAILABLE", "SDG provider unavailable")
    return _error("JOB_NOT_FOUND", f"job not found: {job_id}")


def list_jobs(count: int = 50, include_terminal: bool = True) -> Dict[str, Any]:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_JOBS:
        return _error("INVALID_JOB_QUERY", f"count must be an integer from 1 through {MAX_JOBS}")
    jobs = [job for job in _JOBS.values() if include_terminal or job["state"] not in TERMINAL_STATES]
    data = [_snapshot(job) for job in jobs[-count:]]
    return {"status": "success", "code": "JOB_LIST", "message": f"Returned {len(data)} managed jobs", "data": {"jobs": data, "count": len(data), "max_jobs": MAX_JOBS}}
