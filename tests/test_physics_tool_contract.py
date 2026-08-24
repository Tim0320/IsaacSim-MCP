"""Named MCP tool contract for task 3.3."""

from __future__ import annotations

import json

from isaac_mcp.tools.physics import register_tools


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    def __init__(self):
        self.calls = []

    def send_command(self, command, params=None):
        self.calls.append((command, params))
        return {"status": "success", "command": command}


def test_six_named_tools_are_registered_and_forward_parameters():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)
    assert set(mcp.tools) == {
        "configure_physics_body",
        "get_physics_body",
        "create_collision_group",
        "get_collision_group",
        "create_physics_joint",
        "get_physics_joint",
    }
    result = json.loads(mcp.tools["configure_physics_body"]("/World/Box", "dynamic", True, "convex_hull", 2.0, None))
    assert result["status"] == "success"
    assert connection.calls[-1] == (
        "physics.configure_body",
        {
            "prim_path": "/World/Box",
            "body_type": "dynamic",
            "collider_enabled": True,
            "approximation": "convex_hull",
            "mass_kg": 2.0,
        },
    )
