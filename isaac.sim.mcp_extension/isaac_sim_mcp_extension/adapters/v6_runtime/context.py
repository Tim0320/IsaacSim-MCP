"""Shared, dynamically resolved Isaac Sim 6 runtime facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..version import version_string


@dataclass(frozen=True)
class RuntimeContext:
    """Expose shared V6 runtime facts without caching live Stage/backend state."""

    isaac_version: str

    @classmethod
    def from_runtime(cls) -> "RuntimeContext":
        """Build the context from the active Isaac Sim runtime."""
        try:
            from isaacsim.core.version import get_version

            # Isaac Sim 6 returns an 8-tuple; version_string owns that duality.
            isaac_version = version_string(get_version())
        except Exception:
            isaac_version = "unknown"
        return cls(isaac_version=isaac_version)

    @property
    def active_backend(self) -> str:
        """Read the active physics backend on every access."""
        try:
            from isaacsim.core.simulation_manager import SimulationManager

            return SimulationManager.get_active_physics_engine()
        except Exception:
            return "unknown"

    def get_stage(self) -> Any:
        """Return the current USD Stage without caching it across Stage changes."""
        import omni.usd

        return omni.usd.get_context().get_stage()
