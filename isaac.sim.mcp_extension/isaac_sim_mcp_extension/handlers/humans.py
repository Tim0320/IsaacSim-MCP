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

import asyncio
import re
import time
from typing import Any, Dict, Optional, Sequence

from ..adapters.base import IsaacAdapterBase

_IRA_CORE_ID = "isaacsim.replicator.agent.core"
_USD_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MCP_HUMAN_KEY = "isaacsimMcpHuman"
_MCP_HUMAN_SCHEMA = "1.0"
_NAVMESH_NOTICE_FRAMES = 5
_NAVMESH_SETTLE_FRAMES = 5
_NAVMESH_CANCEL_SETTLE_FRAMES = 5
_NAVMESH_CANCEL_TIMEOUT_SECONDS = 1.0
_NAVMESH_DEFAULT_TIMEOUT_SECONDS = 120.0
_NAVMESH_MAX_TIMEOUT_SECONDS = 240.0


class _TimelineStateConflict(RuntimeError):
    pass


class _HumanTaskRejected(RuntimeError):
    pass


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["humans.spawn"] = lambda **p: spawn(adapter, **p)
    registry["humans.list"] = lambda **p: list_humans(adapter, **p)
    registry["humans.get"] = lambda **p: get_human(adapter, **p)
    registry["humans.delete"] = lambda **p: delete_human(adapter, **p)
    registry["humans.set_target"] = lambda **p: set_human_target(adapter, **p)
    registry["humans.look_at"] = lambda **p: set_human_look_at(adapter, **p)
    registry["humans.idle"] = lambda **p: set_human_idle(adapter, **p)
    registry["humans.set_behavior"] = lambda **p: set_human_behavior(adapter, **p)
    registry["humans.navmesh_status"] = lambda **p: get_navmesh_status(adapter, **p)
    registry["humans.bake_navmesh"] = lambda **p: bake_navmesh(adapter, **p)


def _error(code: str, message: str, **data: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "error", "code": code, "message": message}
    result.update(data)
    return result


def _valid_absolute_prim_path(path: Any) -> bool:
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        return False
    try:
        from pxr import Sdf

        return bool(Sdf.Path(path).IsAbsolutePath() and Sdf.Path(path).IsPrimPath())
    except Exception:
        return bool(re.fullmatch(r"/(?:[A-Za-z_][A-Za-z0-9_]*)(?:/[A-Za-z_][A-Za-z0-9_]*)*", path))


def _human_marker(prim: Any) -> Optional[dict[str, Any]]:
    marker = prim.GetCustomDataByKey(_MCP_HUMAN_KEY)
    if not isinstance(marker, dict):
        return None
    marker = dict(marker)
    if marker.get("owner") != "isaacsim-mcp" or marker.get("schema") != _MCP_HUMAN_SCHEMA:
        return None
    return marker


def _find_behavior_agent_paths(prim: Any) -> list[str]:
    import BehaviorSchema
    from pxr import Usd

    return sorted(
        str(candidate.GetPath())
        for candidate in Usd.PrimRange(prim)
        if candidate.HasAPI(BehaviorSchema.BehaviorAgentAPI)
    )


def _resolve_human(stage: Any, human_path: str) -> tuple[Any, Optional[dict[str, Any]], list[str]]:
    if not _valid_absolute_prim_path(human_path):
        raise ValueError("human_path must be an absolute USD prim path")
    prim = stage.GetPrimAtPath(human_path)
    if not prim or not prim.IsValid():
        raise LookupError(f"Human prim does not exist: {human_path}")

    current = prim
    while current and current.IsValid() and str(current.GetPath()) != "/":
        marker = _human_marker(current)
        if marker:
            return current, marker, _find_behavior_agent_paths(current)
        current = current.GetParent()
    paths = _find_behavior_agent_paths(prim)
    return prim, None, paths


def _acquire_behavior_agent(agent_paths: Sequence[str]) -> tuple[Any, str]:
    import omni.anim.behavior.core as behavior_core

    interface = behavior_core.acquire_interface()
    for path in agent_paths:
        agent = interface.get_agent(path)
        if agent:
            return agent, path
    return None, ""


def _float3(value: Sequence[float]) -> Any:
    import carb

    return carb.Float3(float(value[0]), float(value[1]), float(value[2]))


def _one_target(position: Optional[Sequence[float]], prim_path: Optional[str], position_name: str) -> Any:
    if (position is None) == (prim_path is None):
        raise ValueError(f"Provide exactly one of {position_name} or target prim path")
    if position is not None:
        return _float3(_vector3(position, position_name))
    if not _valid_absolute_prim_path(prim_path):
        raise ValueError("target prim path must be an absolute USD prim path")
    return prim_path


def _task_snapshot(agent: Any, task_id: int) -> dict[str, Any]:
    import omni.anim.behavior.core as behavior_core

    if task_id == behavior_core.BEHAVIOR_TASK_ID_INVALID:
        raise _HumanTaskRejected("Behavior Agent rejected the task; verify initialization and NavMesh reachability")
    status = agent.get_task_status(task_id)
    return {
        "task_id": int(task_id),
        "task_name": agent.get_task_name(task_id),
        "task_status": getattr(status, "name", str(status)).lower(),
        "task_running": bool(agent.is_task_running(task_id)),
    }


def _agent_snapshot(agent: Any, agent_path: str) -> dict[str, Any]:
    task_id = int(agent.get_action_task_id())
    result = {
        "agent_path": agent_path,
        "enabled": bool(agent.is_enabled()),
        "position": [float(v) for v in agent.get_world_translation()],
        "facing_direction": [float(v) for v in agent.get_facing_direction()],
        "linear_velocity": [float(v) for v in agent.get_linear_velocity()],
        "speed_stage_units_per_second": float(agent.get_speed()),
        "navigation_areas": list(agent.get_navmesh_areas_allowed()),
        "obstacle_avoidance_enabled": bool(agent.is_obstacle_avoidance_enabled()),
        "auto_avoidance_enabled": bool(agent.is_auto_avoidance_enabled()),
        "current_task_id": task_id,
    }
    if task_id >= 0:
        try:
            result.update(_task_snapshot(agent, task_id))
        except Exception:
            result["task_name"] = None
    return result


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


async def _cancel_navmesh_baking(interface: Any, app: Any) -> Optional[bool]:
    """Request cancellation and confirm the native baking flag clears."""
    try:
        if not interface.is_navmesh_baking():
            return None
    except Exception:
        return False

    cancel = getattr(interface, "cancel_navmesh_baking", None)
    if not callable(cancel):
        return False
    try:
        # Navigation Core 110.1.4 declares a void return. Confirmation comes
        # from is_navmesh_baking(), not the Python return value.
        cancel()
    except Exception:
        return False

    deadline = time.perf_counter() + _NAVMESH_CANCEL_TIMEOUT_SECONDS
    for _ in range(_NAVMESH_CANCEL_SETTLE_FRAMES + 1):
        try:
            if not interface.is_navmesh_baking():
                return True
        except Exception:
            return False
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(app.next_update_async(), timeout=remaining)
        except asyncio.TimeoutError:
            break
    try:
        return not bool(interface.is_navmesh_baking())
    except Exception:
        return False


async def _wait_for_navmesh(
    max_frames: int = 2000,
    force_rebake: bool = False,
    timeout_seconds: float = _NAVMESH_DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Bake with frame and wall-clock bounds, then wait for native publication."""
    import omni.anim.navigation.core as nav
    import omni.kit.app

    started_at = time.perf_counter()
    interface = nav.acquire_interface()

    def _result(
        *,
        ready: bool,
        frames: int,
        reason: str,
        start_result: Optional[bool],
        settle_frames: int = 0,
        cancel_result: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return {
            "ready": ready,
            "frames": frames,
            "reason": reason,
            "start_result": start_result,
            "elapsed_seconds": time.perf_counter() - started_at,
            "settle_frames": settle_frames,
            "cancel_result": cancel_result,
        }

    if interface.get_navmesh() is not None and not force_rebake:
        return _result(ready=True, frames=0, reason="already_ready", start_result=None)
    app = omni.kit.app.get_app()

    async def _next_update() -> bool:
        remaining = timeout_seconds - (time.perf_counter() - started_at)
        if remaining <= 0:
            return False
        try:
            await asyncio.wait_for(app.next_update_async(), timeout=remaining)
        except asyncio.TimeoutError:
            return False
        return True

    # Navigation Core's own 110.1 tests allow five application updates after
    # authoring a NavMeshVolume before asking the native interface to bake.
    # Without this notice-processing window start_navmesh_baking() rejects a
    # newly authored volume even though USD read-back already sees it.
    for _ in range(_NAVMESH_NOTICE_FRAMES):
        if not await _next_update():
            return _result(
                ready=False,
                frames=0,
                reason="timeout",
                start_result=None,
                cancel_result=await _cancel_navmesh_baking(interface, app),
            )
    start_result = None
    if not interface.is_navmesh_baking():
        # Some Navigation Core 110.1 Python builds start the asynchronous bake
        # but return None despite the generated stub advertising bool. Only an
        # explicit False is a rejection; readiness/baking is proven below.
        start_result = interface.start_navmesh_baking()
        if start_result is False:
            return _result(ready=False, frames=0, reason="start_rejected", start_result=False)
    for frame in range(1, max_frames + 1):
        if not await _next_update():
            return _result(
                ready=False,
                frames=frame - 1,
                reason="timeout",
                start_result=start_result,
                cancel_result=await _cancel_navmesh_baking(interface, app),
            )
        current_navmesh = interface.get_navmesh()
        baking = bool(interface.is_navmesh_baking())
        # A force-rebake can retain the previous immutable NavMesh while the
        # new native job is still running. Never accept that stale object until
        # the current baking flag has cleared.
        if baking:
            continue
        if current_navmesh is not None:
            return _result(ready=True, frames=frame, reason="ready", start_result=start_result)
        # Navigation Core may clear its baking flag one or more updates before
        # the completed NavMesh is published by get_navmesh().
        for settle_frame in range(1, _NAVMESH_SETTLE_FRAMES + 1):
            if not await _next_update():
                return _result(
                    ready=False,
                    frames=frame,
                    reason="timeout",
                    start_result=start_result,
                    settle_frames=settle_frame - 1,
                    cancel_result=await _cancel_navmesh_baking(interface, app),
                )
            if interface.get_navmesh() is not None:
                return _result(
                    ready=True,
                    frames=frame,
                    reason="ready",
                    start_result=start_result,
                    settle_frames=settle_frame,
                )
        return _result(
            ready=False,
            frames=frame,
            reason="completed_without_navmesh",
            start_result=start_result,
            settle_frames=_NAVMESH_SETTLE_FRAMES,
        )
    return _result(
        ready=False,
        frames=max_frames,
        reason="max_frames_exceeded",
        start_result=start_result,
        cancel_result=await _cancel_navmesh_baking(interface, app),
    )


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


def _describe_human(
    stage: Any, prim: Any, marker: Optional[dict[str, Any]], agent_paths: Sequence[str]
) -> dict[str, Any]:
    path = str(prim.GetPath())
    item: dict[str, Any] = {
        "human_path": path,
        "name": prim.GetName(),
        "mcp_owned": bool(marker),
        "marker_schema": marker.get("schema") if marker else None,
        "behavior": marker.get("behavior") if marker else None,
        "group_path": marker.get("group_path") if marker else str(prim.GetParent().GetPath()),
        "behavior_agent_paths": list(agent_paths),
        "behavior_agent_ready": False,
    }
    agent, agent_path = _acquire_behavior_agent(agent_paths)
    if agent:
        item["behavior_agent_ready"] = True
        item["runtime"] = _agent_snapshot(agent, agent_path)
    return item


def list_humans(
    adapter: IsaacAdapterBase,
    root_prim_path: str = "/World/Characters",
    include_external: bool = True,
) -> Dict[str, Any]:
    try:
        if not _valid_absolute_prim_path(root_prim_path):
            return _error("INVALID_HUMAN_REQUEST", "root_prim_path must be an absolute USD prim path")
        stage = adapter.get_stage()
        if stage is None:
            return _error("NO_STAGE", "No USD stage is open")
        root = stage.GetPrimAtPath(root_prim_path)
        if not root or not root.IsValid():
            return {"status": "success", "humans": [], "count": 0, "root_prim_path": root_prim_path}

        humans: list[dict[str, Any]] = []
        seen: set[str] = set()
        for prim in stage.TraverseAll():
            path = str(prim.GetPath())
            if path != root_prim_path and not path.startswith(root_prim_path.rstrip("/") + "/"):
                continue
            marker = _human_marker(prim)
            if marker:
                agent_paths = _find_behavior_agent_paths(prim)
                humans.append(_describe_human(stage, prim, marker, agent_paths))
                seen.update(agent_paths)
        if include_external:
            import BehaviorSchema

            for prim in stage.TraverseAll():
                path = str(prim.GetPath())
                if path in seen or not path.startswith(root_prim_path.rstrip("/") + "/"):
                    continue
                if prim.HasAPI(BehaviorSchema.BehaviorAgentAPI):
                    humans.append(_describe_human(stage, prim, None, [path]))
        humans.sort(key=lambda item: item["human_path"])
        return {"status": "success", "humans": humans, "count": len(humans), "root_prim_path": root_prim_path}
    except Exception as exc:
        return _error("HUMAN_QUERY_FAILED", str(exc))


def get_human(adapter: IsaacAdapterBase, human_path: str) -> Dict[str, Any]:
    try:
        stage = adapter.get_stage()
        if stage is None:
            return _error("NO_STAGE", "No USD stage is open")
        prim, marker, agent_paths = _resolve_human(stage, human_path)
        if not agent_paths:
            return _error("HUMAN_AGENT_NOT_FOUND", f"No BehaviorAgentAPI was found below {human_path}")
        return {"status": "success", "human": _describe_human(stage, prim, marker, agent_paths)}
    except ValueError as exc:
        return _error("INVALID_HUMAN_REQUEST", str(exc))
    except LookupError as exc:
        return _error("HUMAN_NOT_FOUND", str(exc))
    except Exception as exc:
        return _error("HUMAN_QUERY_FAILED", str(exc))


def _control_context(
    adapter: IsaacAdapterBase, human_path: str, *, require_agent: bool = True
) -> tuple[Any, Any, dict[str, Any], list[str], Any, str]:
    stage = adapter.get_stage()
    if stage is None:
        raise RuntimeError("No USD stage is open")
    prim, marker, agent_paths = _resolve_human(stage, human_path)
    if not marker:
        raise PermissionError("Runtime control is limited to humans created by this MCP")
    if not agent_paths:
        raise LookupError(f"No BehaviorAgentAPI was found below {human_path}")
    agent, agent_path = _acquire_behavior_agent(agent_paths)
    if not agent and require_agent:
        raise RuntimeError("Behavior Agent is not ready; play the timeline and wait for initialization")
    return stage, prim, marker, agent_paths, agent, agent_path


def _control_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, _TimelineStateConflict):
        return _error("TIMELINE_STATE_CONFLICT", str(exc))
    if isinstance(exc, _HumanTaskRejected):
        return _error("HUMAN_TASK_REJECTED", str(exc))
    if isinstance(exc, ValueError):
        return _error("INVALID_HUMAN_REQUEST", str(exc))
    if isinstance(exc, PermissionError):
        return _error("HUMAN_NOT_OWNED", str(exc))
    if isinstance(exc, LookupError):
        message = str(exc)
        return _error("HUMAN_NOT_FOUND" if "does not exist" in message else "HUMAN_AGENT_NOT_FOUND", message)
    return _error("HUMAN_PREREQUISITE_MISSING", str(exc))


def _require_playing(adapter: IsaacAdapterBase) -> None:
    if adapter.get_simulation_state().get("timeline_state") != "playing":
        raise _TimelineStateConflict("Play the timeline before issuing a Behavior Agent task")


def set_human_target(
    adapter: IsaacAdapterBase,
    human_path: str,
    target_position: Optional[Sequence[float]] = None,
    target_prim_path: Optional[str] = None,
    speed_mps: Optional[float] = None,
    auto_brake: bool = True,
    preview: bool = True,
) -> Dict[str, Any]:
    try:
        if not preview:
            _require_playing(adapter)
        stage, prim, marker, agent_paths, agent, agent_path = _control_context(
            adapter, human_path, require_agent=not preview
        )
        target = _one_target(target_position, target_prim_path, "target_position")
        if speed_mps is not None and (not isinstance(speed_mps, (int, float)) or speed_mps <= 0):
            raise ValueError("speed_mps must be a positive number")
        if target_prim_path and not stage.GetPrimAtPath(target_prim_path).IsValid():
            raise ValueError(f"Target prim does not exist: {target_prim_path}")
        plan = {
            "operation": "move_to",
            "human_path": str(prim.GetPath()),
            "target": target_prim_path or list(target_position),
        }
        if preview:
            return {"status": "success", "preview": True, "plan": plan}
        _require_playing(adapter)
        original_speed = float(agent.get_speed())
        if speed_mps is not None:
            from pxr import UsdGeom

            meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage) or 1.0)
            agent.set_speed(float(speed_mps) / meters_per_unit)
        try:
            task = _task_snapshot(agent, agent.move_to(target, bool(auto_brake)))
        except Exception:
            if speed_mps is not None:
                agent.set_speed(original_speed)
            raise
        return {
            "status": "success",
            "preview": False,
            "operation": "move_to",
            "task": task,
            "readback": _agent_snapshot(agent, agent_path),
        }
    except Exception as exc:
        return _control_error(exc)


def set_human_look_at(
    adapter: IsaacAdapterBase,
    human_path: str,
    target_position: Optional[Sequence[float]] = None,
    target_prim_path: Optional[str] = None,
    duration_seconds: float = 0.0,
    preview: bool = True,
) -> Dict[str, Any]:
    try:
        if not preview:
            _require_playing(adapter)
        stage, prim, marker, agent_paths, agent, agent_path = _control_context(
            adapter, human_path, require_agent=not preview
        )
        target = _one_target(target_position, target_prim_path, "target_position")
        if not isinstance(duration_seconds, (int, float)) or duration_seconds < 0:
            raise ValueError("duration_seconds must be a non-negative number")
        if target_prim_path and not stage.GetPrimAtPath(target_prim_path).IsValid():
            raise ValueError(f"Target prim does not exist: {target_prim_path}")
        if preview:
            return {
                "status": "success",
                "preview": True,
                "plan": {
                    "operation": "look_at",
                    "human_path": str(prim.GetPath()),
                    "duration_seconds": duration_seconds,
                },
            }
        _require_playing(adapter)
        task = _task_snapshot(agent, agent.look_at(target, float(duration_seconds)))
        return {"status": "success", "preview": False, "task": task, "readback": _agent_snapshot(agent, agent_path)}
    except Exception as exc:
        return _control_error(exc)


def set_human_idle(
    adapter: IsaacAdapterBase,
    human_path: str,
    facing_position: Optional[Sequence[float]] = None,
    facing_prim_path: Optional[str] = None,
    preview: bool = True,
) -> Dict[str, Any]:
    try:
        if not preview:
            _require_playing(adapter)
        stage, prim, marker, agent_paths, agent, agent_path = _control_context(
            adapter, human_path, require_agent=not preview
        )
        facing = None
        if facing_position is not None or facing_prim_path is not None:
            facing = _one_target(facing_position, facing_prim_path, "facing_position")
        if facing_prim_path and not stage.GetPrimAtPath(facing_prim_path).IsValid():
            raise ValueError(f"Facing prim does not exist: {facing_prim_path}")
        if preview:
            return {
                "status": "success",
                "preview": True,
                "plan": {"operation": "idle", "human_path": str(prim.GetPath())},
            }
        _require_playing(adapter)
        task_id = agent.idle(facing) if facing is not None else agent.idle()
        task = _task_snapshot(agent, task_id)
        return {"status": "success", "preview": False, "task": task, "readback": _agent_snapshot(agent, agent_path)}
    except Exception as exc:
        return _control_error(exc)


def set_human_behavior(
    adapter: IsaacAdapterBase,
    human_path: str,
    enabled: Optional[bool] = None,
    speed_mps: Optional[float] = None,
    navigation_areas: Optional[Sequence[str]] = None,
    obstacle_avoidance_enabled: Optional[bool] = None,
    auto_avoidance_enabled: Optional[bool] = None,
    preview: bool = True,
) -> Dict[str, Any]:
    try:
        stage, prim, marker, agent_paths, agent, agent_path = _control_context(
            adapter, human_path, require_agent=not preview
        )
        changes: dict[str, Any] = {}
        for name, value in {
            "enabled": enabled,
            "obstacle_avoidance_enabled": obstacle_avoidance_enabled,
            "auto_avoidance_enabled": auto_avoidance_enabled,
        }.items():
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean")
            if value is not None:
                changes[name] = value
        if speed_mps is not None:
            if not isinstance(speed_mps, (int, float)) or speed_mps <= 0:
                raise ValueError("speed_mps must be a positive number")
            changes["speed_mps"] = float(speed_mps)
        if navigation_areas is not None:
            if not all(isinstance(area, str) and area.strip() for area in navigation_areas):
                raise ValueError("navigation_areas must contain non-empty strings")
            changes["navigation_areas"] = list(navigation_areas)
        if not changes:
            raise ValueError("At least one behavior setting must be provided")
        if preview:
            return {
                "status": "success",
                "preview": True,
                "plan": {"human_path": str(prim.GetPath()), "changes": changes},
            }

        before = _agent_snapshot(agent, agent_path)
        try:
            if enabled is not None:
                agent.set_enabled(enabled)
            if speed_mps is not None:
                from pxr import UsdGeom

                meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage) or 1.0)
                agent.set_speed(float(speed_mps) / meters_per_unit)
            if navigation_areas is not None:
                agent.set_navmesh_areas_allowed(list(navigation_areas))
            if obstacle_avoidance_enabled is not None:
                agent.set_obstacle_avoidance_enabled(obstacle_avoidance_enabled)
            if auto_avoidance_enabled is not None:
                agent.set_auto_avoidance_enabled(auto_avoidance_enabled)
            readback = _agent_snapshot(agent, agent_path)
            mismatches = []
            if enabled is not None and readback["enabled"] is not enabled:
                mismatches.append("enabled")
            if speed_mps is not None:
                expected_speed = float(speed_mps) / meters_per_unit
                if abs(readback["speed_stage_units_per_second"] - expected_speed) > 1e-5:
                    mismatches.append("speed_mps")
            if navigation_areas is not None and readback["navigation_areas"] != list(navigation_areas):
                mismatches.append("navigation_areas")
            if (
                obstacle_avoidance_enabled is not None
                and readback["obstacle_avoidance_enabled"] is not obstacle_avoidance_enabled
            ):
                mismatches.append("obstacle_avoidance_enabled")
            if auto_avoidance_enabled is not None and readback["auto_avoidance_enabled"] is not auto_avoidance_enabled:
                mismatches.append("auto_avoidance_enabled")
            if mismatches:
                raise RuntimeError(f"Behavior setting read-back mismatch: {', '.join(mismatches)}")
        except Exception:
            agent.set_enabled(before["enabled"])
            agent.set_speed(before["speed_stage_units_per_second"])
            agent.set_navmesh_areas_allowed(before["navigation_areas"])
            agent.set_obstacle_avoidance_enabled(before["obstacle_avoidance_enabled"])
            agent.set_auto_avoidance_enabled(before["auto_avoidance_enabled"])
            raise
        return {"status": "success", "preview": False, "changes": changes, "readback": readback}
    except Exception as exc:
        return _control_error(exc)


def get_navmesh_status(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    try:
        stage = adapter.get_stage()
        if stage is None:
            return _error("NO_STAGE", "No USD stage is open")
        import omni.anim.navigation.core as nav

        interface = nav.acquire_interface()
        volumes = sorted(str(prim.GetPath()) for prim in stage.TraverseAll() if prim.GetTypeName() == "NavMeshVolume")
        navmesh = interface.get_navmesh()
        return {
            "status": "success",
            "ready": navmesh is not None,
            "baking": bool(interface.is_navmesh_baking()),
            "volume_paths": volumes,
            "volume_count": len(volumes),
            "area_names": list(interface.get_area_names()),
            "prerequisites": {
                "has_volume": bool(volumes),
                "timeline_should_be_stopped_for_bake": True,
            },
        }
    except Exception as exc:
        return _error("NAVMESH_STATUS_FAILED", str(exc))


async def bake_navmesh(
    adapter: IsaacAdapterBase,
    max_frames: int = 2000,
    preview: bool = True,
    timeout_seconds: float = _NAVMESH_DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    try:
        if not isinstance(max_frames, int) or not 1 <= max_frames <= 10000:
            return _error("INVALID_HUMAN_REQUEST", "max_frames must be an integer from 1 to 10000")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 1 <= float(timeout_seconds) <= _NAVMESH_MAX_TIMEOUT_SECONDS
        ):
            return _error(
                "INVALID_HUMAN_REQUEST",
                f"timeout_seconds must be a number from 1 to {_NAVMESH_MAX_TIMEOUT_SECONDS:g}",
            )
        timeout_seconds = float(timeout_seconds)
        stage = adapter.get_stage()
        if stage is None:
            return _error("NO_STAGE", "No USD stage is open")
        volumes = sorted(str(prim.GetPath()) for prim in stage.TraverseAll() if prim.GetTypeName() == "NavMeshVolume")
        if not volumes:
            return _error(
                "NAVMESH_VOLUME_NOT_FOUND",
                "No NavMeshVolume exists. Create one that overlaps walkable collision geometry before baking.",
            )
        if adapter.get_simulation_state().get("timeline_state") == "playing":
            return _error("TIMELINE_STATE_CONFLICT", "Stop or pause the timeline before baking the NavMesh")
        if preview:
            return {
                "status": "success",
                "preview": True,
                "plan": {
                    "operation": "bake_navmesh",
                    "max_frames": max_frames,
                    "timeout_seconds": timeout_seconds,
                    "volume_paths": volumes,
                },
            }
        bake_result = await _wait_for_navmesh(
            max_frames=max_frames,
            force_rebake=True,
            timeout_seconds=timeout_seconds,
        )
        frames = bake_result["frames"]
        if not bake_result["ready"]:
            return _error(
                "NAVMESH_BAKE_FAILED",
                f"NavMesh baking did not produce a NavMesh after {frames} update frames ({bake_result['reason']})",
                readback={
                    "ready": False,
                    "bake_frames": frames,
                    "volume_paths": volumes,
                    "reason": bake_result["reason"],
                    "start_result": bake_result["start_result"],
                    "elapsed_seconds": bake_result["elapsed_seconds"],
                    "settle_frames": bake_result["settle_frames"],
                    "cancel_result": bake_result["cancel_result"],
                },
            )
        return {
            "status": "success",
            "preview": False,
            "message": "NavMesh bake completed",
            "readback": {
                "ready": True,
                "bake_frames": frames,
                "volume_paths": volumes,
                "reason": bake_result["reason"],
                "start_result": bake_result["start_result"],
                "elapsed_seconds": bake_result["elapsed_seconds"],
                "settle_frames": bake_result["settle_frames"],
                "cancel_result": bake_result["cancel_result"],
            },
        }
    except Exception as exc:
        return _error("NAVMESH_BAKE_FAILED", str(exc))


def delete_human(
    adapter: IsaacAdapterBase,
    human_path: str,
    delete_empty_group: bool = True,
    preview: bool = True,
) -> Dict[str, Any]:
    try:
        stage = adapter.get_stage()
        if stage is None:
            return _error("NO_STAGE", "No USD stage is open")
        prim, marker, agent_paths = _resolve_human(stage, human_path)
        if not marker:
            return _error("HUMAN_NOT_OWNED", "Delete is limited to humans created by this MCP")
        exact_path = str(prim.GetPath())
        parent_path = str(prim.GetParent().GetPath())
        group_path = str(marker.get("group_path") or parent_path)
        if group_path != parent_path:
            return _error("HUMAN_OWNERSHIP_MISMATCH", "The ownership marker group_path does not match the human parent")
        if adapter.get_simulation_state().get("timeline_state") == "playing":
            return _error("TIMELINE_STATE_CONFLICT", "Stop or pause the timeline before deleting a human")
        if preview:
            return {
                "status": "success",
                "preview": True,
                "plan": {
                    "delete_paths": [exact_path],
                    "delete_empty_group": delete_empty_group,
                    "group_path": group_path,
                },
            }

        import omni.kit.commands

        agent, _ = _acquire_behavior_agent(agent_paths)
        if agent:
            task_id = int(agent.get_action_task_id())
            if task_id >= 0 and agent.is_task_running(task_id):
                agent.cancel_task(task_id)
            agent.set_enabled(False)
        success, _ = omni.kit.commands.execute("DeletePrims", paths=[exact_path], destructive=False)
        if success is False or stage.GetPrimAtPath(exact_path).IsValid():
            return _error("HUMAN_DELETE_FAILED", f"Delete read-back failed for {exact_path}")

        deleted_group = False
        group = stage.GetPrimAtPath(group_path)
        if delete_empty_group and group and group.IsValid() and not list(group.GetChildren()):
            group_success, _ = omni.kit.commands.execute("DeletePrims", paths=[group_path], destructive=False)
            deleted_group = group_success is not False and not stage.GetPrimAtPath(group_path).IsValid()
        return {
            "status": "success",
            "preview": False,
            "deleted_human_path": exact_path,
            "deleted_empty_group": deleted_group,
            "readback": {"human_absent": not stage.GetPrimAtPath(exact_path).IsValid()},
        }
    except ValueError as exc:
        return _error("INVALID_HUMAN_REQUEST", str(exc))
    except LookupError as exc:
        return _error("HUMAN_NOT_FOUND", str(exc))
    except Exception as exc:
        return _error("HUMAN_DELETE_FAILED", str(exc))


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

        navmesh_result = await _wait_for_navmesh()
        navmesh_bake_frames = navmesh_result["frames"]
        if not navmesh_result["ready"]:
            return _error(
                "HUMAN_PREREQUISITE_MISSING",
                (
                    f"NavMesh baking did not produce a NavMesh after {navmesh_bake_frames} update frames. "
                    f"Runtime reason: {navmesh_result['reason']}. "
                    "Verify that the volume overlaps a walkable collision surface."
                ),
                blocked_by="bake_navmesh",
                navmesh_volume_path=navmesh_volume_path,
                navmesh_bake_frames=navmesh_bake_frames,
                navmesh_reason=navmesh_result["reason"],
                navmesh_start_result=navmesh_result["start_result"],
                navmesh_diagnostics={
                    "elapsed_seconds": navmesh_result["elapsed_seconds"],
                    "settle_frames": navmesh_result["settle_frames"],
                    "cancel_result": navmesh_result["cancel_result"],
                },
            )

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

        for created_path in created:
            created_prim = stage.GetPrimAtPath(created_path)
            if created_prim and created_prim.IsValid():
                created_prim.SetCustomDataByKey(
                    _MCP_HUMAN_KEY,
                    {
                        "schema": _MCP_HUMAN_SCHEMA,
                        "owner": "isaacsim-mcp",
                        "group_path": group_path,
                        "behavior": behavior.lower().strip(),
                    },
                )

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
            "navmesh_reason": navmesh_result["reason"],
            "navmesh_start_result": navmesh_result["start_result"],
            "behavior_agent_paths": behavior_agent_paths,
        }
        if warning:
            result["warning"] = warning
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}
