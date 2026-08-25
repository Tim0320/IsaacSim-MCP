"""Public MCP forwarding contract for unified job tools."""

import json

from isaac_mcp.tools.jobs import register_tools


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
        return {"status": "success", "command": command, "params": params}


def test_four_named_tools_forward_typed_contract():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    started = json.loads(mcp.tools["start_job"]("sensors.capture_image", {"prim_path": "/World/Camera"}, 5000))
    json.loads(mcp.tools["get_job_status"]("job-1"))
    json.loads(mcp.tools["cancel_job"]("job-1"))
    json.loads(mcp.tools["list_jobs"](10, False))

    assert started["command"] == "job.start"
    assert connection.calls == [
        (
            "job.start",
            {
                "command_type": "sensors.capture_image",
                "params": {"prim_path": "/World/Camera"},
                "deadline_ms": 5000,
            },
        ),
        ("job.get_status", {"job_id": "job-1"}),
        ("job.cancel", {"job_id": "job-1"}),
        ("job.list", {"count": 10, "include_terminal": False}),
    ]
