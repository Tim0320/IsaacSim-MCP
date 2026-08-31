"""Public MCP tool-profile contracts."""

from __future__ import annotations

import pytest

from isaac_mcp.tool_inventory import all_tool_names, tool_names
from isaac_mcp.tools import register_all_tools


class _FakeMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


def _registered(monkeypatch: pytest.MonkeyPatch, profile: str | None) -> set[str]:
    if profile is None:
        monkeypatch.delenv("ISAAC_MCP_TOOL_PROFILE", raising=False)
    else:
        monkeypatch.setenv("ISAAC_MCP_TOOL_PROFILE", profile)
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: None)
    return set(mcp.tools)


def test_default_profile_preserves_legacy_public_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _registered(monkeypatch, None) == set(tool_names("legacy"))
    assert len(tool_names("legacy")) == 129
    assert "list_prims" in tool_names("legacy")
    assert "query_prim" not in tool_names("legacy")


def test_consolidated_profile_replaces_legacy_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    names = _registered(monkeypatch, "consolidated")

    assert names == set(tool_names("consolidated"))
    assert len(names) < len(tool_names("legacy"))
    assert {"query_prim", "control_timeline", "create_ros2_publisher"} <= names
    assert {"list_prims", "get_prim_info", "play_simulation", "create_ros2_clock_publisher"}.isdisjoint(names)
    assert {"get_joint_state", "set_joint_command", "capture_camera_output"} <= names
    assert {"get_joint_positions", "set_joint_positions", "capture_image"}.isdisjoint(names)


def test_full_profile_exposes_migration_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _registered(monkeypatch, "full") == set(all_tool_names())


def test_unknown_tool_profile_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ISAAC_MCP_TOOL_PROFILE", "surprise")
    with pytest.raises(ValueError, match="ISAAC_MCP_TOOL_PROFILE"):
        register_all_tools(_FakeMCP(), lambda: None)


def test_real_fastmcp_consolidated_registration_matches_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp.server.fastmcp import FastMCP

    monkeypatch.setenv("ISAAC_MCP_TOOL_PROFILE", "consolidated")
    mcp = FastMCP("consolidated-registration-contract")

    register_all_tools(mcp, lambda: None)

    assert {tool.name for tool in mcp._tool_manager.list_tools()} == set(tool_names("consolidated"))
