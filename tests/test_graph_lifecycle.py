# MIT License
# Copyright (c) 2026 whats2000

"""Behavioral contracts for guarded OmniGraph lifecycle helpers."""

from __future__ import annotations

import sys
from types import ModuleType

from isaac_sim_mcp_extension.handlers import graphs


class _Adapter:
    def __init__(self, state: str = "stopped"):
        self.state = state

    def get_simulation_state(self):
        return {"timeline_state": self.state, "playing": self.state == "playing"}


class _Attribute:
    def __init__(self, path: str):
        self.path = path
        self.downstream = []

    def get_path(self):
        return self.path

    def get_downstream_connections(self):
        return list(self.downstream)


class _Graph:
    def __init__(self):
        self.disabled = False

    def is_valid(self):
        return True

    def is_disabled(self):
        return self.disabled

    def set_disabled(self, value):
        self.disabled = bool(value)


def _install_fake_og(monkeypatch, source, target):
    class _Keys:
        CONNECT = "connect"
        DISCONNECT = "disconnect"

    class _Controller:
        Keys = _Keys

        @staticmethod
        def edit(_graph_path, spec):
            if _Keys.CONNECT in spec:
                source.downstream[:] = [target]
            if _Keys.DISCONNECT in spec:
                source.downstream[:] = []

    omni = ModuleType("omni")
    omni.__path__ = []
    graph_package = ModuleType("omni.graph")
    graph_package.__path__ = []
    core = ModuleType("omni.graph.core")
    core.Controller = _Controller
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.graph", graph_package)
    monkeypatch.setitem(sys.modules, "omni.graph.core", core)


def test_register_exposes_complete_twelve_command_extension_surface():
    registry = {}

    graphs.register(registry, _Adapter())

    assert len(registry) == 12
    assert {
        "graphs.list_action_graphs",
        "graphs.get_action_graph",
        "graphs.delete_action_graph",
        "graphs.connect_action_graph",
        "graphs.disconnect_action_graph",
        "graphs.set_action_graph_enabled",
        "graphs.get_action_graph_status",
        "graphs.configure_script_node",
        "graphs.reload_script_node",
        "graphs.evaluate_action_graph",
    } <= set(registry)


def test_graph_writes_fail_closed_when_timeline_is_not_stopped(monkeypatch):
    monkeypatch.setattr(graphs, "_graph_or_none", lambda _path: _Graph())

    result = graphs.set_action_graph_enabled(_Adapter("paused"), "/World/G", True, preview=False)

    assert result["code"] == "TIMELINE_NOT_STOPPED"


def test_connect_and_disconnect_require_exact_readback(monkeypatch):
    graph = _Graph()
    source = _Attribute("/World/G/A.outputs:value")
    target = _Attribute("/World/G/B.inputs:value")
    _install_fake_og(monkeypatch, source, target)
    monkeypatch.setattr(graphs, "_graph_or_none", lambda _path: graph)
    monkeypatch.setattr(
        graphs,
        "_resolve_attribute",
        lambda _graph, _path, spec: source if "outputs:" in spec else target,
    )

    connected = graphs.connect_action_graph(_Adapter(), "/World/G", "A.outputs:value", "B.inputs:value", preview=False)
    duplicate = graphs.connect_action_graph(_Adapter(), "/World/G", "A.outputs:value", "B.inputs:value", preview=False)
    disconnected = graphs.disconnect_action_graph(
        _Adapter(), "/World/G", "A.outputs:value", "B.inputs:value", preview=False
    )

    assert connected["status"] == "success" and connected["readback"]["connection_present"] is True
    assert duplicate["code"] == "CONNECTION_ALREADY_EXISTS"
    assert disconnected["status"] == "success" and disconnected["readback"]["connection_present"] is False


def test_script_modes_are_explicit_and_mutually_exclusive(tmp_path):
    script = tmp_path / "controller.py"
    script.write_text("def compute(db): return True\n", encoding="utf-8")

    _, conflict = graphs._script_request("inline", "def compute(db): pass", str(script), require_source=True)
    file_request, file_error = graphs._script_request("file", None, str(script), require_source=True)
    _, missing = graphs._script_request("file", None, str(tmp_path / "missing.py"), require_source=True)

    assert conflict["code"] == "SCRIPT_MODE_CONFLICT"
    assert file_error is None and file_request["script_file"] == str(script.resolve())
    assert missing["code"] == "SCRIPT_FILE_NOT_FOUND"


def test_enabled_state_is_runtime_only_and_disable_is_emergency_safe(monkeypatch):
    graph = _Graph()
    monkeypatch.setattr(graphs, "_graph_or_none", lambda _path: graph)

    result = graphs.set_action_graph_enabled(_Adapter("playing"), "/World/G", False, preview=False)

    assert result["status"] == "success"
    assert result["readback"] == {"enabled": False, "runtime_state_persistent": False}
    assert graph.disabled is True
