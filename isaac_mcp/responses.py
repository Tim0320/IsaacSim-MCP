# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Stable response envelopes shared by every MCP tool."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Mapping, Optional

SCHEMA_VERSION = "1.0"
STATUSES = {"success", "error", "partial", "unsupported", "timeout", "cancelled"}
_CONTROL_FIELDS = {
    "schema_version",
    "status",
    "code",
    "message",
    "data",
    "warnings",
    "command_id",
    "timing",
    "artifacts",
    "readback",
}
_DEFAULT_CODES = {
    "success": "OK",
    "error": "COMMAND_FAILED",
    "partial": "PARTIAL_SUCCESS",
    "unsupported": "UNSUPPORTED",
    "timeout": "TIMEOUT",
    "cancelled": "CANCELLED",
}


def new_command_id() -> str:
    """Return an opaque correlation ID suitable for logs and retries."""
    return str(uuid.uuid4())


def is_envelope(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        key in value
        for key in (
            "schema_version",
            "status",
            "code",
            "message",
            "data",
            "warnings",
            "command_id",
            "timing",
            "artifacts",
            "readback",
        )
    )


def _legacy_status(payload: Mapping[str, Any]) -> str:
    status = str(payload.get("status", "success")).lower()
    if status in STATUSES and status != "error":
        return status

    message = str(payload.get("message", "")).lower()
    unsupported = payload.get("unsupported")
    if unsupported:
        return "partial" if payload.get("applied") else "unsupported"
    if "not supported" in message or "unsupported" in message:
        return "unsupported"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "cancelled" in message or "canceled" in message:
        return "cancelled"
    return "error" if status == "error" else "success"


def normalize_response(
    value: Any,
    *,
    command_id: Optional[str] = None,
    timing: Optional[Mapping[str, Any]] = None,
    default_code: Optional[str] = None,
    default_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert current envelopes and legacy tool results to schema 1.0."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {"status": "success", "data": {"value": value}}
    if not isinstance(value, Mapping):
        value = {"status": "success", "data": value}

    status = _legacy_status(value)
    data = value.get("data")
    if data is None:
        data = {key: item for key, item in value.items() if key not in _CONTROL_FIELDS}

    merged_timing = dict(value.get("timing") or {})
    if timing:
        merged_timing.update(timing)

    message = value.get("message")
    if not message:
        message = default_message or ("Command completed" if status == "success" else "Command did not complete")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "code": str(value.get("code") or default_code or _DEFAULT_CODES[status]),
        "message": str(message),
        "data": data,
        "warnings": list(value.get("warnings") or []),
        "command_id": str(value.get("command_id") or command_id or new_command_id()),
        "timing": merged_timing,
        "artifacts": list(value.get("artifacts") or []),
        "readback": value.get("readback"),
    }


def dumps_response(value: Any, **kwargs: Any) -> str:
    """Serialize a normalized envelope for MCP text responses."""
    return json.dumps(normalize_response(value, **kwargs), indent=2, sort_keys=True)
