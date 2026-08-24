# MIT License
# Copyright (c) 2026 whats2000

"""Public MCP contracts for item 16 Action Graph lifecycle tools."""

from __future__ import annotations

import inspect
import json

from isaac_mcp.tools.graphs import register_tools


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


ITEM_16_TOOLS = {
    "list_action_graphs",
    "get_action_graph",
    "delete_action_graph",
    "connect_action_graph",
    "disconnect_action_graph",
    "set_action_graph_enabled",
    "get_action_graph_status",
    "evaluate_action_graph",
    "configure_script_node",
    "reload_script_node",
}


def test_all_item_16_tools_are_named_and_registered():
    tools, _ = _registered()

    assert ITEM_16_TOOLS <= tools.keys()


def test_read_tools_forward_exact_defaults():
    tools, connection = _registered()

    json.loads(tools["list_action_graphs"]())
    json.loads(tools["get_action_graph"]("/World/ControlGraph"))
    json.loads(tools["get_action_graph_status"]("/World/ControlGraph"))
    json.loads(tools["evaluate_action_graph"]("/World/ControlGraph"))

    assert connection.calls == [
        ("graphs.list_action_graphs", {"root_path": "/World", "include_disabled": True}),
        (
            "graphs.get_action_graph",
            {
                "graph_path": "/World/ControlGraph",
                "include_values": False,
                "include_script_source": False,
            },
        ),
        ("graphs.get_action_graph_status", {"graph_path": "/World/ControlGraph"}),
        ("graphs.evaluate_action_graph", {"graph_path": "/World/ControlGraph"}),
    ]


def test_graph_mutations_default_to_preview_and_forward_exact_edges():
    tools, connection = _registered()

    tools["delete_action_graph"]("/World/ControlGraph")
    tools["connect_action_graph"](
        "/World/ControlGraph",
        "Tick.outputs:tick",
        "Script.inputs:execIn",
    )
    tools["disconnect_action_graph"](
        "/World/ControlGraph",
        "Tick.outputs:tick",
        "Script.inputs:execIn",
        preview=False,
    )
    tools["set_action_graph_enabled"]("/World/ControlGraph", False)

    assert connection.calls == [
        ("graphs.delete_action_graph", {"graph_path": "/World/ControlGraph", "preview": True}),
        (
            "graphs.connect_action_graph",
            {
                "graph_path": "/World/ControlGraph",
                "source_attr": "Tick.outputs:tick",
                "target_attr": "Script.inputs:execIn",
                "preview": True,
            },
        ),
        (
            "graphs.disconnect_action_graph",
            {
                "graph_path": "/World/ControlGraph",
                "source_attr": "Tick.outputs:tick",
                "target_attr": "Script.inputs:execIn",
                "preview": False,
            },
        ),
        (
            "graphs.set_action_graph_enabled",
            {"graph_path": "/World/ControlGraph", "enabled": False, "preview": True},
        ),
    ]


def test_configure_script_node_forwards_only_the_selected_mode_source():
    tools, connection = _registered()

    tools["configure_script_node"](
        "/World/ControlGraph",
        mode="inline",
        inline_script="def compute(db): return True",
    )
    tools["configure_script_node"](
        "/World/ControlGraph",
        node_path="Controller",
        mode="file",
        script_file="D:/scratch/controller.py",
        preview=False,
    )

    assert connection.calls == [
        (
            "graphs.configure_script_node",
            {
                "graph_path": "/World/ControlGraph",
                "node_path": "ScriptNode",
                "mode": "inline",
                "inline_script": "def compute(db): return True",
                "preview": True,
            },
        ),
        (
            "graphs.configure_script_node",
            {
                "graph_path": "/World/ControlGraph",
                "node_path": "Controller",
                "mode": "file",
                "script_file": "D:/scratch/controller.py",
                "preview": False,
            },
        ),
    ]


def test_reload_script_node_omits_optional_values_when_unspecified():
    tools, connection = _registered()

    tools["reload_script_node"]("/World/ControlGraph")
    tools["reload_script_node"](
        "/World/ControlGraph",
        mode="file",
        script_file="D:/scratch/controller.py",
        preview=False,
    )

    assert connection.calls == [
        (
            "graphs.reload_script_node",
            {"graph_path": "/World/ControlGraph", "node_path": "ScriptNode", "preview": True},
        ),
        (
            "graphs.reload_script_node",
            {
                "graph_path": "/World/ControlGraph",
                "node_path": "ScriptNode",
                "mode": "file",
                "script_file": "D:/scratch/controller.py",
                "preview": False,
            },
        ),
    ]


def test_script_node_signatures_expose_explicit_inline_and_file_modes():
    tools, _ = _registered()

    configure = inspect.signature(tools["configure_script_node"])
    reload_ = inspect.signature(tools["reload_script_node"])
    assert configure.parameters["mode"].default == "inline"
    assert reload_.parameters["mode"].default is None
    assert {"inline_script", "script_file", "preview"} <= configure.parameters.keys()
    assert {"inline_script", "script_file", "preview"} <= reload_.parameters.keys()
