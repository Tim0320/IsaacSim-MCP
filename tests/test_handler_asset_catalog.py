# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Unit tests for the NVIDIA asset catalog handler."""

from unittest.mock import MagicMock, patch

from isaac_sim_mcp_extension.handlers.assets import (
    NVIDIA_ASSET_CATALOG,
    _classify_robot,
    list_nvidia_assets,
    spawn_nvidia_asset,
)


def _adapter():
    adapter = MagicMock()
    adapter.get_simulation_state.return_value = {"timeline_state": "paused"}
    adapter.get_assets_root_path.return_value = "https://example.test/Assets/Isaac/6.0"
    adapter.get_stage.return_value.GetPrimAtPath.return_value.IsValid.return_value = False
    return adapter


def test_catalog_covers_requested_non_robot_categories():
    categories = {entry["category"] for entry in NVIDIA_ASSET_CATALOG.values()}
    assert {"conveyor", "warehouse", "factory", "vegetation", "lifting", "instrumentation"} <= categories


def test_lifting_and_instrument_assets_include_official_thumbnails():
    for key in ("cargo_crane", "portable_gantry_crane", "oscilloscope_a01", "wheel_alignment_scanner"):
        entry = NVIDIA_ASSET_CATALOG[key]
        assert entry["thumbnail_path"].endswith(".usd.png")


def test_robot_classifier_separates_arms_quadrupeds_and_agvs():
    assert _classify_robot("frankapanda", {"description": "Franka Panda"}) == "robot_arm"
    assert _classify_robot("spot", {"description": "Boston Dynamics Spot"}) == "quadruped"
    assert _classify_robot("syncro10", {"description": "Addverb Syncro10 AMR"}) == "agv"


def test_list_filters_live_robot_and_curated_catalog():
    adapter = _adapter()
    robots = {
        "spot": {
            "description": "Boston Dynamics Spot",
            "manufacturer": "BostonDynamics",
            "asset_path": "/Isaac/Robots/BostonDynamics/spot/spot.usd",
        }
    }
    with patch("isaac_sim_mcp_extension.handlers.robots._get_robot_library", return_value=robots):
        result = list_nvidia_assets(adapter, category="quadruped")

    assert result["status"] == "success"
    assert result["match_count"] == 1
    assert result["assets"][0]["key"] == "spot"
    assert "locomotion policy" in result["assets"][0]["interaction_note"]


def test_list_returns_resolved_thumbnail_url_for_instrument():
    adapter = _adapter()
    with patch("isaac_sim_mcp_extension.handlers.robots._get_robot_library", return_value={}):
        result = list_nvidia_assets(adapter, category="instrumentation", query="oscilloscope")

    assert result["status"] == "success"
    assert result["match_count"] == 1
    assert result["assets"][0]["key"] == "oscilloscope_a01"
    assert result["assets"][0]["thumbnail_url"].startswith("https://example.test/Assets/Isaac/6.0/")


def test_spawn_curated_asset_resolves_isaac_root_and_transform():
    adapter = _adapter()
    with patch("isaac_sim_mcp_extension.handlers.robots._get_robot_library", return_value={}):
        result = spawn_nvidia_asset(
            adapter,
            asset_key="conveyor_a01",
            prim_path="/World/Assets/TestConveyor",
            position=[1, 2, 0],
        )

    assert result["status"] == "success"
    assert result["category"] == "conveyor"
    assert result["control_tool"] == "create_action_graph / reload_script / execute_script"
    adapter.add_reference_to_stage.assert_called_once_with(
        "https://example.test/Assets/Isaac/6.0/Isaac/Props/Conveyors/ConveyorBelt_A01.usd",
        "/World/Assets/TestConveyor",
    )
    adapter.set_prim_transform.assert_called_once_with(
        "/World/Assets/TestConveyor", position=[1, 2, 0], rotation=None, scale=None
    )


def test_spawn_fails_closed_while_timeline_is_playing():
    adapter = _adapter()
    adapter.get_simulation_state.return_value = {"timeline_state": "playing"}

    result = spawn_nvidia_asset(adapter, asset_key="boxwood_shrub")

    assert result["status"] == "error"
    assert "pause" in result["message"].lower()
