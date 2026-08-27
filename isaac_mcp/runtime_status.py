"""Bounded cross-process status for the supervised Isaac Sim runtime."""

from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from isaac_mcp.responses import normalize_response

STATE_SCHEMA_VERSION = "1.0"
MAX_STATE_BYTES = 64 * 1024
DEFAULT_PROBE_TIMEOUT_SECONDS = 1.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_state_file() -> Path:
    configured = os.getenv("ISAAC_MCP_RUNTIME_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    if os.getenv("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.getenv("XDG_STATE_HOME"):
        base = Path(os.environ["XDG_STATE_HOME"])
    else:
        base = Path.home() / ".local" / "state"
    return base / "IsaacSim-MCP" / "runtime-state.json"


def _probe_timeout() -> float:
    try:
        value = float(os.getenv("ISAAC_MCP_RUNTIME_PROBE_TIMEOUT_SECONDS", DEFAULT_PROBE_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_PROBE_TIMEOUT_SECONDS
    return value if 0 < value <= 30 else DEFAULT_PROBE_TIMEOUT_SECONDS


def probe_runtime_health(*, host: str, port: int, timeout: float | None = None) -> dict[str, Any]:
    """Query the read-only capability command so an open-but-hung port is not considered ready."""
    checked_at = utc_now()
    timeout = timeout if timeout is not None else _probe_timeout()
    command = {
        "type": "system.get_capabilities",
        "params": {},
        "command_id": f"runtime-health-{uuid.uuid4()}",
    }
    port_open = False
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            port_open = True
            connection.settimeout(timeout)
            connection.sendall(json.dumps(command, separators=(",", ":")).encode("utf-8"))
            chunks: list[bytes] = []
            total = 0
            response: Any = None
            while True:
                chunk = connection.recv(16384)
                if not chunk:
                    break
                total += len(chunk)
                if total > 1024 * 1024:
                    raise ValueError("health response exceeds 1048576 bytes")
                chunks.append(chunk)
                try:
                    response = json.loads(b"".join(chunks).decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    continue
            if not chunks:
                raise ConnectionError("runtime closed the health connection without a response")
            if response is None:
                raise ValueError("runtime returned incomplete health JSON")
        responding = isinstance(response, Mapping) and response.get("status") == "success"
        return {
            "responding": responding,
            "port_open": True,
            "checked_at": checked_at,
            "error": None if responding else "capability health response was not successful",
        }
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "responding": False,
            "port_open": port_open,
            "checked_at": checked_at,
            "error": str(exc)[:512],
        }


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "state": "unmanaged",
            "supervised": False,
        }
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError(f"runtime state exceeds {MAX_STATE_BYTES} bytes")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ValueError("runtime state schema is invalid")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "state": "diagnostic_unavailable",
            "supervised": True,
            "diagnostic_error": str(exc)[:512],
        }


def _availability_code(state: str, responding: bool) -> str:
    if responding:
        return "ISAAC_RUNTIME_READY"
    if state in {"starting", "restarting", "restart_backoff"}:
        return "ISAAC_RUNTIME_RECOVERING"
    if state in {"crashed", "recovery_failed"}:
        return "ISAAC_RUNTIME_CRASHED"
    return "ISAAC_RUNTIME_UNAVAILABLE"


def _recommended_actions(code: str, state: str) -> list[str]:
    actions = ["query_get_runtime_status"]
    if code == "ISAAC_RUNTIME_RECOVERING":
        actions.extend(["wait_for_recovery", "retry_read_when_ready"])
    elif code == "ISAAC_RUNTIME_CRASHED":
        actions.extend(["inspect_last_crash", "fix_root_cause", "restart_supervisor"])
    elif code == "ISAAC_RUNTIME_UNAVAILABLE":
        if state in {"unresponsive", "external_runtime_unresponsive"}:
            actions.extend(["inspect_unresponsive_runtime", "do_not_start_second_runtime"])
        else:
            actions.append("start_supervised_isaac_runtime")
    actions.append("do_not_replay_write")
    return actions


def get_runtime_status(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    state_file: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Combine supervisor evidence with a bounded protocol-level health probe."""
    effective_port = port or int(os.getenv("ISAAC_MCP_PORT", "8766"))
    path = Path(state_file) if state_file is not None else default_state_file()
    state = _read_state(path)
    health = probe_runtime_health(host=host, port=effective_port)
    responding = bool(health.get("responding"))
    if responding:
        state["state"] = "ready"
    elif state.get("state") == "ready":
        state["state"] = "unresponsive"
    state["runtime_responding"] = responding
    state["health"] = health
    state["host"] = host
    state["port"] = effective_port
    state["availability_code"] = _availability_code(str(state.get("state", "unmanaged")), responding)
    state["recommended_actions"] = _recommended_actions(state["availability_code"], str(state["state"]))
    return state


def runtime_unavailable_response(status: Mapping[str, Any], *, command_id: str | None = None) -> dict[str, Any]:
    code = str(status.get("availability_code", "ISAAC_RUNTIME_UNAVAILABLE"))
    state = str(status.get("state", "unmanaged"))
    message = {
        "ISAAC_RUNTIME_RECOVERING": f"Isaac Sim is recovering under the runtime supervisor (state: {state})",
        "ISAAC_RUNTIME_CRASHED": f"Isaac Sim exited unexpectedly and automatic recovery is unavailable (state: {state})",
    }.get(
        code,
        (
            "Isaac Sim or its runtime port exists but did not answer protocol health; do not start a second runtime"
            if state in {"unresponsive", "external_runtime_unresponsive"}
            else "Isaac Sim is not available; start the supervised runtime launcher"
        ),
    )
    return normalize_response(
        {
            "status": "error",
            "code": code,
            "message": message,
            "data": {"runtime": dict(status)},
            "warnings": [
                "The failed command was not replayed; read back state after recovery before retrying a write."
            ],
            "readback": {"required": True, "completed": False},
        },
        command_id=command_id,
    )


class IsaacRuntimeUnavailableError(ConnectionError):
    """Carries a stable MCP response when the extension runtime cannot be reached."""

    def __init__(self, status: Mapping[str, Any], *, command_id: str | None = None):
        self.status = dict(status)
        self.command_id = command_id
        super().__init__(runtime_unavailable_response(self.status, command_id=command_id)["message"])

    def to_response(self) -> dict[str, Any]:
        return runtime_unavailable_response(self.status, command_id=self.command_id)
