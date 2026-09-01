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

"""Unit tests for the NVIDIA IRA human handler's runtime-independent contract."""

import asyncio
import sys
import types
from unittest.mock import MagicMock

import isaac_sim_mcp_extension.handlers.humans as humans
import pytest
from isaac_sim_mcp_extension.handlers.humans import (
    _build_routines,
    _control_error,
    _ensure_navmesh_volume,
    _human_marker,
    _HumanTaskRejected,
    _one_target,
    _valid_absolute_prim_path,
    _wait_for_navmesh,
    bake_navmesh,
    register,
    spawn,
)


def test_wander_routine_maps_mcp_parameters_to_ira_schema():
    result = _build_routines("wander", [0.8, 1.2], [2.0, 6.0], [1.0, 3.0], None)

    assert result == [
        {
            "wander": {
                "walk": {"speed_range": [0.8, 1.2], "distance_range": [2.0, 6.0]},
                "idle": [{"animation": "idle", "time_range": [1.0, 3.0]}],
            }
        }
    ]


def test_patrol_requires_points_and_preserves_xyz_values():
    with pytest.raises(ValueError, match="patrol_points"):
        _build_routines("patrol", None, None, None, None)

    result = _build_routines("patrol", [1, 1], None, None, [[1, 2, 0], [3, 4, 0]])
    assert result[0]["patrol"]["path_points"] == [[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]]


def test_stop_uses_idle_time_range():
    assert _build_routines("stop", None, None, [4, 7], None) == [{"stop": {"time_range": [4.0, 7.0]}}]


def test_manual_behavior_leaves_runtime_control_to_interaction_scripts():
    assert _build_routines("manual", None, None, None, None) == []


def test_unknown_behavior_fails_closed():
    with pytest.raises(ValueError, match="wander, patrol, stop, manual"):
        _build_routines("dance", None, None, None, None)


def test_navmesh_volume_fails_closed_without_explicit_auto_create():
    stage = MagicMock()
    stage.TraverseAll.return_value = []

    assert _ensure_navmesh_volume(MagicMock(), stage, False, None, None) == (None, False)


def test_navmesh_auto_create_requires_explicit_size():
    stage = MagicMock()
    stage.TraverseAll.return_value = []

    with pytest.raises(ValueError, match="navmesh_volume_size"):
        _ensure_navmesh_volume(MagicMock(), stage, True, None, None)


def test_item_19_registers_all_human_lifecycle_commands():
    registry = {}
    register(registry, MagicMock())

    assert {
        "humans.spawn",
        "humans.list",
        "humans.get",
        "humans.delete",
        "humans.set_target",
        "humans.look_at",
        "humans.idle",
        "humans.set_behavior",
        "humans.navmesh_status",
        "humans.bake_navmesh",
    } <= registry.keys()


@pytest.mark.parametrize("path", ["World/Human", "/", "/World/Bad Name", "/World/123bad"])
def test_human_paths_fail_closed(path):
    assert _valid_absolute_prim_path(path) is False


def test_target_contract_requires_exactly_one_target():
    with pytest.raises(ValueError, match="exactly one"):
        _one_target(None, None, "target_position")
    with pytest.raises(ValueError, match="exactly one"):
        _one_target([1, 2, 3], "/World/Target", "target_position")


def test_ownership_marker_requires_exact_owner_and_schema():
    prim = MagicMock()
    prim.GetCustomDataByKey.return_value = {"owner": "someone-else", "schema": "1.0"}
    assert _human_marker(prim) is None
    prim.GetCustomDataByKey.return_value = {"owner": "isaacsim-mcp", "schema": "2.0"}
    assert _human_marker(prim) is None
    marker = {"owner": "isaacsim-mcp", "schema": "1.0", "group_path": "/World/Characters/Group"}
    prim.GetCustomDataByKey.return_value = marker
    assert _human_marker(prim) == marker


def test_rejected_behavior_task_has_stable_error_code():
    result = _control_error(_HumanTaskRejected("not reachable"))

    assert result["code"] == "HUMAN_TASK_REJECTED"


def test_navmesh_bake_validates_bound_before_touching_runtime():
    result = asyncio.run(bake_navmesh(MagicMock(), max_frames=0, preview=False))

    assert result["status"] == "error"
    assert result["code"] == "INVALID_HUMAN_REQUEST"


def _install_navmesh_runtime(monkeypatch, interface):
    updates = []

    class _App:
        async def next_update_async(self):
            updates.append("update")

    nav = types.ModuleType("omni.anim.navigation.core")
    nav.acquire_interface = lambda: interface
    kit_app = types.ModuleType("omni.kit.app")
    kit_app.get_app = lambda: _App()
    omni = types.ModuleType("omni")
    omni_anim = types.ModuleType("omni.anim")
    omni_navigation = types.ModuleType("omni.anim.navigation")
    omni_kit = types.ModuleType("omni.kit")
    omni.anim = omni_anim
    omni.kit = omni_kit
    omni_anim.navigation = omni_navigation
    omni_navigation.core = nav
    omni_kit.app = kit_app
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.anim", omni_anim)
    monkeypatch.setitem(sys.modules, "omni.anim.navigation", omni_navigation)
    monkeypatch.setitem(sys.modules, "omni.anim.navigation.core", nav)
    monkeypatch.setitem(sys.modules, "omni.kit", omni_kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", kit_app)
    return updates


def test_wait_for_navmesh_reports_explicit_start_rejection(monkeypatch):
    interface = MagicMock()
    interface.get_navmesh.return_value = None
    interface.is_navmesh_baking.return_value = False
    interface.start_navmesh_baking.return_value = False
    updates = _install_navmesh_runtime(monkeypatch, interface)

    result = asyncio.run(_wait_for_navmesh(max_frames=10, force_rebake=True))

    assert result == {
        "ready": False,
        "frames": 0,
        "reason": "start_rejected",
        "start_result": False,
    }
    assert len(updates) == 5


def test_wait_for_navmesh_reports_native_completion_without_navmesh(monkeypatch):
    interface = MagicMock()
    interface.get_navmesh.return_value = None
    interface.is_navmesh_baking.side_effect = [False, False]
    interface.start_navmesh_baking.return_value = True
    updates = _install_navmesh_runtime(monkeypatch, interface)

    result = asyncio.run(_wait_for_navmesh(max_frames=10, force_rebake=True))

    assert result == {
        "ready": False,
        "frames": 1,
        "reason": "completed_without_navmesh",
        "start_result": True,
    }
    assert len(updates) == 6


def test_wait_for_navmesh_reports_successful_frame_count(monkeypatch):
    interface = MagicMock()
    navmesh = object()
    interface.get_navmesh.side_effect = [None, None, None, navmesh]
    interface.is_navmesh_baking.side_effect = [False, True, True]
    interface.start_navmesh_baking.return_value = None
    updates = _install_navmesh_runtime(monkeypatch, interface)

    result = asyncio.run(_wait_for_navmesh(max_frames=10, force_rebake=True))

    assert result == {
        "ready": True,
        "frames": 3,
        "reason": "ready",
        "start_result": None,
    }
    assert len(updates) == 8


def test_bake_navmesh_exposes_native_failure_diagnostics(monkeypatch):
    stage = MagicMock()
    volume = MagicMock()
    volume.GetPath.return_value = "/World/NavMeshVolume"
    volume.GetTypeName.return_value = "NavMeshVolume"
    stage.TraverseAll.return_value = [volume]
    adapter = MagicMock()
    adapter.get_stage.return_value = stage
    adapter.get_simulation_state.return_value = {"timeline_state": "stopped"}

    async def _failed_wait(**_kwargs):
        return {
            "ready": False,
            "frames": 1,
            "reason": "completed_without_navmesh",
            "start_result": True,
        }

    monkeypatch.setattr(humans, "_wait_for_navmesh", _failed_wait)

    result = asyncio.run(bake_navmesh(adapter, max_frames=10, preview=False))

    assert result["code"] == "NAVMESH_BAKE_FAILED"
    assert result["readback"]["reason"] == "completed_without_navmesh"
    assert result["readback"]["start_result"] is True


def test_spawn_exposes_navmesh_failure_diagnostics(monkeypatch):
    character = types.ModuleType("isaacsim.replicator.agent.core.configuration.models.character")
    character.CharacterConfig = object
    randomizer = types.ModuleType("isaacsim.replicator.agent.core.randomizer")
    randomizer.Randomizer = object
    scene_assembly = types.ModuleType("isaacsim.replicator.agent.core.scene_assembly")
    scene_assembly.CharacterLoader = object
    monkeypatch.setitem(sys.modules, character.__name__, character)
    monkeypatch.setitem(sys.modules, randomizer.__name__, randomizer)
    monkeypatch.setitem(sys.modules, scene_assembly.__name__, scene_assembly)

    stage = MagicMock()
    adapter = MagicMock()
    adapter.get_stage.return_value = stage
    adapter.get_simulation_state.return_value = {"timeline_state": "stopped"}

    async def _enabled():
        return True, "C:/isaacsim/exts/ira"

    async def _failed_wait(**_kwargs):
        return {
            "ready": False,
            "frames": 1,
            "reason": "completed_without_navmesh",
            "start_result": True,
        }

    monkeypatch.setattr(humans, "_enable_ira_core", _enabled)
    monkeypatch.setattr(humans, "_ensure_navmesh_volume", lambda *_args: ("/World/NavMeshVolume", False))
    monkeypatch.setattr(humans, "_wait_for_navmesh", _failed_wait)

    result = asyncio.run(spawn(adapter))

    assert result["status"] == "error"
    assert result["navmesh_reason"] == "completed_without_navmesh"
    assert result["navmesh_start_result"] is True
