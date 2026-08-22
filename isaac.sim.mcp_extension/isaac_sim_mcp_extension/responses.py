# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Response envelope normalization inside the Isaac Sim Kit process."""

from __future__ import annotations

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
    return str(uuid.uuid4())


def normalize_response(
    value: Any,
    *,
    command_id: Optional[str] = None,
    timing: Optional[Mapping[str, Any]] = None,
    default_code: Optional[str] = None,
    default_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap legacy handler dictionaries in the stable schema 1.0 envelope."""
    if not isinstance(value, Mapping):
        value = {"status": "error", "message": "Handler returned no structured result", "data": value}

    status = str(value.get("status", "success")).lower()
    if status not in STATUSES:
        status = "error"
    if status == "error" and value.get("unsupported"):
        status = "partial" if value.get("applied") else "unsupported"

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
