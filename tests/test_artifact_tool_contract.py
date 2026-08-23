"""MCP-facing Task 1.5 artifact tool forwarding contract."""

from __future__ import annotations

import json

from isaac_mcp.tools.artifacts import register_tools


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

    def send_command(self, command, params):
        self.calls.append((command, params))
        return {"status": "success"}


def test_artifact_tools_forward_exact_commands():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)
    handle = "artifact://managed/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    assert json.loads(mcp.tools["get_artifact_info"](handle))["status"] == "success"
    assert json.loads(mcp.tools["read_artifact"](handle, offset=4, length=8))["status"] == "success"
    assert json.loads(mcp.tools["delete_artifact"](handle))["status"] == "success"
    assert json.loads(mcp.tools["cleanup_artifacts"]())["status"] == "success"
    assert connection.calls == [
        ("artifacts.info", {"handle": handle}),
        ("artifacts.read", {"handle": handle, "offset": 4, "length": 8}),
        ("artifacts.delete", {"handle": handle}),
        ("artifacts.cleanup", {}),
    ]
