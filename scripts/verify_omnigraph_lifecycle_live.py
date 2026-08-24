#!/usr/bin/env python3
"""Guarded live acceptance for task 4.1 OmniGraph lifecycle and ScriptNode reload."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from isaac_mcp.connection import IsaacConnection

GRAPH = "/World/MCP_Task_4_1"
TICK = f"{GRAPH}/OnTick.outputs:tick"
SCRIPT_EXEC = f"{GRAPH}/ScriptNode.inputs:execIn"
SECOND_EXEC = f"{GRAPH}/ScriptNode2.inputs:execIn"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    assert response["schema_version"] == "1.0", response
    return response["data"]


def _script(version: str, *, fail: bool = False) -> str:
    body = (
        f'raise RuntimeError("MCP_ERROR_{version}")'
        if fail
        else (
            "import omni.graph.core as og\n    "
            f'og.Controller.set(db.node.get_attribute("state:mcp_version"), "{version}")'
        )
    )
    return (
        "def setup(db):\n"
        "    import omni.graph.core as og\n"
        '    if not db.node.get_attribute_exists("state:mcp_version"):\n'
        '        db.node.create_attribute("mcp_version", og.Type(og.BaseDataType.TOKEN), og.AttributePortType.STATE)\n'
        "\n"
        "def compute(db):\n"
        f"    {body}\n"
        "    return True\n"
    )


def _status(connection: IsaacConnection) -> dict:
    return _data(connection.send_command("graphs.get_action_graph_status", {"graph_path": GRAPH}))


def _messages(status: dict) -> list[str]:
    return [item["message"] for item in status["messages"]]


def _version(connection: IsaacConnection) -> str:
    graph = _data(
        connection.send_command(
            "graphs.get_action_graph",
            {"graph_path": GRAPH, "include_values": True, "include_script_source": False},
        )
    )
    script_node = next(item for item in graph["nodes"] if item["path"] == f"{GRAPH}/ScriptNode")
    attribute = next(item for item in script_node["attributes"] if item["name"] == "state:mcp_version")
    return str(attribute["value"])


def _play_and_stop(connection: IsaacConnection, updates: int = 8) -> dict:
    _data(connection.send_command("simulation.play"))
    for _ in range(updates):
        _data(connection.send_command("simulation.get_state"))
    _data(connection.send_command("simulation.stop"))
    state = _data(connection.send_command("simulation.get_state"))
    assert state["timeline_state"] == "stopped", state
    return state


def _play_capture_status_and_stop(connection: IsaacConnection, updates: int = 8) -> dict:
    _data(connection.send_command("simulation.play"))
    for _ in range(updates):
        _data(connection.send_command("simulation.get_state"))
    status = _status(connection)
    _data(connection.send_command("simulation.stop"))
    state = _data(connection.send_command("simulation.get_state"))
    assert state["timeline_state"] == "stopped", state
    return status


def _delete_if_present(connection: IsaacConnection) -> None:
    listing = _data(
        connection.send_command("graphs.list_action_graphs", {"root_path": "/World", "include_disabled": True})
    )
    if any(item["graph_path"] == GRAPH for item in listing["graphs"]):
        connection.send_command(
            "graphs.set_action_graph_enabled",
            {"graph_path": GRAPH, "enabled": False, "preview": False},
        )
        deleted = connection.send_command("graphs.delete_action_graph", {"graph_path": GRAPH, "preview": False})
        assert deleted["status"] == "success", deleted


def main() -> int:
    connection = IsaacConnection(port=8766)
    temp_dir = tempfile.TemporaryDirectory(prefix="isaacsim-mcp-task-4-1-")
    script_file = Path(temp_dir.name) / "controller.py"
    created = False
    evidence: dict = {}
    try:
        _data(connection.send_command("simulation.stop"))
        state_before = _data(connection.send_command("simulation.get_state"))
        assert state_before["timeline_state"] == "stopped", state_before
        scene_before = _data(connection.send_command("scene.get_info"))
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["extension"]["command_count"] == 98, capabilities["extension"]
        lifecycle = capabilities["feature_flags"]["omnigraph.lifecycle"]
        assert lifecycle["state"] == "supported", lifecycle
        assert lifecycle["enabled_state_runtime_only"] is True
        graphs_before = _data(
            connection.send_command("graphs.list_action_graphs", {"root_path": "/World", "include_disabled": True})
        )["graphs"]
        assert all(item["graph_path"] != GRAPH for item in graphs_before), graphs_before

        created_response = connection.send_command(
            "graphs.create_action_graph",
            {
                "graph_path": GRAPH,
                "evaluator": "execution",
                "nodes": [
                    {"path": "OnTick", "type": "omni.graph.action.OnTick"},
                    {"path": "ScriptNode", "type": "omni.graph.scriptnode.ScriptNode"},
                    {"path": "ScriptNode2", "type": "omni.graph.scriptnode.ScriptNode"},
                ],
                "connections": [["OnTick.outputs:tick", "ScriptNode.inputs:execIn"]],
                "values": [
                    {"attr": "ScriptNode.inputs:usePath", "value": False},
                    {"attr": "ScriptNode.inputs:script", "value": _script("A")},
                    {"attr": "ScriptNode2.inputs:usePath", "value": False},
                    {"attr": "ScriptNode2.inputs:script", "value": _script("SECOND")},
                ],
            },
        )
        created = True
        created_data = _data(created_response)
        created_readback = created_response["readback"]
        assert created_readback["evaluator"] == "execution"
        assert created_readback["node_count"] == 3
        assert created_readback["connection_count"] == 1

        listed = _data(
            connection.send_command("graphs.list_action_graphs", {"root_path": "/World", "include_disabled": True})
        )
        assert [item["graph_path"] for item in listed["graphs"]].count(GRAPH) == 1
        queried = _data(
            connection.send_command(
                "graphs.get_action_graph",
                {"graph_path": GRAPH, "include_values": False, "include_script_source": False},
            )
        )
        assert queried["node_count"] == 3 and queried["connection_count"] == 1
        assert sorted(item["script"]["mode"] for item in queried["nodes"] if item.get("script")) == [
            "inline",
            "inline",
        ]

        evaluated_a = connection.send_command("graphs.evaluate_action_graph", {"graph_path": GRAPH})
        _data(evaluated_a)
        _play_and_stop(connection)
        status_a = _status(connection)
        assert _version(connection) == "A", status_a

        disabled = connection.send_command(
            "graphs.set_action_graph_enabled",
            {"graph_path": GRAPH, "enabled": False, "preview": False},
        )
        assert disabled["status"] == "success" and disabled["readback"]["enabled"] is False
        disabled_count = _status(connection)["compute_count"]
        _play_and_stop(connection)
        disabled_eval = connection.send_command("graphs.evaluate_action_graph", {"graph_path": GRAPH})
        assert disabled_eval["status"] == "error" and disabled_eval["code"] == "GRAPH_DISABLED", disabled_eval
        assert _status(connection)["compute_count"] == disabled_count
        enabled = connection.send_command(
            "graphs.set_action_graph_enabled",
            {"graph_path": GRAPH, "enabled": True, "preview": False},
        )
        assert enabled["status"] == "success" and enabled["readback"]["enabled"] is True

        connect_preview = connection.send_command(
            "graphs.connect_action_graph",
            {"graph_path": GRAPH, "source_attr": TICK, "target_attr": SECOND_EXEC},
        )
        assert connect_preview["status"] == "success" and connect_preview["data"]["preview"] is True
        connected = connection.send_command(
            "graphs.connect_action_graph",
            {"graph_path": GRAPH, "source_attr": TICK, "target_attr": SECOND_EXEC, "preview": False},
        )
        assert connected["status"] == "success" and connected["readback"]["connection_present"] is True
        duplicate = connection.send_command(
            "graphs.connect_action_graph",
            {"graph_path": GRAPH, "source_attr": TICK, "target_attr": SECOND_EXEC, "preview": False},
        )
        assert duplicate["status"] == "error" and duplicate["code"] == "CONNECTION_ALREADY_EXISTS"
        disconnected = connection.send_command(
            "graphs.disconnect_action_graph",
            {"graph_path": GRAPH, "source_attr": TICK, "target_attr": SECOND_EXEC, "preview": False},
        )
        assert disconnected["status"] == "success" and disconnected["readback"]["connection_present"] is False

        conflict = connection.send_command(
            "graphs.configure_script_node",
            {
                "graph_path": GRAPH,
                "node_path": f"{GRAPH}/ScriptNode",
                "mode": "inline",
                "inline_script": _script("BAD"),
                "script_file": str(script_file),
                "preview": False,
            },
        )
        assert conflict["status"] == "error" and conflict["code"] == "SCRIPT_MODE_CONFLICT", conflict

        inline_b = connection.send_command(
            "graphs.reload_script_node",
            {
                "graph_path": GRAPH,
                "node_path": f"{GRAPH}/ScriptNode",
                "mode": "inline",
                "inline_script": _script("B"),
                "preview": False,
            },
        )
        assert inline_b["status"] == "success" and inline_b["readback"]["compile_state"] == "pending_evaluation"
        _play_and_stop(connection)
        status_b = _status(connection)
        assert _version(connection) == "B", status_b

        script_file.write_text(_script("C"), encoding="utf-8")
        file_c = connection.send_command(
            "graphs.configure_script_node",
            {
                "graph_path": GRAPH,
                "node_path": "ScriptNode",
                "mode": "file",
                "script_file": str(script_file),
                "preview": False,
            },
        )
        assert file_c["status"] == "success" and file_c["readback"]["script"]["mode"] == "file", file_c
        _play_and_stop(connection)
        status_c = _status(connection)
        assert _version(connection) == "C", status_c

        script_file.write_text(_script("D"), encoding="utf-8")
        file_d = connection.send_command(
            "graphs.reload_script_node",
            {"graph_path": GRAPH, "node_path": "ScriptNode", "mode": "file", "preview": False},
        )
        assert file_d["status"] == "success", file_d
        _play_and_stop(connection)
        status_d = _status(connection)
        assert _version(connection) == "D", status_d

        error_reload = connection.send_command(
            "graphs.reload_script_node",
            {
                "graph_path": GRAPH,
                "node_path": "ScriptNode",
                "mode": "inline",
                "inline_script": _script("E", fail=True),
                "preview": False,
            },
        )
        assert error_reload["status"] == "success" and error_reload["readback"]["compile_state"] == "pending_evaluation"
        status_e = _play_capture_status_and_stop(connection)
        assert status_e["has_errors"] is True and any("MCP_ERROR_E" in text for text in _messages(status_e)), status_e

        recovered = connection.send_command(
            "graphs.reload_script_node",
            {
                "graph_path": GRAPH,
                "node_path": "ScriptNode",
                "mode": "inline",
                "inline_script": _script("RECOVERED"),
                "preview": False,
            },
        )
        assert recovered["status"] == "success", recovered
        _play_and_stop(connection)
        assert _version(connection) == "RECOVERED"

        delete_preview = connection.send_command("graphs.delete_action_graph", {"graph_path": GRAPH})
        assert delete_preview["status"] == "success" and delete_preview["data"]["preview"] is True
        deleted = connection.send_command("graphs.delete_action_graph", {"graph_path": GRAPH, "preview": False})
        assert deleted["status"] == "success" and deleted["readback"] == {
            "graph_present": False,
            "prim_present": False,
        }
        created = False
        after_graphs = _data(
            connection.send_command("graphs.list_action_graphs", {"root_path": "/World", "include_disabled": True})
        )["graphs"]
        assert after_graphs == graphs_before, {"before": graphs_before, "after": after_graphs}
        state_after = _data(connection.send_command("simulation.get_state"))
        assert state_after["timeline_state"] == "stopped", state_after
        scene_after = _data(connection.send_command("scene.get_info"))
        assert scene_after == scene_before, {"before": scene_before, "after": scene_after}
        evidence = {
            "command_count": capabilities["extension"]["command_count"],
            "created_node_count": created_data["node_count"],
            "query_connection_count": queried["connection_count"],
            "evaluate_a_counts": evaluated_a["readback"]["compute_count_after"],
            "disable_froze_compute_count": disabled_count,
            "duplicate_code": duplicate["code"],
            "script_modes": ["inline", "file"],
            "inline_versions": ["A", "B", "RECOVERED"],
            "file_versions": ["C", "D"],
            "runtime_error_state": status_e["evaluation_state"],
            "delete_readback": deleted["readback"],
            "graph_list_restored": True,
            "stage_prim_count": scene_after["prim_count"],
            "timeline_state": state_after["timeline_state"],
        }
        print(json.dumps({"status": "success", "graph_path": GRAPH, "evidence": evidence}, indent=2))
        return 0
    finally:
        if created:
            try:
                _delete_if_present(connection)
            except Exception as exc:
                print(json.dumps({"status": "cleanup_failed", "message": str(exc)}), flush=True)
        temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
