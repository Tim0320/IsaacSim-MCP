"""High-level gripper and mobile-base MCP tools with explicit profiles."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    def send(command: str, params: dict | None = None) -> str:
        return json.dumps(get_connection().send_command(command, params or {}), indent=2)

    @mcp.tool("list_controller_profiles")
    def list_controller_profiles() -> str:
        """List the exact gripper and mobile-base profiles accepted by high-level controller tools."""
        return send("controllers.list_profiles")

    @mcp.tool("set_gripper_width")
    def set_gripper_width(prim_path: str, profile: str, width_m: float) -> str:
        """Set total gripper opening width using an explicit robot profile.

        The profile validates exact joint names and types before applying any
        position target. width_m is the total distance between both fingers.
        """
        return send(
            "controllers.set_gripper_width",
            {
                "prim_path": prim_path,
                "profile": profile,
                "width_m": width_m,
            },
        )

    @mcp.tool("open_gripper")
    def open_gripper(prim_path: str, profile: str) -> str:
        """Open a gripper to the profile's declared open width with immediate target read-back."""
        return send(
            "controllers.open_gripper",
            {
                "prim_path": prim_path,
                "profile": profile,
            },
        )

    @mcp.tool("close_gripper")
    def close_gripper(prim_path: str, profile: str) -> str:
        """Close a gripper to the profile's declared closed width with immediate target read-back."""
        return send(
            "controllers.close_gripper",
            {
                "prim_path": prim_path,
                "profile": profile,
            },
        )

    @mcp.tool("set_mobile_base_velocity")
    def set_mobile_base_velocity(
        prim_path: str,
        profile: str,
        forward_mps: float,
        lateral_mps: float = 0.0,
        yaw_radps: float = 0.0,
    ) -> str:
        """Apply a profiled differential or holonomic base velocity target.

        The timeline must be playing for a non-zero command. Targets persist
        until replaced, so always call stop_mobile_base at the end of motion.
        Differential profiles reject non-zero lateral velocity.
        """
        return send(
            "controllers.set_mobile_base_velocity",
            {
                "prim_path": prim_path,
                "profile": profile,
                "forward_mps": forward_mps,
                "lateral_mps": lateral_mps,
                "yaw_radps": yaw_radps,
            },
        )

    @mcp.tool("stop_mobile_base")
    def stop_mobile_base(prim_path: str, profile: str) -> str:
        """Set every profiled wheel velocity target to zero and verify the stop target read-back."""
        return send(
            "controllers.stop_mobile_base",
            {
                "prim_path": prim_path,
                "profile": profile,
            },
        )
