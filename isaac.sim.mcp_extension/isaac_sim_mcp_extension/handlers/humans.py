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

"""Spawn NVIDIA IRA 1.x human characters without replacing the current stage."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

from ..adapters.base import IsaacAdapterBase

_IRA_CORE_ID = "isaacsim.replicator.agent.core"
_USD_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["humans.spawn"] = lambda **p: spawn(adapter, **p)


def _pair(value: Optional[Sequence[float]], default: Sequence[float], name: str) -> list[float]:
    result = list(default if value is None else value)
    if len(result) != 2 or not all(isinstance(item, (int, float)) for item in result):
        raise ValueError(f"{name} must contain exactly two numbers")
    if result[0] > result[1]:
        raise ValueError(f"{name} minimum cannot exceed maximum")
    return [float(result[0]), float(result[1])]


def _vector3(value: Optional[Sequence[float]], name: str) -> Optional[list[float]]:
    if value is None:
        return None
    result = list(value)
    if len(result) != 3 or not all(isinstance(item, (int, float)) for item in result):
        raise ValueError(f"{name} must contain exactly three numbers")
    return [float(item) for item in result]


def _build_routines(
    behavior: str,
    speed_range: Optional[Sequence[float]],
    distance_range: Optional[Sequence[float]],
    idle_time_range: Optional[Sequence[float]],
    patrol_points: Optional[Sequence[Sequence[float]]],
) -> list[dict[str, Any]]:
    behavior = behavior.lower().strip()
    if behavior == "manual":
        return []

    speed = _pair(speed_range, [1.0, 1.0], "speed_range")
    idle = _pair(idle_time_range, [2.0, 5.0], "idle_time_range")
    if speed[0] <= 0:
        raise ValueError("speed_range values must be positive")

    if behavior == "wander":
        distance = _pair(distance_range, [5.0, 15.0], "distance_range")
        if distance[0] < 0:
            raise ValueError("distance_range values cannot be negative")
        return [
            {
                "wander": {
                    "walk": {"speed_range": speed, "distance_range": distance},
                    "idle": [{"animation": "idle", "time_range": idle}],
                }
            }
        ]

    if behavior == "patrol":
        if not patrol_points:
            raise ValueError("patrol_points is required when behavior='patrol'")
        points = [_vector3(point, f"patrol_points[{index}]") for index, point in enumerate(patrol_points)]
        return [{"patrol": {"speed_range": speed, "path_points": points}}]

    if behavior == "stop":
        return [{"stop": {"time_range": idle}}]

    raise ValueError("behavior must be one of: wander, patrol, stop, manual")


async def _enable_ira_core() -> tuple[bool, str]:
    import omni.kit.app

    app = omni.kit.app.get_app()
    manager = app.get_extension_manager()
    if not manager.is_extension_enabled(_IRA_CORE_ID):
        manager.set_extension_enabled_immediate(_IRA_CORE_ID, True)
        for _ in range(5):
            await app.next_update_async()
    if not manager.is_extension_enabled(_IRA_CORE_ID):
        return False, f"Failed to enable {_IRA_CORE_ID}; verify Isaac Sim 6.0+ Actor SDG extensions are installed"
    return True, manager.get_extension_path_by_module(_IRA_CORE_ID) or ""


def _ensure_navmesh_volume(
    adapter: IsaacAdapterBase,
    stage: Any,
    auto_create: bool,
    center: Optional[Sequence[float]],
    size: Optional[Sequence[float]],
) -> tuple[Optional[str], bool]:
    existing = [str(prim.GetPath()) for prim in stage.TraverseAll() if prim.GetTypeName() == "NavMeshVolume"]
    if existing:
        return existing[0], False
    if not auto_create:
        return None, False
    if size is None:
        raise ValueError("navmesh_volume_size is required when auto_create_navmesh_volume=true")

    volume_center = _vector3(center or [0.0, 0.0, 1.0], "navmesh_volume_center")
    volume_size = _vector3(size, "navmesh_volume_size")
    if any(component <= 0 for component in volume_size):
        raise ValueError("navmesh_volume_size values must be positive")

    import NavSchema
    import omni.usd
    from pxr import Gf, UsdGeom

    volume_path = omni.usd.get_stage_next_free_path(stage, "/World/MCPNavMeshVolume", True)
    volume = NavSchema.NavMeshVolume.Define(stage, volume_path)
    volume.GetNavVolumeTypeAttr().Set("Include")
    prim = volume.GetPrim()
    prim.ApplyAPI(NavSchema.NavMeshAreaAPI)
    UsdGeom.Boundable(prim).CreateExtentAttr().Set([Gf.Vec3f(-0.5, -0.5, -0.5), Gf.Vec3f(0.5, 0.5, 0.5)])
    adapter.set_prim_transform(volume_path, position=volume_center, scale=volume_size)
    return str(volume_path), True


async def _wait_for_navmesh(max_frames: int = 2000) -> tuple[bool, int]:
    """Bake/wait beyond IRA's 100-frame helper limit for real factory stages."""
    import omni.anim.navigation.core as nav
    import omni.kit.app

    interface = nav.acquire_interface()
    if interface.get_navmesh() is not None:
        return True, 0
    if not interface.is_navmesh_baking() and not interface.start_navmesh_baking():
        return False, 0
    app = omni.kit.app.get_app()
    for frame in range(1, max_frames + 1):
        await app.next_update_async()
        if interface.get_navmesh() is not None:
            return True, frame
        if not interface.is_navmesh_baking():
            return False, frame
    return False, max_frames


async def _refresh_behavior_agents(stage: Any, character_paths: Sequence[str]) -> list[str]:
    """Resync dynamically loaded SkelRoots with the Behavior Core scanner."""
    import BehaviorSchema
    import omni.kit.app
    from pxr import Usd, UsdSkel

    refreshed: list[str] = []
    for character_path in character_paths:
        character_prim = stage.GetPrimAtPath(character_path)
        if not character_prim or not character_prim.IsValid():
            continue
        for prim in Usd.PrimRange(character_prim):
            if prim.IsA(UsdSkel.Root) and prim.HasAPI(BehaviorSchema.BehaviorAgentAPI):
                # NVIDIA's Behavior Core tests use this re-application after a
                # character payload is loaded into an already-open stage. It
                # emits the prim resync that the initial stage scan can miss.
                BehaviorSchema.BehaviorAgentAPI.Apply(prim)
                refreshed.append(str(prim.GetPath()))

    app = omni.kit.app.get_app()
    await app.next_update_async()
    await app.next_update_async()
    return refreshed


async def spawn(
    adapter: IsaacAdapterBase,
    count: int = 1,
    group_name: str = "MCPHumans",
    root_prim_path: str = "/World/Characters",
    asset_path: Optional[str] = None,
    motion_library_path: Optional[str] = None,
    behavior: str = "wander",
    spawn_areas: Optional[Sequence[str]] = None,
    speed_range: Optional[Sequence[float]] = None,
    distance_range: Optional[Sequence[float]] = None,
    idle_time_range: Optional[Sequence[float]] = None,
    patrol_points: Optional[Sequence[Sequence[float]]] = None,
    position: Optional[Sequence[float]] = None,
    rotation: Optional[Sequence[float]] = None,
    auto_create_navmesh_volume: bool = False,
    navmesh_volume_center: Optional[Sequence[float]] = None,
    navmesh_volume_size: Optional[Sequence[float]] = None,
    seed: int = 12345,
) -> Dict[str, Any]:
    try:
        if not isinstance(count, int) or not 1 <= count <= 25:
            return {"status": "error", "message": "count must be an integer from 1 to 25"}
        if not _USD_IDENTIFIER.fullmatch(group_name):
            return {
                "status": "error",
                "message": "group_name must be a USD identifier using letters, numbers, and underscores",
            }
        if not isinstance(root_prim_path, str) or not root_prim_path.startswith("/"):
            return {"status": "error", "message": "root_prim_path must be an absolute USD prim path"}
        if not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
            return {"status": "error", "message": "seed must be a 32-bit unsigned integer"}
        if spawn_areas is not None and (
            not all(isinstance(area, str) and area.strip() for area in spawn_areas)
            or len(set(spawn_areas)) != len(spawn_areas)
        ):
            return {"status": "error", "message": "spawn_areas must contain unique non-empty strings"}

        exact_position = _vector3(position, "position")
        exact_rotation = _vector3(rotation, "rotation")
        if count != 1 and (exact_position is not None or exact_rotation is not None):
            return {"status": "error", "message": "position and rotation require count=1"}
        routines = _build_routines(behavior, speed_range, distance_range, idle_time_range, patrol_points)

        state = adapter.get_simulation_state()
        if state.get("timeline_state") == "playing":
            return {"status": "error", "message": "Stop or pause the timeline before calling spawn_human"}

        stage = adapter.get_stage()
        if stage is None:
            return {"status": "error", "message": "No USD stage is open"}

        enabled, extension_path = await _enable_ira_core()
        if not enabled:
            return {"status": "error", "message": extension_path}

        # Import only after enabling IRA so this MCP extension remains usable on
        # Isaac Sim installations where Actor SDG is unavailable.
        from isaacsim.replicator.agent.core.configuration.models.character import CharacterConfig
        from isaacsim.replicator.agent.core.randomizer import Randomizer
        from isaacsim.replicator.agent.core.scene_assembly import CharacterLoader

        navmesh_volume_path, navmesh_volume_created = _ensure_navmesh_volume(
            adapter,
            stage,
            auto_create_navmesh_volume,
            navmesh_volume_center,
            navmesh_volume_size,
        )
        if navmesh_volume_created:
            import omni.kit.app

            await omni.kit.app.get_app().next_update_async()
        if navmesh_volume_path is None:
            return {
                "status": "error",
                "message": (
                    "The current stage has no NavMeshVolume. Create and bake one first, or call spawn_human with "
                    "auto_create_navmesh_volume=true and an explicit navmesh_volume_size."
                ),
            }

        navmesh_ready, navmesh_bake_frames = await _wait_for_navmesh()
        if not navmesh_ready:
            return {
                "status": "error",
                "message": (
                    f"NavMesh baking did not produce a NavMesh after {navmesh_bake_frames} update frames. "
                    "Verify that the volume overlaps a walkable collision surface."
                ),
                "navmesh_volume_path": navmesh_volume_path,
            }

        group_path = f"{root_prim_path.rstrip('/')}/{group_name}"
        before = {
            str(prim.GetPath())
            for prim in stage.TraverseAll()
            if str(prim.GetPath()).startswith(group_path + "/")
            and str(prim.GetPath()).count("/") == group_path.count("/") + 1
        }

        # CharacterLoader treats num as a group target, not an increment. Ask
        # for the existing direct children plus the requested new characters.
        target_count = len(before) + count
        group: dict[str, Any] = {
            "num": target_count,
            "spawn_areas": list(spawn_areas or []),
            "routines": routines,
        }
        if asset_path:
            group["asset_path"] = asset_path
        config_data: dict[str, Any] = {
            "root_prim_path": root_prim_path,
            "groups": {group_name: group},
        }
        if motion_library_path:
            config_data["motion_library_path"] = motion_library_path

        config = CharacterConfig.model_validate(config_data)
        loaded = await CharacterLoader(config, Randomizer(seed), stage).load()
        after = {
            str(prim.GetPath())
            for prim in stage.TraverseAll()
            if str(prim.GetPath()).startswith(group_path + "/")
            and str(prim.GetPath()).count("/") == group_path.count("/") + 1
        }
        created = sorted(after - before)

        if loaded <= 0 or not created:
            return {
                "status": "error",
                "message": (
                    "IRA loaded no characters. A baked NavMesh and reachable NVIDIA character/motion assets are required. "
                    "Inspect get_isaac_logs for the exact asset or NavMesh failure. If a valid NavMeshVolume is reported "
                    "as missing after IRA was enabled late, restart Isaac Sim so Navigation Core loads before the stage."
                ),
                "ira_extension": _IRA_CORE_ID,
                "extension_path": extension_path,
            }

        behavior_agent_paths = await _refresh_behavior_agents(stage, created)

        if exact_position is not None or exact_rotation is not None:
            adapter.set_prim_transform(created[0], position=exact_position, rotation=exact_rotation)

        warning = None
        if exact_position is not None and behavior in {"wander", "patrol"}:
            warning = "Exact position was applied after spawning; keep it on the baked NavMesh for navigation behavior."
        result: Dict[str, Any] = {
            "status": "success",
            "message": f"Spawned {len(created)} NVIDIA IRA human character(s)",
            "created_prim_paths": created,
            "group_path": group_path,
            "behavior": behavior.lower().strip(),
            "ira_extension": _IRA_CORE_ID,
            "preserved_current_stage": True,
            "navmesh_volume_path": navmesh_volume_path,
            "navmesh_volume_created": navmesh_volume_created,
            "navmesh_bake_frames": navmesh_bake_frames,
            "behavior_agent_paths": behavior_agent_paths,
        }
        if warning:
            result["warning"] = warning
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
