"""MCP-facing object deletion lifecycle forwarding contract."""

from __future__ import annotations

import json

from isaac_mcp.tools.objects import register_tools


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
        return {"status": "success", "data": {}}


def test_delete_object_forwards_sensor_verification_window():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(mcp.tools["delete_object"]("/World/Camera", post_delete_updates=32))

    assert response["status"] == "success"
    assert connection.calls == [("objects.delete", {"prim_path": "/World/Camera", "post_delete_updates": 32})]
