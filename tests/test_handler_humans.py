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
from unittest.mock import MagicMock

import pytest
from isaac_sim_mcp_extension.handlers.humans import (
    _build_routines,
    _control_error,
    _ensure_navmesh_volume,
    _human_marker,
    _HumanTaskRejected,
    _one_target,
    _valid_absolute_prim_path,
    bake_navmesh,
    register,
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
