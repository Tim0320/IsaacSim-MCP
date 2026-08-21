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
from typing import TYPE_CHECKING, Callable, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

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
