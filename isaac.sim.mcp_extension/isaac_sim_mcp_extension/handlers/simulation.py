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

"""Simulation control command handlers."""

from __future__ import annotations

import glob
import math
import os
import time
from typing import Any, Dict, Optional, Sequence, Tuple

from ..adapters.base import IsaacAdapterBase, PhysicsParamsApplyError
from ..script_policy import SCRIPT_POLICY


def configure_script_policy(settings: Any = None) -> None:
    SCRIPT_POLICY.configure(settings)


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["simulation.play"] = lambda **p: play(adapter, **p)
    registry["simulation.pause"] = lambda **p: pause(adapter, **p)
    registry["simulation.stop"] = lambda **p: stop(adapter, **p)
    registry["simulation.step"] = lambda **p: step(adapter, **p)
    registry["simulation.set_physics"] = lambda **p: set_physics(adapter, **p)
    registry["simulation.execute_script"] = lambda **p: execute_script(adapter, **p)
    registry["simulation.get_script_policy"] = lambda **p: get_script_policy(**p)
    registry["simulation.get_script_audit"] = lambda **p: get_script_audit(**p)
    registry["simulation.get_state"] = lambda **p: get_simulation_state(adapter, **p)
    registry["simulation.get_logs"] = lambda **p: get_logs(adapter, **p)
    registry["simulation.get_physics_state"] = lambda **p: get_physics_state_handler(adapter, **p)
    registry["simulation.get_joint_config"] = lambda **p: get_joint_config_handler(adapter, **p)
    registry["simulation.reload_script"] = lambda **p: reload_script_handler(adapter, **p)


def play(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    try:
        adapter.play()
        return {"status": "success", "message": "Simulation started"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def pause(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    try:
        adapter.pause()
        return {"status": "success", "message": "Simulation paused"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def stop(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    try:
        adapter.stop()
        return {"status": "success", "message": "Simulation stopped"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def step(
    adapter: IsaacAdapterBase,
    num_steps: int = 1,
    observe_prims: Optional[Sequence[str]] = None,
    observe_joints: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    try:
        # Fail loud: stepping is only valid on a frozen (paused/stopped)
        # timeline. If a free run is active, N frames cannot be counted
        # exactly, so refuse rather than silently race the play loop.
        state = adapter.get_simulation_state()
        timeline_state = state.get("timeline_state") if isinstance(state, dict) else None
        if timeline_state == "playing":
            return {
                "status": "error",
                "message": (
                    "Cannot step while the simulation is running. A free-running "
                    "timeline is active — call pause_simulation or stop_simulation "
                    "first. Do not call play_simulation during the debug loop; "
                    "step_simulation is for a frozen timeline."
                ),
            }
        result = adapter.step(num_steps=num_steps, observe_prims=observe_prims, observe_joints=observe_joints)
        return {
            "status": "success",
            "message": f"Stepped {num_steps} frames",
            "timeline_state": timeline_state,
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def set_physics(
    adapter: IsaacAdapterBase,
    gravity: Optional[Sequence[float]] = None,
    time_step: Optional[float] = None,
    gpu_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    if gravity is None and time_step is None and gpu_enabled is None:
        return {
            "status": "error",
            "code": "PHYSICS_PARAMS_REQUIRED",
            "message": "At least one physics parameter is required",
            "applied": False,
        }
    try:
        normalized_gravity = None
        if gravity is not None:
            try:
                gravity_length = len(gravity)
            except TypeError as exc:
                raise ValueError("gravity must contain exactly three finite numbers") from exc
            if isinstance(gravity, (str, bytes)) or gravity_length != 3:
                raise ValueError("gravity must contain exactly three finite numbers")
            normalized_gravity = []
            for value in gravity:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("gravity must contain exactly three finite numbers")
                normalized_gravity.append(float(value))
        normalized_time_step = None
        if time_step is not None:
            if isinstance(time_step, bool) or not isinstance(time_step, (int, float)) or not math.isfinite(time_step):
                raise ValueError("time_step must be a finite number in seconds")
            normalized_time_step = float(time_step)
            if not 1.0 / 10000.0 <= normalized_time_step <= 1.0:
                raise ValueError("time_step must be within [0.0001, 1.0] seconds")
            steps_per_second = int(round(1.0 / normalized_time_step))
            effective_time_step = 1.0 / steps_per_second
            if not math.isclose(normalized_time_step, effective_time_step, rel_tol=5e-6, abs_tol=1e-9):
                raise ValueError(
                    "time_step must map to an integer PhysX steps-per-second value; "
                    f"nearest supported value is {effective_time_step}"
                )
        if gpu_enabled is not None:
            if not isinstance(gpu_enabled, bool):
                raise ValueError("gpu_enabled must be a boolean")

        state = adapter.get_simulation_state()
        if state.get("timeline_state") != "stopped":
            return {
                "status": "error",
                "code": "TIMELINE_NOT_STOPPED",
                "message": "Stop the simulation before changing physics scene parameters",
                "applied": False,
            }
        result = adapter.configure_physics(
            gravity=normalized_gravity,
            time_step=normalized_time_step,
            gpu_enabled=gpu_enabled,
        )
        return {
            "status": "success",
            "code": "PHYSICS_PARAMS_APPLIED",
            "message": f"Physics parameters updated: {result['applied']}",
            "data": result,
            "readback": result.get("readback"),
        }
    except NotImplementedError as exc:
        return {
            "status": "unsupported",
            "code": "PHYSICS_PARAMS_UNSUPPORTED",
            "message": str(exc),
            "applied": False,
        }
    except PhysicsParamsApplyError as exc:
        return {
            "status": "error" if exc.rollback_succeeded else "partial",
            "code": "PHYSICS_PARAMS_APPLY_FAILED" if exc.rollback_succeeded else "PHYSICS_PARAMS_ROLLBACK_FAILED",
            "message": str(exc),
            "applied": False if exc.rollback_succeeded else None,
            "rollback_succeeded": exc.rollback_succeeded,
        }
    except ValueError as exc:
        return {
            "status": "error",
            "code": "INVALID_PHYSICS_PARAMS",
            "message": str(exc),
            "applied": False,
        }
    except Exception as e:
        return {
            "status": "error",
            "code": "PHYSICS_PARAMS_FAILED",
            "message": str(e),
            "applied": False,
        }


def execute_script(
    adapter: IsaacAdapterBase,
    code: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    max_output_bytes: Optional[int] = None,
    allow_background: bool = False,
) -> Dict[str, Any]:
    started = time.perf_counter()
    outcome = "rejected"
    details: Dict[str, Any] = {}
    try:
        policy = SCRIPT_POLICY.policy
        if not policy.enabled:
            return {
                "status": "error",
                "code": "SCRIPT_EXECUTION_DISABLED",
                "message": "execute_script is disabled by extension policy; use a named tool",
                "applied": False,
            }
        if not code:
            return {"status": "error", "code": "SCRIPT_CODE_REQUIRED", "message": "code is required"}
        SCRIPT_POLICY.validate_code(code, allow_background=allow_background)
        resolved_cwd = SCRIPT_POLICY.require_path(cwd, "cwd") if cwd else None
        timeout, output_limit = SCRIPT_POLICY.resolve_limits(timeout_s, max_output_bytes)
        details = {
            "cwd": resolved_cwd,
            "timeout_s": timeout,
            "max_output_bytes": output_limit,
            "allow_background": allow_background,
        }
        result = adapter.execute_script(
            code,
            cwd=resolved_cwd,
            timeout_s=timeout,
            max_output_bytes=output_limit,
        )
        outcome = str(result.get("status", "error"))
        details["stdout_bytes"] = len(str(result.get("stdout", "")).encode("utf-8"))
        details["stderr_bytes"] = len(str(result.get("stderr", "")).encode("utf-8"))
        return {"status": "success", **result, "policy": details}
    except PermissionError as exc:
        return {"status": "error", "code": "SCRIPT_POLICY_DENIED", "message": str(exc), "applied": False}
    except (ValueError, SyntaxError) as exc:
        return {"status": "error", "code": "INVALID_SCRIPT_REQUEST", "message": str(exc), "applied": False}
    except Exception as e:
        outcome = "error"
        return {"status": "error", "code": "SCRIPT_EXECUTION_FAILED", "message": str(e)}
    finally:
        SCRIPT_POLICY.record(operation="execute_script", target=code or "", outcome=outcome, started=started, details=details)


def get_script_policy() -> Dict[str, Any]:
    return {
        "status": "success",
        "code": "SCRIPT_POLICY",
        "message": "Script escape-hatch policy",
        "data": SCRIPT_POLICY.policy.as_dict(),
    }


def get_script_audit(count: int = 50) -> Dict[str, Any]:
    try:
        records = SCRIPT_POLICY.audit(count)
        return {
            "status": "success",
            "code": "SCRIPT_AUDIT",
            "message": f"Returned {len(records)} bounded audit records",
            "data": {"records": records, "count": len(records)},
        }
    except (TypeError, ValueError) as exc:
        return {"status": "error", "code": "INVALID_AUDIT_QUERY", "message": str(exc)}


def get_simulation_state(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    try:
        result = adapter.get_simulation_state()
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_physics_state_handler(adapter: IsaacAdapterBase, prim_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not prim_path:
            return {"status": "error", "message": "prim_path is required"}
        result = adapter.get_physics_state(prim_path)
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_joint_config_handler(adapter: IsaacAdapterBase, prim_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not prim_path:
            return {"status": "error", "message": "prim_path is required"}
        result = adapter.get_joint_config(prim_path)
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def reload_script_handler(
    adapter: IsaacAdapterBase,
    file_path: Optional[str] = None,
    module_name: Optional[str] = None,
    timeout_s: Optional[float] = None,
    max_output_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    outcome = "rejected"
    details: Dict[str, Any] = {}
    try:
        if not SCRIPT_POLICY.policy.enabled:
            return {
                "status": "error",
                "code": "SCRIPT_EXECUTION_DISABLED",
                "message": "reload_script is disabled by extension policy; use a named tool",
                "applied": False,
            }
        if not file_path:
            return {"status": "error", "code": "SCRIPT_FILE_REQUIRED", "message": "file_path is required"}
        resolved_path = SCRIPT_POLICY.require_path(file_path, "file_path", require_file=True)
        timeout, output_limit = SCRIPT_POLICY.resolve_limits(timeout_s, max_output_bytes)
        details = {"file_path": resolved_path, "timeout_s": timeout, "max_output_bytes": output_limit}
        result = adapter.reload_script(
            resolved_path,
            module_name=module_name,
            timeout_s=timeout,
            max_output_bytes=output_limit,
        )
        outcome = str(result.get("status", "error"))
        details["stdout_bytes"] = len(str(result.get("stdout", "")).encode("utf-8"))
        details["stderr_bytes"] = len(str(result.get("stderr", "")).encode("utf-8"))
        return {"status": "success", **result, "policy": details}
    except PermissionError as exc:
        return {"status": "error", "code": "SCRIPT_POLICY_DENIED", "message": str(exc), "applied": False}
    except (ValueError, FileNotFoundError) as exc:
        return {"status": "error", "code": "INVALID_SCRIPT_REQUEST", "message": str(exc), "applied": False}
    except Exception as e:
        outcome = "error"
        return {"status": "error", "code": "SCRIPT_RELOAD_FAILED", "message": str(e)}
    finally:
        SCRIPT_POLICY.record(
            operation="reload_script", target=file_path or "", outcome=outcome, started=started, details=details
        )


# ── Log buffer for get_logs ───────────────────────────────────────────────────

# _log_buffer holds only [PRINT] output captured from execute_script /
# reload_script. WARN/ERROR come from Kit's own log file (see get_kit_log_path)
# — never from a Python log consumer, which deadlocks physics loads.
_log_buffer: list = []
_log_listener_active: bool = False
_play_boundary: int = 0
_MAX_LOG_BUFFER = 500
# Path of Kit's session log file: None = not resolved yet, "" = unavailable.
_kit_log_path: Optional[str] = None
# Byte offset into that file at the last timeline Play.
_kit_log_play_offset: int = 0


def append_log(entry: str) -> None:
    """Append an entry to the shared log buffer, trimming to the cap."""
    _log_buffer.append(entry)
    if len(_log_buffer) > _MAX_LOG_BUFFER:
        # Keep the boundary consistent when we drop from the front.
        global _play_boundary
        _log_buffer.pop(0)
        if _play_boundary > 0:
            _play_boundary -= 1


def mark_play_boundary() -> None:
    """Record the run boundary at the current timeline Play.

    Two positions: the [PRINT] buffer index, and the byte offset into Kit's log
    file, so `since_last_play` scopes both sources to the current run.
    """
    global _play_boundary, _kit_log_play_offset
    _play_boundary = len(_log_buffer)
    path = get_kit_log_path()
    if path:
        try:
            _kit_log_play_offset = os.path.getsize(path)
        except Exception:
            pass


def _select_logs(buffer: list, boundary: int, since_last_play: bool, count: int) -> list:
    """Pure selector: entries after the Play boundary (optional), capped to count."""
    scoped = buffer[boundary:] if since_last_play else buffer
    return scoped[-count:]


def get_kit_log_path() -> Optional[str]:
    """Absolute path of the log file Kit is writing this session, or None.

    Kit publishes it in the `/log/file` setting; fall back to the newest
    kit_*.log under the Omniverse logs tree.
    """
    global _kit_log_path
    if _kit_log_path is not None:
        return _kit_log_path or None
    path = None
    try:
        import carb

        value = carb.settings.get_settings().get("/log/file")
        if value and os.path.isfile(value):
            path = value
    except Exception:
        pass
    if path is None:
        try:
            candidates = glob.glob(os.path.expanduser("~/.nvidia-omniverse/logs/Kit/*/*/kit_*.log"))
            if candidates:
                path = max(candidates, key=os.path.getmtime)
        except Exception:
            path = None
    _kit_log_path = path or ""
    return path


def _ensure_log_listener():
    """Prepare log capture. Deliberately does NOT install a Python log consumer.

    A `carb`/`omni.log` message consumer is a Python callback that Kit invokes
    on whatever thread emitted the message. During a physics load
    (SingleArticulation.initialize() / World.initialize_physics()) omni.physx
    emits warnings from native TBB worker threads while the calling thread holds
    the GIL inside the native call — the worker blocks acquiring the GIL, the
    load never completes, and kit deadlocks permanently (reproduced on Isaac Sim
    5.1: spawning a Franka FR3, which emits invalid-inertia warnings, wedges kit
    forever with a Python consumer installed).

    Kit already writes every WARN/ERROR to its own log file starting at [0ms] —
    earlier than this extension can load, and it survives a crash or freeze — so
    get_logs reads that file instead. Startup-crash diagnostics are strictly
    better this way; nothing is captured on a live callback.
    """
    global _log_listener_active
    if _log_listener_active:
        return
    get_kit_log_path()
    _log_listener_active = True


def _read_kit_log_warnings(since_offset: int, count: int) -> Tuple[list, int]:
    """Return (WARN/ERROR lines from the kit log after `since_offset`, new offset)."""
    path = get_kit_log_path()
    if not path:
        return [], since_offset
    try:
        size = os.path.getsize(path)
        start = since_offset if 0 <= since_offset <= size else 0
        with open(path, "r", errors="replace") as f:
            f.seek(start)
            chunk = f.read()
            new_offset = f.tell()
    except Exception:
        return [], since_offset
    entries = [ln.rstrip("\n") for ln in chunk.splitlines() if ("[Warning]" in ln or "[Error]" in ln)]
    return entries[-count:], new_offset


def get_logs(
    adapter: IsaacAdapterBase, clear: bool = False, count: int = 100, since_last_play: bool = True
) -> Dict[str, Any]:
    """Return recent WARN/ERROR + [PRINT] log messages, scoped to the current run.

    WARN/ERROR are read from Kit's own session log file (covers everything from
    [0ms], survives a crash); [PRINT] comes from the captured stdout buffer.
    """
    try:
        global _kit_log_play_offset
        _ensure_log_listener()
        prints = _select_logs(_log_buffer, _play_boundary, since_last_play, count)
        warnings, _ = _read_kit_log_warnings(_kit_log_play_offset if since_last_play else 0, count)
        logs = (warnings + prints)[-count:]
        if clear:
            _log_buffer.clear()
            mark_play_boundary()
        return {
            "status": "success",
            "log_count": len(logs),
            "logs": logs,
            "kit_log_file": get_kit_log_path(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
