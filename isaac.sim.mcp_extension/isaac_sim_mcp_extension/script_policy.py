"""Policy and bounded audit records for execute_script and reload_script."""

from __future__ import annotations

import ast
import hashlib
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, Optional

from .command_governance import current_command_id

_BACKGROUND_CALLS = {
    "asyncio.create_task",
    "asyncio.ensure_future",
    "omni.kit.async_engine.run_coroutine",
    "threading.Thread",
    "threading.Timer",
    "multiprocessing.Process",
    "subprocess.Popen",
}
_BACKGROUND_METHODS = {
    "add_update_callback",
    "create_subscription_to_pop",
    "create_subscription_to_pop_by_type",
    "create_subscription_to_push",
    "ensure_future",
    "run_coroutine",
}
_BACKGROUND_MODULES = {"asyncio", "threading", "multiprocessing", "subprocess"}
_BACKGROUND_EXACT_MODULES = {"omni.kit.async_engine"}


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dotted_name(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


@dataclass(frozen=True)
class ScriptPolicy:
    enabled: bool
    allowed_roots: tuple[str, ...]
    default_timeout_s: float
    max_timeout_s: float
    default_output_bytes: int
    max_output_bytes: int
    max_code_bytes: int
    allow_background: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allowed_roots": list(self.allowed_roots),
            "default_timeout_s": self.default_timeout_s,
            "max_timeout_s": self.max_timeout_s,
            "default_output_bytes": self.default_output_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_code_bytes": self.max_code_bytes,
            "allow_background": self.allow_background,
            "timeout_mode": "cooperative_python_trace",
            "named_tools_preferred": True,
        }


class ScriptPolicyManager:
    def __init__(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.policy = ScriptPolicy(True, (str(repo_root),), 30.0, 300.0, 65536, 1048576, 262144, False)
        self._audit: deque[Dict[str, Any]] = deque(maxlen=256)

    def configure(self, settings: Any = None) -> None:
        def setting(name: str, default: Any) -> Any:
            env_name = "ISAAC_MCP_SCRIPT_" + name.upper()
            if env_name in os.environ:
                return os.environ[env_name]
            if settings is not None:
                try:
                    value = settings.get(f"/exts/isaac.sim.mcp/server.script.{name}")
                    if value is not None:
                        return value
                except Exception:
                    pass
            return default

        roots_raw = str(setting("allowed_roots", os.pathsep.join(self.policy.allowed_roots)))
        roots = tuple(
            str(Path(item).expanduser().resolve()) for item in roots_raw.split(os.pathsep) if item.strip()
        )
        self.policy = ScriptPolicy(
            enabled=_bool(setting("enabled", True), True),
            allowed_roots=roots,
            default_timeout_s=float(setting("default_timeout_s", 30.0)),
            max_timeout_s=float(setting("max_timeout_s", 300.0)),
            default_output_bytes=int(setting("default_output_bytes", 65536)),
            max_output_bytes=int(setting("max_output_bytes", 1048576)),
            max_code_bytes=int(setting("max_code_bytes", 262144)),
            allow_background=_bool(setting("allow_background", False), False),
        )

    def resolve_limits(self, timeout_s: Optional[float], max_output_bytes: Optional[int]) -> tuple[float, int]:
        timeout = self.policy.default_timeout_s if timeout_s is None else float(timeout_s)
        output = self.policy.default_output_bytes if max_output_bytes is None else int(max_output_bytes)
        if timeout <= 0 or timeout > self.policy.max_timeout_s:
            raise ValueError(f"timeout_s must be within (0, {self.policy.max_timeout_s:g}]")
        if output <= 0 or output > self.policy.max_output_bytes:
            raise ValueError(f"max_output_bytes must be within (0, {self.policy.max_output_bytes}]")
        return timeout, output

    def require_path(self, value: str, field: str, *, require_file: bool = False) -> str:
        if os.name != "nt" and PureWindowsPath(value).is_absolute():
            raise PermissionError(f"{field} is outside allowed_roots")
        resolved = Path(value).expanduser().resolve()
        allowed = any(resolved == Path(root) or Path(root) in resolved.parents for root in self.policy.allowed_roots)
        if not allowed:
            raise PermissionError(f"{field} is outside allowed_roots")
        if require_file and not resolved.is_file():
            raise FileNotFoundError(f"File not found: {resolved}")
        return str(resolved)

    def validate_code(self, code: str, allow_background: bool) -> None:
        if len(code.encode("utf-8")) > self.policy.max_code_bytes:
            raise ValueError(f"code exceeds {self.policy.max_code_bytes} bytes")
        if allow_background and not self.policy.allow_background:
            raise PermissionError("background execution is disabled by policy")
        if allow_background:
            return
        tree = ast.parse(code, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules: Iterable[str]
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if any(
                    module.split(".", 1)[0] in _BACKGROUND_MODULES or module in _BACKGROUND_EXACT_MODULES
                    for module in modules
                ):
                    raise PermissionError("background process/thread imports require allow_background and policy opt-in")
            if isinstance(node, ast.Call):
                call_name = _dotted_name(node.func)
                if call_name in _BACKGROUND_CALLS or call_name.rsplit(".", 1)[-1] in _BACKGROUND_METHODS:
                    raise PermissionError("background scheduling requires allow_background and policy opt-in")

    def record(self, *, operation: str, target: str, outcome: str, started: float, details: Dict[str, Any]) -> None:
        self._audit.append(
            {
                "command_id": current_command_id.get(),
                "timestamp_unix": time.time(),
                "operation": operation,
                "target_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
                "outcome": outcome,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                **details,
            }
        )

    def audit(self, count: int) -> list[Dict[str, Any]]:
        bounded = max(1, min(int(count), 256))
        return list(self._audit)[-bounded:]


SCRIPT_POLICY = ScriptPolicyManager()
