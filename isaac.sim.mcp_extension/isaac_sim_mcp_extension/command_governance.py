"""Command correlation, write classification, and bounded idempotency replay."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

current_command_id: ContextVar[Optional[str]] = ContextVar("isaac_sim_mcp_command_id", default=None)

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_READ_ACTION_PREFIXES = ("get", "list", "read", "observe", "resolve", "validate")
_READ_ACTIONS = {"status", "capabilities"}


def validate_command_id(value: Any) -> str:
    command_id = str(value or "").strip()
    if not command_id or len(command_id) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in command_id):
        raise ValueError("command_id must be 1..128 printable ASCII characters")
    return command_id


def validate_idempotency_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    key = str(value).strip()
    if not _KEY_RE.fullmatch(key):
        raise ValueError(
            "idempotency_key must be 1..128 characters and use only letters, digits, '.', '_', ':', or '-'"
        )
    return key


def is_write_command(command_type: str) -> bool:
    """Conservatively classify commands that can mutate stage or runtime state."""
    action = command_type.rsplit(".", 1)[-1].lower()
    if action in _READ_ACTIONS or action.startswith(_READ_ACTION_PREFIXES):
        return False
    return True


def request_fingerprint(command_type: str, params: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"type": command_type, "params": params},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=repr,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def attach_command_metadata(
    response: Dict[str, Any],
    *,
    command_type: str,
    request_params: Optional[Mapping[str, Any]] = None,
    idempotency_key: Optional[str],
    replayed: bool,
    original_command_id: Optional[str] = None,
) -> Dict[str, Any]:
    result = copy.deepcopy(response)
    data = result.get("data")
    if not isinstance(data, dict):
        data = {"value": data}
        result["data"] = data
    readback = result.get("readback")
    if readback is None and isinstance(data.get("readback"), Mapping):
        readback = data["readback"]
    status = str(result.get("status", "error"))
    write = is_write_command(command_type)
    preview = status == "success" and write and (
        bool((request_params or {}).get("preview")) or data.get("preview") is True
    )
    lifecycle = {
        "type": command_type,
        "write": write,
        "apply_state": (
            "not_applicable"
            if not write
            else "preview"
            if preview
            else "applied"
            if status == "success"
            else "partial"
            if status == "partial"
            else "not_applied"
            if status in {"error", "unsupported", "timeout", "cancelled"}
            else "unknown"
        ),
        "readback_state": "verified" if readback is not None else "not_reported",
        "idempotency_key": idempotency_key,
        "replayed": replayed,
    }
    if original_command_id is not None:
        lifecycle["original_command_id"] = original_command_id
    data["command"] = lifecycle
    return result


@dataclass
class _Entry:
    fingerprint: str
    response: Dict[str, Any]
    command_id: str
    stored_at: float


class IdempotencyLedger:
    """Small in-memory replay ledger scoped to one running Kit extension."""

    def __init__(self, max_entries: int = 256, ttl_seconds: float = 600.0) -> None:
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if now - entry.stored_at > self.ttl_seconds]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def lookup(self, key: str, fingerprint: str) -> Tuple[str, Optional[_Entry]]:
        now = time.monotonic()
        self._prune(now)
        entry = self._entries.get(key)
        if entry is None:
            return "miss", None
        self._entries.move_to_end(key)
        if entry.fingerprint != fingerprint:
            return "conflict", entry
        return "replay", entry

    def store(self, key: str, fingerprint: str, response: Dict[str, Any], command_id: str) -> None:
        self._entries[key] = _Entry(
            fingerprint=fingerprint,
            response=copy.deepcopy(response),
            command_id=command_id,
            stored_at=time.monotonic(),
        )
        self._entries.move_to_end(key)
        self._prune(time.monotonic())
