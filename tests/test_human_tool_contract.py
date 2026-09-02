# MIT License
# Copyright (c) 2026 whats2000

"""Public MCP contracts for item 19 human lifecycle tools."""

from __future__ import annotations

import json

from isaac_mcp.tools.humans import register_tools


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorate(function):
            self.tools[name] = function
            return function

        return decorate


class _Connection:
    def __init__(self):
        self.calls = []

    def send_command(self, command, params=None):
        self.calls.append((command, params or {}))
        return {"status": "success"}


def _registered():
    mcp, connection = _MCP(), _Connection()
    register_tools(mcp, lambda: connection)
    return mcp.tools, connection


ITEM_19_TOOLS = {
    "list_humans",
    "get_human",
    "delete_human",
    "set_human_target",
    "set_human_look_at",
    "set_human_idle",
    "set_human_behavior",
    "get_navmesh_status",
    "bake_navmesh",
}


def test_item_19_named_tools_are_registered():
    tools, _ = _registered()
    assert ITEM_19_TOOLS <= tools.keys()


def test_read_and_delete_contracts_forward_exact_defaults():
    tools, connection = _registered()

    json.loads(tools["list_humans"]())
    json.loads(tools["get_human"]("/World/Characters/MCPHumans/Character_01"))
    json.loads(tools["delete_human"]("/World/Characters/MCPHumans/Character_01"))
    json.loads(tools["get_navmesh_status"]())
    json.loads(tools["bake_navmesh"]())

    assert connection.calls == [
        ("humans.list", {"root_prim_path": "/World/Characters", "include_external": True}),
        ("humans.get", {"human_path": "/World/Characters/MCPHumans/Character_01"}),
        (
            "humans.delete",
            {
                "human_path": "/World/Characters/MCPHumans/Character_01",
                "delete_empty_group": True,
                "preview": True,
            },
        ),
        ("humans.navmesh_status", {}),
        (
            "humans.bake_navmesh",
            {"max_frames": 2000, "timeout_seconds": 120.0, "preview": True},
        ),
    ]


def test_bake_navmesh_forwards_explicit_timeout():
    tools, connection = _registered()

    tools["bake_navmesh"](max_frames=400, timeout_seconds=30, preview=False)

    assert connection.calls == [
        (
            "humans.bake_navmesh",
            {"max_frames": 400, "timeout_seconds": 30, "preview": False},
        )
    ]


def test_task_tools_default_to_preview_and_omit_unspecified_targets():
    tools, connection = _registered()

    tools["set_human_target"]("/World/H", target_position=[1, 2, 0], speed_mps=1.25)
    tools["set_human_look_at"]("/World/H", target_prim_path="/World/Target", preview=False)
    tools["set_human_idle"]("/World/H")

    assert connection.calls == [
        (
            "humans.set_target",
            {
                "human_path": "/World/H",
                "target_position": [1, 2, 0],
                "speed_mps": 1.25,
                "auto_brake": True,
                "preview": True,
            },
        ),
        (
            "humans.look_at",
            {
                "human_path": "/World/H",
                "target_prim_path": "/World/Target",
                "duration_seconds": 0.0,
                "preview": False,
            },
        ),
        ("humans.idle", {"human_path": "/World/H", "preview": True}),
    ]


def test_behavior_tool_forwards_only_explicit_settings():
    tools, connection = _registered()

    tools["set_human_behavior"](
        "/World/H",
        enabled=False,
        navigation_areas=["FactoryFloor"],
        preview=False,
    )

    assert connection.calls == [
        (
            "humans.set_behavior",
            {
                "human_path": "/World/H",
                "enabled": False,
                "navigation_areas": ["FactoryFloor"],
                "preview": False,
            },
        )
    ]
