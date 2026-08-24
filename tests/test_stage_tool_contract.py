# MIT License
# Copyright (c) 2026 whats2000

"""Public MCP contracts for item 15 Stage/composition tools."""

from __future__ import annotations

import inspect
import json

from isaac_mcp.tools.scene import register_tools


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
        return {"status": "success", "data": {"command": command, "params": params or {}}}


def _registered():
    mcp, connection = _MCP(), _Connection()
    register_tools(mcp, lambda: connection)
    return mcp.tools, connection


def test_all_item_15_tools_are_named_and_registered():
    tools, _ = _registered()

    assert {
        "new_stage",
        "open_stage",
        "save_stage_as",
        "get_stage_composition",
        "edit_sublayer",
        "edit_composition_arc",
        "set_variant_selection",
        "get_semantic_labels",
        "set_semantic_labels",
        "get_typed_attribute",
        "set_typed_attribute",
        "apply_stage_batch",
    } <= tools.keys()


def test_lifecycle_tools_default_to_preview_and_fail_closed_flags():
    tools, connection = _registered()

    response = json.loads(tools["open_stage"]("D:/scratch/test.usda"))

    assert response["status"] == "success"
    command, params = connection.calls[-1]
    assert command == "stage.open"
    assert params == {
        "path": "D:/scratch/test.usda",
        "scratch_stage": False,
        "scratch_root": None,
        "preview": True,
        "readback_root_path": "/",
    }


def test_semantics_use_isaac_sim_6_labels_api_shape():
    tools, connection = _registered()

    tools["set_semantic_labels"]("/World/Box", "class", ["box", "obstacle"])

    command, params = connection.calls[-1]
    assert command == "stage.set_semantics"
    assert params["taxonomy"] == "class"
    assert params["labels"] == ["box", "obstacle"]
    assert params["overwrite"] is False
    assert params["preview"] is True


def test_typed_attribute_and_batch_keep_json_safe_public_types():
    tools, connection = _registered()

    signature = inspect.signature(tools["set_typed_attribute"])
    assert signature.parameters["value"].annotation is not inspect.Parameter.empty
    tools["set_typed_attribute"]("/World/Box", "mcp:weight", "double", 3.5, overwrite=True, preview=False)
    tools["apply_stage_batch"](
        [
            {
                "operation": "set_attribute",
                "prim_path": "/World/Box",
                "attribute": "mcp:tag",
                "type_name": "string",
                "value": "fixture",
            }
        ],
        preview=False,
    )

    assert connection.calls[-2][0] == "stage.set_attribute"
    assert connection.calls[-2][1]["value"] == 3.5
    assert connection.calls[-1][0] == "stage.apply_batch"
    assert connection.calls[-1][1]["preview"] is False
