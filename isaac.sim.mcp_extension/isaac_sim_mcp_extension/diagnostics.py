"""Bounded, redacted, command-correlated diagnostics for the Kit process."""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from typing import Any, Deque, Dict, Iterable, Optional

MAX_RECORDS = 1000
MAX_MESSAGE_BYTES = 8192
MAX_QUERY_COUNT = 200
MAX_QUERY_BYTES = 262144

_RECORDS: Deque[Dict[str, Any]] = deque(maxlen=MAX_RECORDS)
_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|authorization|password|secret|token|credential)")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token|credential)\b(\s*[:=]\s*)([^\s,;]+)"
)


def redact(value: Any) -> Any:
    """Recursively redact common credential fields and inline secret forms."""
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = _BEARER.sub(r"\1[REDACTED]", value)
        return _ASSIGNMENT.sub(r"\1\2[REDACTED]", text)
    return value


def _bounded_text(value: Any) -> str:
    text = str(redact(value))
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= MAX_MESSAGE_BYTES:
        return text
    suffix = "... [truncated]"
    keep = MAX_MESSAGE_BYTES - len(suffix.encode("utf-8"))
    return raw[:keep].decode("utf-8", errors="ignore") + suffix


def record(
    message: Any,
    *,
    severity: str = "info",
    source: str = "extension",
    command_id: Optional[str] = None,
    command_type: Optional[str] = None,
    frame: Optional[int] = None,
    backend: Optional[str] = None,
    extension: str = "isaac.sim.mcp",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry = {
        "timestamp": time.time(),
        "severity": str(severity).lower(),
        "source": str(source),
        "message": _bounded_text(message),
        "command_id": command_id,
        "command_type": command_type,
        "stage": _stage_identifier(),
        "frame": frame,
        "backend": backend,
        "extension": extension,
    }
    if details:
        entry["details"] = redact(details)
    _RECORDS.append(entry)
    return dict(entry)


def _stage_identifier() -> Optional[str]:
    try:
        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return None
        layer = stage.GetRootLayer()
        return str(layer.identifier) if layer else None
    except Exception:
        return None


def kit_log_offset() -> int:
    try:
        from .handlers.simulation import get_kit_log_path

        path = get_kit_log_path()
        return os.path.getsize(path) if path else 0
    except Exception:
        return 0


def capture_kit_messages(
    offset: int, *, command_id: str, command_type: str
) -> None:
    """Attach Kit warning/error lines emitted during one command window."""
    try:
        from .handlers.simulation import get_kit_log_path

        path = get_kit_log_path()
        if not path:
            return
        size = os.path.getsize(path)
        start = offset if 0 <= offset <= size else size
        with open(path, "r", errors="replace") as stream:
            stream.seek(start)
            lines = stream.read(MAX_QUERY_BYTES).splitlines()
        for line in lines[-MAX_QUERY_COUNT:]:
            lowered = line.lower()
            if "[error]" in lowered:
                severity = "error"
            elif "[warning]" in lowered:
                severity = "warning"
            else:
                continue
            record(line, severity=severity, source="kit", command_id=command_id, command_type=command_type)
    except Exception:
        return


def query(
    *,
    count: int = 100,
    command_id: Optional[str] = None,
    severity: Optional[str] = None,
    source: Optional[str] = None,
) -> list[Dict[str, Any]]:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_QUERY_COUNT:
        raise ValueError(f"count must be an integer from 1 through {MAX_QUERY_COUNT}")
    records: Iterable[Dict[str, Any]] = _RECORDS
    if command_id:
        records = (item for item in records if item.get("command_id") == command_id)
    if severity:
        wanted = str(severity).lower()
        records = (item for item in records if item.get("severity") == wanted)
    if source:
        wanted_source = str(source).lower()
        records = (item for item in records if str(item.get("source", "")).lower() == wanted_source)
    selected = list(records)[-count:]
    bounded: list[Dict[str, Any]] = []
    used = 0
    for item in reversed(selected):
        size = len(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8"))
        if used + size > MAX_QUERY_BYTES:
            break
        bounded.append(dict(item))
        used += size
    return list(reversed(bounded))


def clear() -> None:
    _RECORDS.clear()
