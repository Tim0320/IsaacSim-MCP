#!/usr/bin/env python3
"""Guarded live acceptance for Task 4.4 IRA human lifecycle control."""

from __future__ import annotations

import json
import math
import time

from isaac_mcp.connection import IsaacConnection
from isaac_mcp.tool_inventory import extension_tool_count

ROOT = "/World/MCP_Task_4_4"
HUMAN_ROOT = f"{ROOT}/Characters"
GROUP = "MCPHumans"
FLOOR = f"{ROOT}/Floor"
VOLUME = f"{ROOT}/NavMeshVolume"
TARGET_PRIM = f"{ROOT}/Target"
ORIGIN = [50.0, 0.0, 0.2]
TARGET = [53.0, 0.0, 0.2]


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    assert response["schema_version"] == "1.0", response
    return response["data"]


def _fixture(connection: IsaacConnection) -> None:
    code = f'''
import omni.usd
import omni.physxcommands
from omni.anim.navigation.core.scripts.command import NAVMESH_VOLUME_INCLUDE, CreateNavMeshVolumeCommand
from pxr import Gf, Sdf, UsdGeom
stage = omni.usd.get_context().get_stage()
root = UsdGeom.Xform.Define(stage, "{ROOT}").GetPrim()
target = UsdGeom.Xform.Define(stage, "{TARGET_PRIM}").GetPrim()
UsdGeom.XformCommonAPI(target).SetTranslate(Gf.Vec3d(*{TARGET!r}))
up_axis = UsdGeom.GetStageUpAxis(stage)
meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
omni.physxcommands.AddGroundPlaneCommand.execute(
    stage, "{FLOOR}", up_axis, 20.0 / meters_per_unit, Gf.Vec3f(50.0, 0.0, 0.0), Gf.Vec3f(0.5)
)
CreateNavMeshVolumeCommand(
    parent_prim_path=Sdf.Path("{ROOT}"), volume_type=NAVMESH_VOLUME_INCLUDE
).do()
volume_prim = stage.GetPrimAtPath("{VOLUME}")
UsdGeom.XformCommonAPI(volume_prim).SetTranslate(Gf.Vec3d(50.0, 0.0, 2.0))
UsdGeom.XformCommonAPI(volume_prim).SetScale(Gf.Vec3f(20.0, 20.0, 4.0))
'''
    _data(connection.send_command("simulation.execute_script", {"code": code}))
    assert _data(connection.send_command("scene.get_prim_info", {"prim_path": FLOOR}))["path"] == FLOOR
    assert _data(connection.send_command("scene.get_prim_info", {"prim_path": VOLUME}))["type"] == "NavMeshVolume"


def _human(connection: IsaacConnection, human_path: str) -> dict:
    return _data(connection.send_command("humans.get", {"human_path": human_path}))["human"]


def _wait_agent(connection: IsaacConnection, human_path: str, timeout: float = 20.0) -> dict:
    deadline = time.perf_counter() + timeout
    last = None
    while time.perf_counter() < deadline:
        last = _human(connection, human_path)
        if last["behavior_agent_ready"]:
            return last
        time.sleep(0.05)
    raise TimeoutError(f"Behavior Agent did not initialize: {last}")


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def main() -> int:
    connection = IsaacConnection(port=8766)
    evidence: dict = {}
    human_path = None
    original_paths: list[str] = []
    try:
        _data(connection.send_command("simulation.stop"))
        state_before = _data(connection.send_command("simulation.get_state"))
        assert state_before["timeline_state"] == "stopped", state_before
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["extension"]["command_count"] == extension_tool_count(), capabilities["extension"]
        assert capabilities["feature_flags"]["human.lifecycle"]["state"] == "supported"
        original = _data(connection.send_command("humans.list", {"root_prim_path": "/World", "include_external": True}))
        original_paths = [item["human_path"] for item in original["humans"]]

        if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))
        _fixture(connection)

        status_before = _data(connection.send_command("humans.navmesh_status"))
        assert VOLUME in status_before["volume_paths"]
        bake_preview = _data(connection.send_command("humans.bake_navmesh", {"max_frames": 2000, "preview": True}))
        assert bake_preview["preview"] is True
        baked = connection.send_command("humans.bake_navmesh", {"max_frames": 2000, "preview": False})
        _data(baked)
        baked_readback = baked["readback"]
        assert baked_readback["ready"] is True, baked

        spawned = _data(
            connection.send_command(
                "humans.spawn",
                {
                    "count": 1,
                    "group_name": GROUP,
                    "root_prim_path": HUMAN_ROOT,
                    "behavior": "manual",
                    "position": ORIGIN,
                    "seed": 4401,
                },
            )
        )
        assert len(spawned["created_prim_paths"]) == 1, spawned
        human_path = spawned["created_prim_paths"][0]
        listed = _data(connection.send_command("humans.list", {"root_prim_path": ROOT, "include_external": True}))
        listed_item = next(item for item in listed["humans"] if item["human_path"] == human_path)
        assert listed_item["mcp_owned"] is True and listed_item["marker_schema"] == "1.0", listed_item

        target_preview = _data(
            connection.send_command(
                "humans.set_target",
                {"human_path": human_path, "target_prim_path": TARGET_PRIM, "speed_mps": 1.0, "preview": True},
            )
        )
        assert target_preview["preview"] is True
        stopped_rejection = connection.send_command(
            "humans.set_target",
            {"human_path": human_path, "target_prim_path": TARGET_PRIM, "speed_mps": 1.0, "preview": False},
        )
        assert stopped_rejection["status"] == "error" and stopped_rejection["code"] == "TIMELINE_STATE_CONFLICT"

        _data(connection.send_command("simulation.play"))
        initialized = _wait_agent(connection, human_path)
        time.sleep(1.0)
        position_before = initialized["runtime"]["position"]
        behavior_response = connection.send_command(
            "humans.set_behavior",
            {
                "human_path": human_path,
                "speed_mps": 1.0,
                "obstacle_avoidance_enabled": True,
                "preview": False,
            },
        )
        _data(behavior_response)
        assert behavior_response["readback"]["obstacle_avoidance_enabled"] is True
        moved_task = _data(
            connection.send_command(
                "humans.set_target",
                {"human_path": human_path, "target_prim_path": TARGET_PRIM, "speed_mps": 1.0, "preview": False},
            )
        )
        assert moved_task["task"]["task_name"] == "MoveTo", moved_task

        movement_deadline = time.perf_counter() + 12.0
        moved = None
        while time.perf_counter() < movement_deadline:
            moved = _human(connection, human_path)
            if _distance(moved["runtime"]["position"], position_before) >= 0.25:
                break
            time.sleep(0.1)
        assert moved and _distance(moved["runtime"]["position"], position_before) >= 0.25, moved

        looked = _data(
            connection.send_command(
                "humans.look_at",
                {"human_path": human_path, "target_prim_path": TARGET_PRIM, "duration_seconds": 1.0, "preview": False},
            )
        )
        assert looked["task"]["task_name"] == "LookAt", looked
        idled = _data(connection.send_command("humans.idle", {"human_path": human_path, "preview": False}))
        assert idled["task"]["task_name"] == "Idle", idled
        _data(connection.send_command("simulation.stop"))

        delete_preview = _data(connection.send_command("humans.delete", {"human_path": human_path, "preview": True}))
        assert delete_preview["preview"] is True
        deleted = connection.send_command("humans.delete", {"human_path": human_path, "preview": False})
        _data(deleted)
        assert deleted["readback"]["human_absent"] is True
        human_path = None

        evidence = {
            "status": "success",
            "command_count": capabilities["extension"]["command_count"],
            "extensions": {
                name: capabilities["extensions"][name]
                for name in capabilities["feature_flags"]["human.lifecycle"]["required_extensions"]
            },
            "navmesh": baked_readback,
            "spawned": spawned["created_prim_paths"],
            "ownership": {"mcp_owned": True, "marker_schema": "1.0"},
            "stopped_task_rejection": stopped_rejection["code"],
            "move": {
                "task": moved_task["task"],
                "distance_observed": _distance(moved["runtime"]["position"], position_before),
            },
            "look_task": looked["task"],
            "idle_task": idled["task"],
            "delete_readback": deleted["readback"],
        }
    finally:
        _data(connection.send_command("simulation.stop"))
        if human_path:
            response = connection.send_command("humans.delete", {"human_path": human_path, "preview": False})
            if response["status"] != "success" and response.get("code") not in {"HUMAN_NOT_FOUND"}:
                raise RuntimeError(response)
        if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))
        assert connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "error"
        restored = _data(connection.send_command("humans.list", {"root_prim_path": "/World", "include_external": True}))
        restored_paths = [item["human_path"] for item in restored["humans"]]
        assert restored_paths == original_paths, {"before": original_paths, "after": restored_paths}
        final_state = _data(connection.send_command("simulation.get_state"))
        assert final_state["timeline_state"] == "stopped", final_state
        evidence["fixture_absent"] = True
        evidence["human_list_restored"] = True
        evidence["timeline_after"] = final_state["timeline_state"]
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
