"""Fail-closed helpers for destructive Isaac Sim live tests.

The harness never creates or replaces a stage.  A caller must first open a
dedicated scratch USD and then provide its exact path through the environment.
This prevents an apparently empty user stage from being treated as disposable.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRATCH_CONFIRMATION = "I_UNDERSTAND_THIS_CLEARS_THE_STAGE"
_NAMESPACE_RE = re.compile(r"^/World/MCP_Live_[0-9a-f]{32}$")


class ScratchStageGuardError(RuntimeError):
    """Raised before any write when a live stage is not proven disposable."""


def _response_data(response: dict[str, Any], command: str) -> dict[str, Any]:
    if response.get("status") != "success":
        raise ScratchStageGuardError(f"{command} read-back failed: {response}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ScratchStageGuardError(f"{command} returned no data object")
    return data


def _resolved(path: str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _require_prim_absent(response: dict[str, Any], prim_path: str) -> None:
    """Distinguish an exact not-found read-back from transport/handler failure."""
    message = str(response.get("message") or "")
    if (
        response.get("status") == "error"
        and response.get("code") in {"COMMAND_FAILED", "PRIM_NOT_FOUND"}
        and f"Prim not found: {prim_path}" in message
    ):
        return
    raise ScratchStageGuardError(f"could not prove prim absent at {prim_path}: {response}")


@dataclass(frozen=True)
class ScratchRun:
    """Validated stage identity and a unique prim namespace for one live run."""

    stage_path: Path
    scratch_root: Path
    namespace: str

    @classmethod
    def validate(
        cls,
        connection: Any,
        *,
        expected_stage_path: str,
        scratch_root: str,
        run_id: str | None = None,
    ) -> "ScratchRun":
        expected = _resolved(expected_stage_path)
        root = _resolved(scratch_root)
        if expected.suffix.lower() not in {".usd", ".usda", ".usdc"}:
            raise ScratchStageGuardError("scratch stage must be a .usd, .usda, or .usdc file")
        try:
            expected.relative_to(root)
        except ValueError as exc:
            raise ScratchStageGuardError("scratch stage path is outside ISAAC_MCP_SCRATCH_ROOT") from exc

        scene = _response_data(connection.send_command("scene.get_info"), "scene.get_info")
        actual_raw = str(scene.get("stage_path") or "")
        if not actual_raw:
            raise ScratchStageGuardError("connected Isaac Sim stage is anonymous; an exact scratch file is required")
        actual = _resolved(actual_raw)
        if os.path.normcase(str(actual)) != os.path.normcase(str(expected)):
            raise ScratchStageGuardError(f"connected stage {actual} does not match declared scratch stage {expected}")

        simulation = _response_data(connection.send_command("simulation.get_state"), "simulation.get_state")
        if simulation.get("timeline_state") != "stopped":
            raise ScratchStageGuardError("timeline must be stopped before scratch live tests")

        token = (run_id or uuid.uuid4().hex).lower()
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ScratchStageGuardError("run_id must contain exactly 32 lowercase hexadecimal characters")
        namespace = f"/World/MCP_Live_{token}"
        if not _NAMESPACE_RE.fullmatch(namespace):
            raise ScratchStageGuardError("invalid scratch prim namespace")

        existing = connection.send_command("scene.get_prim_info", {"prim_path": namespace})
        if existing.get("status") == "success":
            raise ScratchStageGuardError(f"scratch namespace already exists: {namespace}")
        _require_prim_absent(existing, namespace)
        return cls(stage_path=actual, scratch_root=root, namespace=namespace)

    def cleanup(self, connection: Any) -> dict[str, Any]:
        """Delete only this run's root and prove it is absent afterward."""
        before = connection.send_command("scene.get_prim_info", {"prim_path": self.namespace})
        if before.get("status") == "success":
            deleted = connection.send_command("objects.delete", {"prim_path": self.namespace})
            if deleted.get("status") != "success":
                raise ScratchStageGuardError(f"scratch cleanup failed: {deleted}")
        after = connection.send_command("scene.get_prim_info", {"prim_path": self.namespace})
        _require_prim_absent(after, self.namespace)
        return {"namespace": self.namespace, "prim_absent": True}


def require_legacy_clear_stage(connection: Any) -> ScratchRun:
    """Apply the strongest guard available to the historical clear-scene suite."""
    if os.environ.get("ISAAC_MCP_ALLOW_LEGACY_CLEAR_SCENE") != SCRATCH_CONFIRMATION:
        raise ScratchStageGuardError(
            "legacy integration is disabled; set the exact ISAAC_MCP_ALLOW_LEGACY_CLEAR_SCENE confirmation"
        )
    stage_path = os.environ.get("ISAAC_MCP_SCRATCH_STAGE_PATH", "")
    scratch_root = os.environ.get("ISAAC_MCP_SCRATCH_ROOT", "")
    if not stage_path or not scratch_root:
        raise ScratchStageGuardError("ISAAC_MCP_SCRATCH_STAGE_PATH and ISAAC_MCP_SCRATCH_ROOT are required")
    return ScratchRun.validate(connection, expected_stage_path=stage_path, scratch_root=scratch_root)
