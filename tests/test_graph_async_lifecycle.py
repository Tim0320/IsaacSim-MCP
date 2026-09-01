# MIT License
# Copyright (c) 2026 whats2000

"""Regression tests for Action Graph mutation lifecycle on Kit's asyncio loop."""

from __future__ import annotations

import asyncio
import inspect
import sys
from types import ModuleType

from isaac_sim_mcp_extension.handlers import graphs, ros2


class _StoppedAdapter:
    def get_simulation_state(self):
        return {"timeline_state": "stopped", "playing": False}


class _Prim:
    def __init__(self, state):
        self._state = state

    def __bool__(self):
        return True

    def IsValid(self):
        return self._state["prim_present"]


class _Stage:
    def __init__(self, state):
        self._state = state

    def GetPrimAtPath(self, _path):
        return _Prim(self._state)


class _Graph:
    def __init__(self):
        self.disabled = False

    def is_disabled(self):
        return self.disabled

    def set_disabled(self, value):
        self.disabled = bool(value)

    def get_nodes(self):
        return []


def _install_fake_kit(monkeypatch, state):
    class _App:
        def update(self):
            raise AssertionError("synchronous app.update() must not run inside MCP dispatch")

        async def next_update_async(self):
            await asyncio.sleep(0)
            state["async_updates"] += 1

    class _DeletePrimsCommand:
        def __init__(self, *, paths, destructive, stage):
            assert paths == ["/World/G"]
            assert destructive is False
            self.stage = stage

        def do(self):
            state["prim_present"] = False

        def undo(self):
            state["prim_present"] = True

    omni = ModuleType("omni")
    omni.__path__ = []
    kit = ModuleType("omni.kit")
    kit.__path__ = []
    app_module = ModuleType("omni.kit.app")
    app = _App()
    app_module.get_app = lambda: app
    usd = ModuleType("omni.usd")
    usd.__path__ = []
    stage = _Stage(state)
    usd.get_context = lambda: type("_Context", (), {"get_stage": lambda self: stage})()
    commands = ModuleType("omni.usd.commands")
    commands.DeletePrimsCommand = _DeletePrimsCommand

    omni.kit = kit
    omni.usd = usd
    kit.app = app_module
    usd.commands = commands
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.kit", kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)
    monkeypatch.setitem(sys.modules, "omni.usd", usd)
    monkeypatch.setitem(sys.modules, "omni.usd.commands", commands)


def test_registered_delete_awaits_kit_update_before_readback(monkeypatch):
    state = {"prim_present": True, "async_updates": 0}
    graph = _Graph()
    _install_fake_kit(monkeypatch, state)

    def graph_or_none(_path):
        if state["prim_present"]:
            return graph
        assert state["async_updates"] == 1
        return None

    monkeypatch.setattr(graphs, "_graph_or_none", graph_or_none)
    monkeypatch.setattr(graphs, "_graph_record", lambda _graph, **_kwargs: {"node_count": 0})
    registry = {}
    graphs.register(registry, _StoppedAdapter())

    async def dispatch():
        pending = registry["graphs.delete_action_graph"](graph_path="/World/G", preview=False)
        assert inspect.isawaitable(pending)
        return await pending

    result = asyncio.run(dispatch())
    assert result["code"] == "ACTION_GRAPH_DELETED"
    assert result["readback"] == {"graph_present": False, "prim_present": False}
    assert state["async_updates"] == 1


def test_create_rollback_awaits_kit_update_before_readback(monkeypatch):
    state = {"prim_present": False, "async_updates": 0}
    _install_fake_kit(monkeypatch, state)

    class _Keys:
        CREATE_NODES = "create_nodes"
        CONNECT = "connect"
        SET_VALUES = "set_values"

    class _Controller:
        Keys = _Keys

        @staticmethod
        def edit(_edit_kwargs, _edit_spec):
            state["prim_present"] = True
            raise RuntimeError("synthetic graph edit failure")

    graph_package = ModuleType("omni.graph")
    graph_package.__path__ = []
    core = ModuleType("omni.graph.core")
    core.Controller = _Controller
    sys.modules["omni"].graph = graph_package
    graph_package.core = core
    monkeypatch.setitem(sys.modules, "omni.graph", graph_package)
    monkeypatch.setitem(sys.modules, "omni.graph.core", core)

    def graph_or_none(_path):
        if not state["prim_present"]:
            if state["async_updates"]:
                assert state["async_updates"] == 1
            return None
        return _Graph()

    monkeypatch.setattr(graphs, "_graph_or_none", graph_or_none)
    registry = {}
    graphs.register(registry, _StoppedAdapter())

    async def dispatch():
        pending = registry["graphs.create_action_graph"](graph_path="/World/G")
        assert inspect.isawaitable(pending)
        return await pending

    result = asyncio.run(dispatch())
    assert result["code"] == "GRAPH_TRANSACTION_ROLLED_BACK"
    assert result["readback"] == {"rolled_back": True, "graph_present": False}
    assert state["async_updates"] == 1


def test_registered_ros2_create_propagates_async_graph_lifecycle(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ros2, "_extension_states", lambda: {name: {"enabled": True} for name in ros2.REQUIRED_EXTENSIONS}
    )
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: None)

    async def create(_adapter, **kwargs):
        await asyncio.sleep(0)
        calls.append(("create", kwargs["graph_path"]))
        return {"status": "success", "readback": {"node_count": len(kwargs["nodes"])}}

    monkeypatch.setattr(ros2.graphs, "create_action_graph", create)
    monkeypatch.setattr(
        ros2,
        "_set_marker",
        lambda _path, workflow_type, topic_name: {
            "schema_version": "1.0",
            "workflow_type": workflow_type,
            "topic_name": topic_name,
        },
    )
    registry = {}
    ros2.register(registry, _StoppedAdapter())

    async def dispatch():
        pending = registry["ros2.create_clock_publisher"](preview=False)
        assert inspect.isawaitable(pending)
        return await pending

    result = asyncio.run(dispatch())
    assert result["code"] == "ROS2_WORKFLOW_CREATED"
    assert calls == [("create", "/World/ROS2Clock")]


def test_ros2_marker_failure_awaits_graph_rollback(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ros2, "_extension_states", lambda: {name: {"enabled": True} for name in ros2.REQUIRED_EXTENSIONS}
    )
    monkeypatch.setattr(ros2.graphs, "_graph_or_none", lambda _path: None)

    async def create(_adapter, **_kwargs):
        await asyncio.sleep(0)
        calls.append("create")
        return {"status": "success", "readback": {"node_count": 3}}

    async def delete(_adapter, _path, *, preview):
        assert preview is False
        await asyncio.sleep(0)
        calls.append("rollback")
        return {"status": "success"}

    monkeypatch.setattr(ros2.graphs, "create_action_graph", create)
    monkeypatch.setattr(ros2.graphs, "delete_action_graph", delete)
    monkeypatch.setattr(ros2, "_set_marker", lambda *_args: (_ for _ in ()).throw(RuntimeError("marker failed")))

    async def dispatch():
        pending = ros2.create_clock_publisher(_StoppedAdapter(), preview=False)
        assert inspect.isawaitable(pending)
        return await pending

    result = asyncio.run(dispatch())
    assert result["code"] == "ROS2_WORKFLOW_ROLLED_BACK"
    assert result["readback"]["rolled_back"] is True
    assert calls == ["create", "rollback"]
