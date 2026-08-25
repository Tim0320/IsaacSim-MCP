"""Per-tool command metadata forwarded to the Isaac Sim extension."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

command_id_var: ContextVar[Optional[str]] = ContextVar("isaac_mcp_command_id", default=None)
idempotency_key_var: ContextVar[Optional[str]] = ContextVar("isaac_mcp_idempotency_key", default=None)
