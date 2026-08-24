"""Common response schema tests for extension, connection, and all named tools."""

from __future__ import annotations

import inspect
import json

from isaac_mcp.responses import normalize_response
from isaac_mcp.tools import register_all_tools

REQUIRED_FIELDS = {
    "schema_version",
    "status",
    "code",
    "message",
    "data",
    "warnings",
    "command_id",
    "timing",
    "artifacts",
    "readback",
}


def test_normalize_response_is_idempotent_and_classifies_legacy_results():
    partial = normalize_response(
        {
            "status": "error",
            "message": "Some settings are not supported",
            "applied": ["gravity"],
            "unsupported": ["time_step"],
        },
        command_id="command-1",
    )
    assert partial["status"] == "partial"
    assert partial["code"] == "PARTIAL_SUCCESS"
    assert partial["command_id"] == "command-1"
    assert normalize_response(partial) == partial

    unsupported = normalize_response({"status": "error", "message": "Not supported by adapter"})
    timeout = normalize_response({"status": "error", "message": "Timeout waiting for Isaac response"})
    cancelled = normalize_response({"status": "error", "message": "Request was cancelled"})
    assert unsupported["status"] == "unsupported"
    assert timeout["status"] == "timeout"
    assert cancelled["status"] == "cancelled"


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    port = 8766

    def send_command(self, command, params=None):
        return normalize_response(
            {"status": "success", "command": command, "params": params or {}},
            command_id=f"id-{command}",
        )


def test_all_98_named_tools_are_registered_through_schema_wrapper():
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: _Connection())

    assert len(mcp.tools) == 98
    for name, function in mcp.tools.items():
        assert inspect.signature(function), name
        assert getattr(function, "__wrapped__", None) is not None, name
        # Calling without arguments either runs a no-argument tool or triggers
        # the wrapper's validation error path. Both must still be schema 1.0.
        response = json.loads(function())
        assert set(response) == REQUIRED_FIELDS, name
        assert response["status"] in {
            "success",
            "error",
            "partial",
            "unsupported",
            "timeout",
            "cancelled",
        }, name


def test_schema_wrapper_returns_all_fields_for_success_and_legacy_error():
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: _Connection())

    success = json.loads(mcp.tools["get_scene_info"]())
    assert set(success) == REQUIRED_FIELDS
    assert success["status"] == "success"
    assert success["command_id"] == "id-scene.get_info"
    assert success["timing"]["mcp_tool_ms"] >= 0

    class _FailingConnection:
        def send_command(self, _command, _params=None):
            raise TimeoutError("timed out")

    failing_mcp = _FakeMCP()
    register_all_tools(failing_mcp, lambda: _FailingConnection())
    timeout = json.loads(failing_mcp.tools["get_scene_info"]())
    assert set(timeout) == REQUIRED_FIELDS
    assert timeout["status"] == "timeout"
    assert timeout["code"] == "TIMEOUT"
