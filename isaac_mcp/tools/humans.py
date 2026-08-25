# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""NVIDIA Replicator Agent human-character MCP tools."""

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    def send(command: str, params: Dict[str, Any]) -> str:
        try:
            return json.dumps(get_connection().send_command(command, params), indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("spawn_human")
    def spawn_human(
        count: int = 1,
        group_name: str = "MCPHumans",
        root_prim_path: str = "/World/Characters",
        asset_path: Optional[str] = None,
        motion_library_path: Optional[str] = None,
        behavior: str = "wander",
        spawn_areas: Optional[List[str]] = None,
        speed_range: Optional[List[float]] = None,
        distance_range: Optional[List[float]] = None,
        idle_time_range: Optional[List[float]] = None,
        patrol_points: Optional[List[List[float]]] = None,
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        auto_create_navmesh_volume: bool = False,
        navmesh_volume_center: Optional[List[float]] = None,
        navmesh_volume_size: Optional[List[float]] = None,
        seed: int = 12345,
    ) -> str:
        """Spawn animated NVIDIA human characters into the CURRENT USD stage.

        Uses Isaac Sim 6.0+'s ``isaacsim.replicator.agent.core`` (IRA 1.x)
        character loader and SimReady assets. Unlike ``IRA.setup_simulation()``,
        this tool does not reopen the environment USD, so existing scene edits
        are preserved.

        A NavMesh is required. The tool can bake an authored volume and waits
        up to 2000 update frames for complex factory stages. The extension is
        enabled automatically, but the tool fails closed when no usable
        NavMesh or character assets are available. Stop the timeline first.

        ``execute_script`` remains useful for one-off IRA experiments.
        ``reload_script`` is the better companion for reusable interaction or
        event logic after characters have been spawned.

        Args:
            count: Number of new characters to add, from 1 to 25.
            group_name: USD-safe IRA group name. Reusing it appends characters.
            root_prim_path: Parent prim for all characters.
            asset_path: Character asset directory. Defaults to
                ``Isaac/People/Characters/``.
            motion_library_path: Human motion-library USD. Defaults to the IRA
                extension setting / Isaac Sim asset root.
            behavior: ``wander``, ``patrol``, ``stop``, or ``manual``. Use
                ``manual`` when interaction scripts will issue Behavior Agent
                tasks directly.
            spawn_areas: Optional NavMesh area names used for spawning.
            speed_range: Two walking speeds in m/s.
            distance_range: Two wander-leg distances in meters.
            idle_time_range: Two idle/stop durations in seconds.
            patrol_points: Required for ``patrol``; reachable NavMesh points as
                ``[[x,y,z], ...]``.
            position: Optional exact world position for one spawned character.
                The point should lie on the NavMesh.
            rotation: Optional ``[rx, ry, rz]`` degrees; requires ``count=1``.
            auto_create_navmesh_volume: Create one include-volume when the
                stage has none. This modifies the current stage and requires
                ``navmesh_volume_size``.
            navmesh_volume_center: Center of the new NavMesh volume. Defaults
                to ``[0, 0, 1]``.
            navmesh_volume_size: Full ``[x, y, z]`` size in stage units. Make
                it cover the walkable floor and surrounding obstacles.
            seed: Deterministic 32-bit IRA randomization seed.
        """
        try:
            params = {
                "count": count,
                "group_name": group_name,
                "root_prim_path": root_prim_path,
                "behavior": behavior,
                "auto_create_navmesh_volume": auto_create_navmesh_volume,
                "seed": seed,
            }
            optional = {
                "asset_path": asset_path,
                "motion_library_path": motion_library_path,
                "spawn_areas": spawn_areas,
                "speed_range": speed_range,
                "distance_range": distance_range,
                "idle_time_range": idle_time_range,
                "patrol_points": patrol_points,
                "position": position,
                "rotation": rotation,
                "navmesh_volume_center": navmesh_volume_center,
                "navmesh_volume_size": navmesh_volume_size,
            }
            params.update({key: value for key, value in optional.items() if value is not None})
            result = get_connection().send_command("humans.spawn", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("list_humans")
    def list_humans(root_prim_path: str = "/World/Characters", include_external: bool = True) -> str:
        """List IRA human characters without changing the stage."""
        return send("humans.list", {"root_prim_path": root_prim_path, "include_external": include_external})

    @mcp.tool("get_human")
    def get_human(human_path: str) -> str:
        """Return USD and live Behavior Agent state for one IRA human."""
        return send("humans.get", {"human_path": human_path})

    @mcp.tool("delete_human")
    def delete_human(human_path: str, delete_empty_group: bool = True, preview: bool = True) -> str:
        """Delete one MCP-owned human. Preview is enabled by default."""
        return send(
            "humans.delete",
            {"human_path": human_path, "delete_empty_group": delete_empty_group, "preview": preview},
        )

    @mcp.tool("set_human_target")
    def set_human_target(
        human_path: str,
        target_position: Optional[List[float]] = None,
        target_prim_path: Optional[str] = None,
        speed_mps: Optional[float] = None,
        auto_brake: bool = True,
        preview: bool = True,
    ) -> str:
        """Issue a Behavior Agent MoveTo task to exactly one target."""
        params: Dict[str, Any] = {
            "human_path": human_path,
            "auto_brake": auto_brake,
            "preview": preview,
        }
        if target_position is not None:
            params["target_position"] = target_position
        if target_prim_path is not None:
            params["target_prim_path"] = target_prim_path
        if speed_mps is not None:
            params["speed_mps"] = speed_mps
        return send("humans.set_target", params)

    @mcp.tool("set_human_look_at")
    def set_human_look_at(
        human_path: str,
        target_position: Optional[List[float]] = None,
        target_prim_path: Optional[str] = None,
        duration_seconds: float = 0.0,
        preview: bool = True,
    ) -> str:
        """Issue a Behavior Agent LookAt task; zero duration means indefinite."""
        params: Dict[str, Any] = {
            "human_path": human_path,
            "duration_seconds": duration_seconds,
            "preview": preview,
        }
        if target_position is not None:
            params["target_position"] = target_position
        if target_prim_path is not None:
            params["target_prim_path"] = target_prim_path
        return send("humans.look_at", params)

    @mcp.tool("set_human_idle")
    def set_human_idle(
        human_path: str,
        facing_position: Optional[List[float]] = None,
        facing_prim_path: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Cancel the active action by issuing Idle, optionally facing one target."""
        params: Dict[str, Any] = {"human_path": human_path, "preview": preview}
        if facing_position is not None:
            params["facing_position"] = facing_position
        if facing_prim_path is not None:
            params["facing_prim_path"] = facing_prim_path
        return send("humans.idle", params)

    @mcp.tool("set_human_behavior")
    def set_human_behavior(
        human_path: str,
        enabled: Optional[bool] = None,
        speed_mps: Optional[float] = None,
        navigation_areas: Optional[List[str]] = None,
        obstacle_avoidance_enabled: Optional[bool] = None,
        auto_avoidance_enabled: Optional[bool] = None,
        preview: bool = True,
    ) -> str:
        """Update supported live Behavior Agent settings with read-back."""
        params: Dict[str, Any] = {"human_path": human_path, "preview": preview}
        optional = {
            "enabled": enabled,
            "speed_mps": speed_mps,
            "navigation_areas": navigation_areas,
            "obstacle_avoidance_enabled": obstacle_avoidance_enabled,
            "auto_avoidance_enabled": auto_avoidance_enabled,
        }
        params.update({key: value for key, value in optional.items() if value is not None})
        return send("humans.set_behavior", params)

    @mcp.tool("get_navmesh_status")
    def get_navmesh_status() -> str:
        """Return Navigation Core, NavMeshVolume, bake and area status."""
        return send("humans.navmesh_status", {})

    @mcp.tool("bake_navmesh")
    def bake_navmesh(max_frames: int = 2000, preview: bool = True) -> str:
        """Bake the current stage NavMesh with a bounded wait; preview by default."""
        return send("humans.bake_navmesh", {"max_frames": max_frames, "preview": preview})
