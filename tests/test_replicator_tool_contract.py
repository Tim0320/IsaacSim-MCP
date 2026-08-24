"""Public Replicator tool signatures and forwarding contract."""

import json

from isaac_mcp.tools.replicator import register_tools


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
        self.calls.append((command, params or {}))
        return {"status": "success", "command": command, "params": params or {}}


def test_registers_seven_named_tools_and_forwards_typed_job_config():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    assert set(mcp.tools) == {
        "get_replicator_status",
        "create_sdg_job",
        "start_sdg_job",
        "get_sdg_job_status",
        "cancel_sdg_job",
        "get_sdg_manifest",
        "delete_sdg_job",
    }
    result = json.loads(
        mcp.tools["create_sdg_job"](
            "/World/Camera",
            3,
            ["rgb", "semantic_segmentation"],
            resolution=[320, 240],
            seed=42,
            randomizers=[
                {
                    "type": "transform",
                    "prim_paths": ["/World/Cube"],
                    "position_min": [-1, 0, 0],
                    "position_max": [1, 0, 0],
                }
            ],
            preview=False,
        )
    )

    assert result["command"] == "replicator.create_job"
    assert connection.calls[-1][1]["seed"] == 42
    assert connection.calls[-1][1]["preview"] is False
    assert connection.calls[-1][1]["randomizers"][0]["type"] == "transform"


def test_write_tools_preview_by_default_and_lifecycle_commands_are_stable():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    json.loads(mcp.tools["start_sdg_job"]("sdg-1"))
    json.loads(mcp.tools["cancel_sdg_job"]("sdg-1"))
    json.loads(mcp.tools["delete_sdg_job"]("sdg-1"))
    json.loads(mcp.tools["get_sdg_job_status"]("sdg-1"))
    json.loads(mcp.tools["get_sdg_manifest"]("sdg-1"))

    assert connection.calls == [
        ("replicator.start_job", {"job_id": "sdg-1", "preview": True}),
        ("replicator.cancel_job", {"job_id": "sdg-1", "preview": True}),
        ("replicator.delete_job", {"job_id": "sdg-1", "delete_artifacts": False, "preview": True}),
        ("replicator.get_job_status", {"job_id": "sdg-1"}),
        ("replicator.get_manifest", {"job_id": "sdg-1"}),
    ]
