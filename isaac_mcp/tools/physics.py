"""Typed physics authoring MCP tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    def send(command: str, params: dict) -> str:
        try:
            return json.dumps(get_connection().send_command(command, params), indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("configure_physics_body")
    def configure_physics_body(
        prim_path: str,
        body_type: str = "dynamic",
        collider_enabled: bool = True,
        approximation: Optional[str] = None,
        mass_kg: Optional[float] = None,
        density_kg_m3: Optional[float] = None,
    ) -> str:
        """Atomically configure rigid/static body, collider approximation and mass.

        body_type is dynamic, kinematic, or static. approximation is one of
        none, convex_hull, convex_decomposition, mesh_simplification,
        bounding_cube, or bounding_sphere. Mass uses kg and density uses kg/m^3.
        The timeline must be stopped.
        """
        params = {"prim_path": prim_path, "body_type": body_type, "collider_enabled": collider_enabled}
        for key, value in (("approximation", approximation), ("mass_kg", mass_kg), ("density_kg_m3", density_kg_m3)):
            if value is not None:
                params[key] = value
        return send("physics.configure_body", params)

    @mcp.tool("get_physics_body")
    def get_physics_body(prim_path: str) -> str:
        """Read authored rigid body, collider, approximation, mass and density."""
        return send("physics.get_body", {"prim_path": prim_path})

    @mcp.tool("create_collision_group")
    def create_collision_group(
        group_path: str,
        collider_paths: List[str],
        filtered_group_paths: Optional[List[str]] = None,
        invert_filtered_groups: bool = False,
        merge_group_name: Optional[str] = None,
    ) -> str:
        """Create a USD collision group and return relationship read-back."""
        params = {
            "group_path": group_path,
            "collider_paths": collider_paths,
            "invert_filtered_groups": invert_filtered_groups,
        }
        if filtered_group_paths is not None:
            params["filtered_group_paths"] = filtered_group_paths
        if merge_group_name is not None:
            params["merge_group_name"] = merge_group_name
        return send("physics.create_collision_group", params)

    @mcp.tool("get_collision_group")
    def get_collision_group(group_path: str) -> str:
        """Read collision group members, filters, inversion and merge name."""
        return send("physics.get_collision_group", {"group_path": group_path})

    @mcp.tool("create_physics_joint")
    def create_physics_joint(
        joint_path: str,
        joint_type: str,
        body1: str,
        body0: Optional[str] = None,
        axis: Optional[str] = None,
        lower_limit: Optional[float] = None,
        upper_limit: Optional[float] = None,
        local_position0: Optional[List[float]] = None,
        local_rotation0: Optional[List[float]] = None,
        local_position1: Optional[List[float]] = None,
        local_rotation1: Optional[List[float]] = None,
        collision_enabled: bool = False,
    ) -> str:
        """Create fixed, revolute, or prismatic joint with explicit local frames.

        Positions and prismatic limits are meters; revolute limits are degrees.
        Quaternion rotations use [w, x, y, z]. Axis is X, Y, or Z.
        """
        params = {
            "joint_path": joint_path,
            "joint_type": joint_type,
            "body1": body1,
            "collision_enabled": collision_enabled,
        }
        for key, value in (
            ("body0", body0),
            ("axis", axis),
            ("lower_limit", lower_limit),
            ("upper_limit", upper_limit),
            ("local_position0", local_position0),
            ("local_rotation0", local_rotation0),
            ("local_position1", local_position1),
            ("local_rotation1", local_rotation1),
        ):
            if value is not None:
                params[key] = value
        return send("physics.create_joint", params)

    @mcp.tool("get_physics_joint")
    def get_physics_joint(joint_path: str) -> str:
        """Read joint type, body targets, frames, axis, limits and units."""
        return send("physics.get_joint", {"joint_path": joint_path})
