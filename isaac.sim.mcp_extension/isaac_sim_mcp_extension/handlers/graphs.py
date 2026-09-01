# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Action Graph command handlers."""

from __future__ import annotations

import asyncio
import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters.base import IsaacAdapterBase


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["graphs.create_action_graph"] = lambda **p: create_action_graph(adapter, **p)
    registry["graphs.edit_action_graph"] = lambda **p: edit_action_graph(adapter, **p)
    registry["graphs.list_action_graphs"] = lambda **p: list_action_graphs(adapter, **p)
    registry["graphs.get_action_graph"] = lambda **p: get_action_graph(adapter, **p)
    registry["graphs.delete_action_graph"] = lambda **p: delete_action_graph(adapter, **p)
    registry["graphs.connect_action_graph"] = lambda **p: connect_action_graph(adapter, **p)
    registry["graphs.disconnect_action_graph"] = lambda **p: disconnect_action_graph(adapter, **p)
    registry["graphs.set_action_graph_enabled"] = lambda **p: set_action_graph_enabled(adapter, **p)
    registry["graphs.get_action_graph_status"] = lambda **p: get_action_graph_status(adapter, **p)
    registry["graphs.configure_script_node"] = lambda **p: configure_script_node(adapter, **p)
    registry["graphs.reload_script_node"] = lambda **p: reload_script_node(adapter, **p)
    registry["graphs.evaluate_action_graph"] = lambda **p: evaluate_action_graph(adapter, **p)


def _error(code: str, message: str, **fields: Any) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, **fields}


def _success(code: str, message: str, data: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    return {"status": "success", "code": code, "message": message, "data": data, **fields}


async def _next_kit_update() -> None:
    """Yield to Kit once without re-entering its asyncio event loop."""
    import omni.kit.app

    await omni.kit.app.get_app().next_update_async()


def _run_or_return(awaitable):
    """Run direct offline calls, but let Kit's dispatcher await on its loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    return awaitable


def _require_stopped(adapter: IsaacAdapterBase) -> Optional[Dict[str, Any]]:
    try:
        state = adapter.get_simulation_state() or {}
    except Exception as exc:
        return _error("TIMELINE_STATE_UNAVAILABLE", f"Cannot verify stopped timeline: {exc}")
    timeline = str(state.get("timeline_state") or state.get("state") or "").lower()
    playing = bool(state.get("playing"))
    if playing or timeline not in {"stopped", "stop"}:
        return _error("TIMELINE_NOT_STOPPED", "OmniGraph writes require a stopped timeline")
    return None


def _validate_graph_path(graph_path: str) -> Optional[Dict[str, Any]]:
    value = str(graph_path or "").strip()
    if not value.startswith("/") or value == "/" or "//" in value or "." in value:
        return _error("INVALID_GRAPH_PATH", f"Expected an absolute USD prim path, got: {graph_path!r}")
    try:
        from pxr import Sdf
    except ImportError:
        return None
    if not hasattr(Sdf, "Path"):
        return None
    try:
        path = Sdf.Path(value)
        if not path.IsPrimPath() or path == Sdf.Path.absoluteRootPath:
            raise ValueError
    except (TypeError, ValueError):
        return _error("INVALID_GRAPH_PATH", f"Expected an absolute USD prim path, got: {graph_path!r}")
    return None


def _graph_or_none(graph_path: str):
    import omni.graph.core as og

    graph = og.get_graph_by_path(str(graph_path))
    if graph is None or not graph.is_valid():
        return None
    return graph


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", value))


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "path"):
        return str(value.path)
    if hasattr(value, "__iter__") and not isinstance(value, (bytes, bytearray)):
        try:
            return [_json_value(item) for item in value]
        except Exception:
            pass
    return str(value)


def _attribute_path(attribute) -> str:
    return str(attribute.get_path())


def _connection_exists(source, target) -> bool:
    target_path = _attribute_path(target)
    return any(_attribute_path(item) == target_path for item in source.get_downstream_connections())


def _resolve_attribute(graph, graph_path: str, attribute_spec: str):
    import omni.graph.core as og

    value = str(attribute_spec or "").strip()
    if not value:
        raise ValueError("Attribute path is required")
    full_path = value if value.startswith("/") else f"{graph_path.rstrip('/')}/{value}"
    if not full_path.startswith(f"{graph_path.rstrip('/')}/") or "." not in full_path:
        raise ValueError(f"Attribute must belong to graph {graph_path}: {attribute_spec}")
    attribute = og.Controller.attribute(full_path)
    if attribute is None or not attribute.is_valid():
        raise LookupError(f"Attribute not found: {attribute_spec}")
    node = attribute.get_node()
    if node is None or not node.is_valid() or node.get_graph() != graph:
        raise ValueError(f"Attribute must belong to graph {graph_path}: {attribute_spec}")
    return attribute


def _resolve_node(graph, graph_path: str, node_path: str):
    value = str(node_path or "").strip()
    if not value:
        raise ValueError("node_path is required")
    full_path = value if value.startswith("/") else f"{graph_path.rstrip('/')}/{value.lstrip('/')}"
    if not full_path.startswith(f"{graph_path.rstrip('/')}/"):
        raise ValueError(f"Node must belong to graph {graph_path}: {node_path}")
    node = graph.get_node(full_path)
    if node is None or not node.is_valid():
        raise LookupError(f"Node not found: {full_path}")
    return node


def _script_source_record(node, *, include_source: bool = False) -> Optional[Dict[str, Any]]:
    if node.get_type_name() != "omni.graph.scriptnode.ScriptNode":
        return None
    import omni.graph.core as og

    use_path = bool(og.Controller.get(node.get_attribute("inputs:usePath")))
    source_attr = node.get_attribute("inputs:scriptPath" if use_path else "inputs:script")
    source = str(og.Controller.get(source_attr) or "")
    source_bytes = source.encode("utf-8")
    file_path = None
    if use_path and source:
        try:
            file_path = Path(source).expanduser().resolve(strict=True)
            source_bytes = file_path.read_bytes()
        except (OSError, ValueError):
            file_path = None
    record: Dict[str, Any] = {
        "mode": "file" if use_path else "inline",
        "source_bytes": len(source_bytes),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    if use_path:
        record["script_file"] = source
        record["file_exists"] = file_path is not None
        if file_path is not None:
            record["file_mtime_ns"] = file_path.stat().st_mtime_ns
    if include_source and not use_path:
        record["inline_script"] = source
    initialized = node.get_attribute("state:omni_initialized")
    if initialized is not None and initialized.is_valid():
        record["initialized"] = bool(og.Controller.get(initialized))
    return record


def _node_messages(node) -> List[Dict[str, str]]:
    import omni.graph.core as og

    messages = []
    for severity in (og.Severity.ERROR, og.Severity.WARNING, og.Severity.INFO):
        for message in node.get_compute_messages(severity):
            messages.append(
                {
                    "severity": str(severity.name).lower(),
                    "message": str(message),
                    "node_path": str(node.get_prim_path()),
                }
            )
    return messages


def _graph_record(
    graph,
    *,
    include_attributes: bool = False,
    include_values: bool = False,
    include_script_source: bool = False,
) -> Dict[str, Any]:
    import omni.graph.core as og

    nodes = []
    connections = set()
    script_node_count = 0
    for node in sorted(graph.get_nodes(), key=lambda item: str(item.get_prim_path())):
        attributes = []
        for attribute in sorted(node.get_attributes(), key=_attribute_path):
            for target in attribute.get_downstream_connections():
                connections.add((_attribute_path(attribute), _attribute_path(target)))
            if include_attributes:
                item = {
                    "path": _attribute_path(attribute),
                    "name": str(attribute.get_name()),
                    "port_type": _enum_name(attribute.get_port_type()),
                    "type_name": str(attribute.get_type_name()),
                }
                if include_values:
                    try:
                        item["value"] = _json_value(og.Controller.get(attribute))
                    except Exception as exc:
                        item["value_error"] = str(exc)
                attributes.append(item)
        script = _script_source_record(node, include_source=include_script_source)
        if script is not None:
            script_node_count += 1
        record = {
            "path": str(node.get_prim_path()),
            "type_name": str(node.get_type_name()),
            "enabled": not bool(node.is_disabled()),
            "compute_count": int(node.get_compute_count()),
            "messages": _node_messages(node),
        }
        if script is not None:
            record["script"] = script
        if include_attributes:
            record["attributes"] = attributes
        nodes.append(record)
    edges = [{"source": source, "target": target} for source, target in sorted(connections)]
    return {
        "graph_path": str(graph.get_path_to_graph()),
        "evaluator": str(graph.get_evaluator_name()),
        "pipeline_stage": _enum_name(graph.get_pipeline_stage()),
        "backing_type": _enum_name(graph.get_graph_backing_type()),
        "enabled": not bool(graph.is_disabled()),
        "runtime_state_persistent": False,
        "node_count": len(nodes),
        "connection_count": len(edges),
        "script_node_count": script_node_count,
        "nodes": nodes,
        "connections": edges,
    }


def force_recompile_scriptnode(graph, node) -> None:
    """Force a ScriptNode to re-read and recompile its script.

    Resets the USD state attribute and clears the ScriptNode's internal shared
    caches so compute() detects a change even if a racing graph evaluation
    re-set omni_initialized. Safe to call when the scriptnode extension is not
    loaded (falls back to the attribute reset only).
    """
    import omni.graph.core as og
    from omni.graph.scriptnode.ogn.OgnScriptNodeDatabase import OgnScriptNodeDatabase

    OgnScriptNodeDatabase.NODE_TYPE_CLASS.try_cleanup(node)
    attr = node.get_attribute("state:omni_initialized")
    if attr is None or not attr.is_valid():
        raise RuntimeError(f"ScriptNode has no state:omni_initialized attribute: {node.get_prim_path()}")
    og.Controller.set(attr, False)


def create_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str = "/World/ActionGraph",
    nodes: Optional[List[Dict[str, str]]] = None,
    connections: Optional[List[List[str]]] = None,
    values: Optional[List[Dict[str, object]]] = None,
    evaluator: str = "execution",
    script_file: Optional[str] = None,
    inline_script: Optional[str] = None,
) -> Dict[str, Any]:
    return _run_or_return(
        _create_action_graph(
            adapter,
            graph_path=graph_path,
            nodes=nodes,
            connections=connections,
            values=values,
            evaluator=evaluator,
            script_file=script_file,
            inline_script=inline_script,
        )
    )


async def _create_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str = "/World/ActionGraph",
    nodes: Optional[List[Dict[str, str]]] = None,
    connections: Optional[List[List[str]]] = None,
    values: Optional[List[Dict[str, object]]] = None,
    evaluator: str = "execution",
    script_file: Optional[str] = None,
    inline_script: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an OmniGraph Action Graph with nodes, connections and values.

    When script_file is provided, automatically creates OnPlaybackTick → ScriptNode,
    wires them, and attaches the script file via usePath + scriptPath.

    When inline_script is provided instead, the same OnPlaybackTick → ScriptNode
    pair is created and wired, but the script is set inline via inputs:script
    with inputs:usePath=False.

    The evaluator defaults to "execution", the one Action Graphs are built on.
    It used to default to "push", which evaluates the graph on every application
    update regardless of the timeline, bypassing the OnPlaybackTick gating this
    function wires up. Measured on 6.0.1 with two otherwise identical graphs and
    the timeline stopped: the push graph's ScriptNode kept running (its marker
    advanced past 5000 ticks), while the execution graph stayed frozen and only
    advanced during play.

    That is not merely wasteful. A ScriptNode controller left running re-commands
    the robot on every update, silently discarding the caller's
    set_joint_positions during the step-only debug loop, and it keeps running
    after stop_simulation — contradicting the documented model that graphs tick
    only while playing.
    """
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    if evaluator not in {"execution", "push", "dirty_push"}:
        return _error("INVALID_EVALUATOR", "evaluator must be execution, push, or dirty_push")
    if script_file is not None and inline_script is not None:
        return _error("SCRIPT_MODE_CONFLICT", "script_file and inline_script are mutually exclusive")
    if inline_script is not None and not str(inline_script).strip():
        return _error("SCRIPT_MODE_CONFLICT", "inline_script must not be empty")
    if script_file is not None:
        request, request_error = _script_request("file", None, script_file, require_source=True)
        if request_error:
            return request_error
        assert request is not None
        script_file = str(request["script_file"])
    if _graph_or_none(graph_path) is not None:
        return _error("GRAPH_ALREADY_EXISTS", f"Action Graph already exists: {graph_path}")
    try:
        import omni.graph.core as og

        # ── shortcut: create standard OnPlaybackTick -> ScriptNode graph ─
        if script_file is not None or inline_script is not None:
            nodes = [
                {"path": "OnPlaybackTick", "type": "omni.graph.action.OnPlaybackTick"},
                {"path": "ScriptNode", "type": "omni.graph.scriptnode.ScriptNode"},
            ]
            connections = [["OnPlaybackTick.outputs:tick", "ScriptNode.inputs:execIn"]]
            values = None  # script/scriptPath set via direct attribute set below

        # Build og.Controller.Keys-based edit descriptor
        edit_kwargs: Dict[str, Any] = {
            "graph_path": graph_path,
            "evaluator_name": evaluator,
        }

        # Convert node dicts to tuples expected by og.Controller
        og_nodes = []
        if nodes:
            for n in nodes:
                node_path = n.get("path", "")
                node_type = n.get("type", "")
                if not node_path or not node_type:
                    return _error("INVALID_GRAPH_NODE", f"Each node needs path and type: {n}")
                og_nodes.append((node_path, node_type))

        # Convert connection pairs (relative paths are resolved by og.Controller)
        og_connections = []
        if connections:
            for conn in connections:
                if len(conn) != 2:
                    return _error("INVALID_CONNECTION", f"Each connection must be [source, target]: {conn}")
                og_connections.append((conn[0], conn[1]))

        # Convert value dicts (relative attr paths are resolved by og.Controller)
        og_values = []
        if values:
            for v in values:
                attr = v.get("attr", "")
                val = v.get("value")
                if not attr:
                    return _error("INVALID_GRAPH_EDIT", f"Each value entry requires attr: {v}")
                og_values.append((attr, val))

        # Build and execute the graph edit
        keys = og.Controller.Keys
        edit_spec = {keys.CREATE_NODES: og_nodes}
        if og_connections:
            edit_spec[keys.CONNECT] = og_connections
        if og_values:
            edit_spec[keys.SET_VALUES] = og_values

        (graph, new_nodes, _, _) = og.Controller.edit(
            edit_kwargs,
            edit_spec,
        )

        created_node_paths = [n.get_prim_path() for n in new_nodes] if new_nodes else []

        # ── attach script via direct attribute set ─────────────────
        if (script_file is not None or inline_script is not None) and graph is not None:
            script_node = graph.get_node(f"{graph_path}/ScriptNode")
            if script_node is not None and script_node.is_valid():
                use_path_attr = script_node.get_attribute("inputs:usePath")
                if script_file is not None:
                    script_path_attr = script_node.get_attribute("inputs:scriptPath")
                    if (
                        use_path_attr is None
                        or not use_path_attr.is_valid()
                        or script_path_attr is None
                        or not script_path_attr.is_valid()
                    ):
                        raise RuntimeError("Created ScriptNode is missing file-mode attributes")
                    og.Controller.set(use_path_attr, True)
                    og.Controller.set(script_path_attr, script_file)
                else:  # inline_script
                    script_attr = script_node.get_attribute("inputs:script")
                    if (
                        use_path_attr is None
                        or not use_path_attr.is_valid()
                        or script_attr is None
                        or not script_attr.is_valid()
                    ):
                        raise RuntimeError("Created ScriptNode is missing inline-mode attributes")
                    og.Controller.set(use_path_attr, False)
                    og.Controller.set(script_attr, inline_script)
                force_recompile_scriptnode(graph, script_node)
        await _next_kit_update()
        readback = _graph_record(graph, include_attributes=True, include_values=False)
        if readback["node_count"] != len(created_node_paths):
            raise RuntimeError("Created graph node-count read-back mismatch")
        return _success(
            "ACTION_GRAPH_CREATED",
            f"Action Graph created at {graph_path}",
            {"graph_path": graph_path, "node_count": len(created_node_paths), "nodes": created_node_paths},
            readback=readback,
        )
    except Exception as exc:
        try:
            import omni.usd
            from omni.usd.commands import DeletePrimsCommand

            stage = omni.usd.get_context().get_stage()
            prim = stage.GetPrimAtPath(graph_path)
            if prim and prim.IsValid():
                DeletePrimsCommand(paths=[graph_path], destructive=False, stage=stage).do()
                await _next_kit_update()
            rolled_back = _graph_or_none(graph_path) is None
        except Exception as rollback_exc:
            return _error(
                "GRAPH_ROLLBACK_FAILED",
                f"Graph creation failed ({exc}); rollback failed ({rollback_exc})",
                readback={"rolled_back": False},
            )
        return _error(
            "GRAPH_TRANSACTION_ROLLED_BACK",
            str(exc),
            readback={"rolled_back": rolled_back, "graph_present": not rolled_back},
        )


def list_action_graphs(
    adapter: IsaacAdapterBase,
    root_path: str = "/World",
    include_disabled: bool = True,
) -> Dict[str, Any]:
    del adapter
    invalid = _validate_graph_path(root_path)
    if invalid:
        return invalid
    try:
        import omni.graph.core as og

        prefix = root_path.rstrip("/") + "/"
        records = []
        for graph in og.get_all_graphs():
            if graph is None or not graph.is_valid():
                continue
            path = str(graph.get_path_to_graph())
            if path != root_path and not path.startswith(prefix):
                continue
            if not include_disabled and graph.is_disabled():
                continue
            record = _graph_record(graph)
            record.pop("nodes", None)
            record.pop("connections", None)
            records.append(record)
        records.sort(key=lambda item: item["graph_path"])
        return _success(
            "ACTION_GRAPHS_LISTED",
            f"Found {len(records)} Action Graph(s)",
            {"root_path": root_path, "graph_count": len(records), "graphs": records},
        )
    except Exception as exc:
        return _error("GRAPH_QUERY_FAILED", str(exc))


def get_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str,
    include_values: bool = False,
    include_script_source: bool = False,
) -> Dict[str, Any]:
    del adapter
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    try:
        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        record = _graph_record(
            graph,
            include_attributes=True,
            include_values=bool(include_values),
            include_script_source=bool(include_script_source),
        )
        return _success("ACTION_GRAPH_READ", f"Read Action Graph {graph_path}", record)
    except Exception as exc:
        return _error("GRAPH_QUERY_FAILED", str(exc))


def _connection_operation(
    adapter: IsaacAdapterBase,
    graph_path: str,
    source_attr: str,
    target_attr: str,
    *,
    connect: bool,
    preview: bool,
) -> Dict[str, Any]:
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        import omni.graph.core as og

        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        try:
            source = _resolve_attribute(graph, graph_path, source_attr)
            target = _resolve_attribute(graph, graph_path, target_attr)
        except LookupError as exc:
            return _error("ATTRIBUTE_NOT_FOUND", str(exc))
        except ValueError as exc:
            return _error("INVALID_CONNECTION", str(exc))
        source_path = _attribute_path(source)
        target_path = _attribute_path(target)
        present = _connection_exists(source, target)
        if connect and present:
            return _error("CONNECTION_ALREADY_EXISTS", f"Connection already exists: {source_path} -> {target_path}")
        if not connect and not present:
            return _error("CONNECTION_NOT_FOUND", f"Connection does not exist: {source_path} -> {target_path}")
        data = {
            "graph_path": graph_path,
            "source": source_path,
            "target": target_path,
            "operation": "connect" if connect else "disconnect",
        }
        if preview:
            return _success(
                "GRAPH_CONNECTION_PREVIEW", "Connection operation preview validated", {"preview": True, **data}
            )
        key = og.Controller.Keys.CONNECT if connect else og.Controller.Keys.DISCONNECT
        inverse = og.Controller.Keys.DISCONNECT if connect else og.Controller.Keys.CONNECT
        try:
            og.Controller.edit(graph_path, {key: [(source_path, target_path)]})
            source = _resolve_attribute(graph, graph_path, source_path)
            target = _resolve_attribute(graph, graph_path, target_path)
            readback_present = _connection_exists(source, target)
            if readback_present is not connect:
                raise RuntimeError("Connection read-back did not match requested state")
        except Exception as exc:
            try:
                source = _resolve_attribute(graph, graph_path, source_path)
                target = _resolve_attribute(graph, graph_path, target_path)
                current = _connection_exists(source, target)
                if current is connect:
                    og.Controller.edit(graph_path, {inverse: [(source_path, target_path)]})
                rolled_back = _connection_exists(source, target) is present
            except Exception as rollback_exc:
                return _error(
                    "GRAPH_ROLLBACK_FAILED",
                    f"Connection apply failed ({exc}); rollback failed ({rollback_exc})",
                    readback={"rolled_back": False},
                )
            return _error(
                "GRAPH_TRANSACTION_ROLLED_BACK",
                str(exc),
                readback={"rolled_back": rolled_back, "connection_present": present},
            )
        return _success(
            "GRAPH_CONNECTION_APPLIED",
            "Connection created" if connect else "Connection removed",
            data,
            readback={"connection_present": connect, "source": source_path, "target": target_path},
        )
    except Exception as exc:
        return _error("GRAPH_CONNECTION_FAILED", str(exc))


def connect_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str,
    source_attr: str,
    target_attr: str,
    preview: bool = True,
) -> Dict[str, Any]:
    return _connection_operation(
        adapter,
        graph_path,
        source_attr,
        target_attr,
        connect=True,
        preview=bool(preview),
    )


def disconnect_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str,
    source_attr: str,
    target_attr: str,
    preview: bool = True,
) -> Dict[str, Any]:
    return _connection_operation(
        adapter,
        graph_path,
        source_attr,
        target_attr,
        connect=False,
        preview=bool(preview),
    )


def set_action_graph_enabled(
    adapter: IsaacAdapterBase,
    graph_path: str,
    enabled: bool,
    preview: bool = True,
) -> Dict[str, Any]:
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    if not isinstance(enabled, bool):
        return _error("INVALID_ENABLED_STATE", "enabled must be a JSON boolean")
    if enabled:
        stopped = _require_stopped(adapter)
        if stopped:
            return stopped
    try:
        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        previous = not bool(graph.is_disabled())
        data = {
            "graph_path": graph_path,
            "enabled": enabled,
            "previous_enabled": previous,
            "runtime_state_persistent": False,
        }
        if preview:
            return _success("GRAPH_ENABLED_PREVIEW", "Graph enabled-state preview validated", {"preview": True, **data})
        try:
            graph.set_disabled(not enabled)
            if (not bool(graph.is_disabled())) is not enabled:
                raise RuntimeError("Graph enabled-state read-back mismatch")
        except Exception as exc:
            try:
                graph.set_disabled(not previous)
                rolled_back = (not bool(graph.is_disabled())) is previous
            except Exception as rollback_exc:
                return _error(
                    "GRAPH_ROLLBACK_FAILED",
                    f"Enabled-state apply failed ({exc}); rollback failed ({rollback_exc})",
                    readback={"rolled_back": False},
                )
            return _error(
                "GRAPH_TRANSACTION_ROLLED_BACK",
                str(exc),
                readback={"rolled_back": rolled_back, "enabled": previous},
            )
        return _success(
            "GRAPH_ENABLED_STATE_APPLIED",
            "Action Graph enabled" if enabled else "Action Graph disabled",
            data,
            readback={"enabled": enabled, "runtime_state_persistent": False},
        )
    except Exception as exc:
        return _error("GRAPH_STATE_APPLY_FAILED", str(exc))


def get_action_graph_status(adapter: IsaacAdapterBase, graph_path: str) -> Dict[str, Any]:
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    try:
        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        state = adapter.get_simulation_state() or {}
        nodes = []
        all_messages = []
        compute_count = 0
        for node in sorted(graph.get_nodes(), key=lambda item: str(item.get_prim_path())):
            messages = _node_messages(node)
            count = int(node.get_compute_count())
            compute_count += count
            all_messages.extend(messages)
            nodes.append(
                {
                    "path": str(node.get_prim_path()),
                    "type_name": str(node.get_type_name()),
                    "enabled": not bool(node.is_disabled()),
                    "compute_count": count,
                    "messages": messages,
                    "script": _script_source_record(node),
                }
            )
        has_errors = any(item["severity"] == "error" for item in all_messages)
        enabled = not bool(graph.is_disabled())
        evaluation_state = (
            "disabled"
            if not enabled
            else "error"
            if has_errors
            else "never_evaluated"
            if compute_count == 0
            else "success"
        )
        data = {
            "graph_path": graph_path,
            "enabled": enabled,
            "runtime_state_persistent": False,
            "evaluator": str(graph.get_evaluator_name()),
            "pipeline_stage": _enum_name(graph.get_pipeline_stage()),
            "timeline_state": str(state.get("timeline_state") or state.get("state") or "unknown"),
            "evaluation_state": evaluation_state,
            "compute_count": compute_count,
            "has_errors": has_errors,
            "messages": all_messages,
            "nodes": nodes,
        }
        return _success("ACTION_GRAPH_STATUS_READ", f"Read runtime status for {graph_path}", data)
    except Exception as exc:
        return _error("GRAPH_RUNTIME_UNAVAILABLE", str(exc))


def evaluate_action_graph(adapter: IsaacAdapterBase, graph_path: str) -> Dict[str, Any]:
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        import omni.graph.core as og

        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        if graph.is_disabled():
            return _error("GRAPH_DISABLED", f"Action Graph is disabled: {graph_path}")
        stage_name = _enum_name(graph.get_pipeline_stage())
        if stage_name in {"GRAPH_PIPELINE_STAGE_PRERENDER", "GRAPH_PIPELINE_STAGE_POSTRENDER"}:
            return _error(
                "GRAPH_NOT_EXPLICITLY_EVALUABLE",
                f"Pipeline stage {stage_name} must be evaluated by the render pipeline",
            )
        before = {str(node.get_prim_path()): int(node.get_compute_count()) for node in graph.get_nodes()}
        og.Controller.evaluate_sync(graph_path)
        after = {str(node.get_prim_path()): int(node.get_compute_count()) for node in graph.get_nodes()}
        messages = [message for node in graph.get_nodes() for message in _node_messages(node)]
        readback = {
            "compute_count_before": before,
            "compute_count_after": after,
            "messages": messages,
        }
        if any(item["severity"] == "error" for item in messages):
            return _error("GRAPH_EVALUATION_FAILED", "Action Graph evaluation reported node errors", readback=readback)
        return _success(
            "ACTION_GRAPH_EVALUATED",
            f"Evaluated Action Graph {graph_path}",
            {"graph_path": graph_path},
            readback=readback,
        )
    except Exception as exc:
        return _error("GRAPH_EVALUATION_FAILED", str(exc))


def _script_request(
    mode: Optional[str],
    inline_script: Optional[str],
    script_file: Optional[str],
    *,
    current_mode: Optional[str] = None,
    require_source: bool,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    selected = str(mode or current_mode or "").lower()
    if selected not in {"inline", "file"}:
        return None, _error("SCRIPT_MODE_CONFLICT", "mode must be exactly 'inline' or 'file'")
    if inline_script is not None and script_file is not None:
        return None, _error("SCRIPT_MODE_CONFLICT", "inline_script and script_file are mutually exclusive")
    if selected == "inline":
        if script_file is not None or (require_source and not inline_script):
            return None, _error("SCRIPT_MODE_CONFLICT", "inline mode requires inline_script and forbids script_file")
        if inline_script is not None and not str(inline_script).strip():
            return None, _error("SCRIPT_MODE_CONFLICT", "inline_script must not be empty")
        return {"mode": "inline", "inline_script": inline_script}, None
    if inline_script is not None or (require_source and not script_file):
        return None, _error("SCRIPT_MODE_CONFLICT", "file mode requires script_file and forbids inline_script")
    if script_file is None:
        return {"mode": "file", "script_file": None}, None
    try:
        resolved = Path(str(script_file)).expanduser().resolve(strict=True)
    except (OSError, ValueError) as exc:
        return None, _error("SCRIPT_FILE_NOT_FOUND", str(exc))
    if not resolved.is_file() or resolved.suffix.lower() != ".py":
        return None, _error("SCRIPT_FILE_NOT_FOUND", f"Expected an existing .py file: {resolved}")
    return {"mode": "file", "script_file": str(resolved)}, None


def _script_node_operation(
    adapter: IsaacAdapterBase,
    graph_path: str,
    node_path: str,
    *,
    mode: Optional[str],
    inline_script: Optional[str],
    script_file: Optional[str],
    preview: bool,
    configure: bool,
) -> Dict[str, Any]:
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        import omni.graph.core as og

        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        try:
            node = _resolve_node(graph, graph_path, node_path)
        except LookupError as exc:
            return _error("NODE_NOT_FOUND", str(exc))
        except ValueError as exc:
            return _error("INVALID_GRAPH_PATH", str(exc))
        if node.get_type_name() != "omni.graph.scriptnode.ScriptNode":
            return _error("SCRIPT_NODE_REQUIRED", f"Node is not a ScriptNode: {node.get_prim_path()}")
        before = _script_source_record(node, include_source=True) or {}
        request, request_error = _script_request(
            mode,
            inline_script,
            script_file,
            current_mode=str(before.get("mode") or ""),
            require_source=configure,
        )
        if request_error:
            return request_error
        assert request is not None
        if request["mode"] == "inline" and request.get("inline_script") is None:
            request["inline_script"] = str(before.get("inline_script") or "")
        if request["mode"] == "file" and request.get("script_file") is None:
            request["script_file"] = str(before.get("script_file") or "")
            _, file_error = _script_request("file", None, request["script_file"], require_source=True)
            if file_error:
                return file_error
        data = {
            "graph_path": graph_path,
            "node_path": str(node.get_prim_path()),
            "mode": request["mode"],
            "operation": "configure" if configure else "reload",
        }
        if preview:
            return _success("SCRIPT_NODE_PREVIEW", "ScriptNode operation preview validated", {"preview": True, **data})
        use_path_attr = node.get_attribute("inputs:usePath")
        script_attr = node.get_attribute("inputs:script")
        script_path_attr = node.get_attribute("inputs:scriptPath")
        initialized_attr = node.get_attribute("state:omni_initialized")
        managed = (use_path_attr, script_attr, script_path_attr, initialized_attr)
        if any(attr is None or not attr.is_valid() for attr in managed):
            return _error("SCRIPT_NODE_REQUIRED", "ScriptNode is missing required 6.0.1 attributes")
        snapshot = {
            "use_path": og.Controller.get(use_path_attr),
            "script": og.Controller.get(script_attr),
            "script_path": og.Controller.get(script_path_attr),
            "initialized": og.Controller.get(initialized_attr),
            "graph_disabled": bool(graph.is_disabled()),
            "node_disabled": bool(node.is_disabled()),
        }
        try:
            graph.set_disabled(True)
            if request["mode"] == "file":
                og.Controller.set(use_path_attr, True)
                og.Controller.set(script_path_attr, request["script_file"])
            else:
                og.Controller.set(use_path_attr, False)
                og.Controller.set(script_attr, request["inline_script"])
            force_recompile_scriptnode(graph, node)
            after = _script_source_record(node, include_source=True) or {}
            if after.get("mode") != request["mode"]:
                raise RuntimeError("ScriptNode mode read-back mismatch")
            if request["mode"] == "file" and Path(str(after.get("script_file"))).resolve(strict=False) != Path(
                str(request["script_file"])
            ).resolve(strict=False):
                raise RuntimeError("ScriptNode file-path read-back mismatch")
            if request["mode"] == "inline" and after.get("inline_script") != request["inline_script"]:
                raise RuntimeError("ScriptNode inline-source read-back mismatch")
            graph.set_disabled(snapshot["graph_disabled"])
        except Exception as exc:
            try:
                og.Controller.set(use_path_attr, snapshot["use_path"])
                og.Controller.set(script_attr, snapshot["script"])
                og.Controller.set(script_path_attr, snapshot["script_path"])
                force_recompile_scriptnode(graph, node)
                node.set_disabled(snapshot["node_disabled"])
                graph.set_disabled(snapshot["graph_disabled"])
                restored = _script_source_record(node, include_source=True) or {}
                rolled_back = restored.get("mode") == before.get("mode") and restored.get(
                    "source_sha256"
                ) == before.get("source_sha256")
            except Exception as rollback_exc:
                return _error(
                    "GRAPH_ROLLBACK_FAILED",
                    f"ScriptNode operation failed ({exc}); rollback failed ({rollback_exc})",
                    readback={"rolled_back": False},
                )
            return _error(
                "GRAPH_TRANSACTION_ROLLED_BACK",
                str(exc),
                readback={"rolled_back": rolled_back, "script": restored},
            )
        return _success(
            "SCRIPT_NODE_CONFIGURED" if configure else "SCRIPT_NODE_RELOADED",
            "ScriptNode configured" if configure else "ScriptNode reload requested",
            data,
            readback={
                "script": after,
                "graph_enabled_restored": (not bool(graph.is_disabled())) is (not snapshot["graph_disabled"]),
                "compile_state": "pending_evaluation",
            },
        )
    except Exception as exc:
        return _error("SCRIPT_RELOAD_FAILED", str(exc))


def configure_script_node(
    adapter: IsaacAdapterBase,
    graph_path: str,
    node_path: str = "ScriptNode",
    mode: str = "inline",
    inline_script: Optional[str] = None,
    script_file: Optional[str] = None,
    preview: bool = True,
) -> Dict[str, Any]:
    return _script_node_operation(
        adapter,
        graph_path,
        node_path,
        mode=mode,
        inline_script=inline_script,
        script_file=script_file,
        preview=bool(preview),
        configure=True,
    )


def reload_script_node(
    adapter: IsaacAdapterBase,
    graph_path: str,
    node_path: str = "ScriptNode",
    mode: Optional[str] = None,
    inline_script: Optional[str] = None,
    script_file: Optional[str] = None,
    preview: bool = True,
) -> Dict[str, Any]:
    return _script_node_operation(
        adapter,
        graph_path,
        node_path,
        mode=mode,
        inline_script=inline_script,
        script_file=script_file,
        preview=bool(preview),
        configure=False,
    )


def delete_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str,
    preview: bool = True,
) -> Dict[str, Any]:
    return _run_or_return(_delete_action_graph(adapter, graph_path, preview=preview))


async def _delete_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str,
    preview: bool = True,
) -> Dict[str, Any]:
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        import omni.usd
        from omni.usd.commands import DeletePrimsCommand

        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(graph_path)
        if not prim or not prim.IsValid():
            return _error("GRAPH_NOT_EDITABLE", f"Graph has no editable USD prim: {graph_path}")
        before = _graph_record(graph)
        if preview:
            return _success(
                "GRAPH_DELETE_PREVIEW",
                "Action Graph deletion preview validated",
                {"preview": True, "graph_path": graph_path, "node_count": before["node_count"]},
            )
        previous_disabled = bool(graph.is_disabled())
        command = DeletePrimsCommand(paths=[graph_path], destructive=False, stage=stage)
        try:
            graph.set_disabled(True)
            for node in graph.get_nodes():
                if node.get_type_name() == "omni.graph.scriptnode.ScriptNode":
                    force_recompile_scriptnode(graph, node)
            command.do()
            await _next_kit_update()
            remaining_graph = _graph_or_none(graph_path)
            remaining_prim = stage.GetPrimAtPath(graph_path)
            if remaining_graph is not None or (remaining_prim and remaining_prim.IsValid()):
                raise RuntimeError("Action Graph or backing prim survived deletion")
        except Exception as exc:
            try:
                command.undo()
                await _next_kit_update()
                restored = _graph_or_none(graph_path)
                if restored is None:
                    raise RuntimeError("DeletePrims undo did not restore graph")
                restored.set_disabled(previous_disabled)
                rolled_back = _graph_record(restored)["node_count"] == before["node_count"]
            except Exception as rollback_exc:
                return _error(
                    "GRAPH_ROLLBACK_FAILED",
                    f"Graph deletion failed ({exc}); rollback failed ({rollback_exc})",
                    readback={"rolled_back": False},
                )
            return _error(
                "GRAPH_TRANSACTION_ROLLED_BACK",
                str(exc),
                readback={"rolled_back": rolled_back, "graph_present": True},
            )
        return _success(
            "ACTION_GRAPH_DELETED",
            f"Deleted Action Graph {graph_path}",
            {"graph_path": graph_path, "deleted_node_count": before["node_count"]},
            readback={"graph_present": False, "prim_present": False},
        )
    except Exception as exc:
        return _error("GRAPH_DELETE_FAILED", str(exc))


def edit_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str = "/World/ActionGraph",
    values: Optional[List[Dict[str, object]]] = None,
    connections: Optional[List[List[str]]] = None,
) -> Dict[str, Any]:
    """Atomically set existing attributes and add validated graph connections."""
    invalid = _validate_graph_path(graph_path)
    if invalid:
        return invalid
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    if not values and not connections:
        return _error("INVALID_GRAPH_EDIT", "At least one value or connection is required")
    try:
        import omni.graph.core as og

        graph = _graph_or_none(graph_path)
        if graph is None:
            return _error("GRAPH_NOT_FOUND", f"Action Graph not found: {graph_path}")
        resolved_values = []
        script_nodes = set()
        for item in values or []:
            if not isinstance(item, dict) or not item.get("attr"):
                return _error("INVALID_GRAPH_EDIT", f"Each value entry requires attr and value: {item}")
            try:
                attribute = _resolve_attribute(graph, graph_path, str(item["attr"]))
            except LookupError as exc:
                return _error("ATTRIBUTE_NOT_FOUND", str(exc))
            except ValueError as exc:
                return _error("INVALID_GRAPH_EDIT", str(exc))
            resolved_values.append((attribute, item.get("value"), og.Controller.get(attribute)))
            if attribute.get_name() in {"inputs:usePath", "inputs:script", "inputs:scriptPath"}:
                node = attribute.get_node()
                if node.get_type_name() != "omni.graph.scriptnode.ScriptNode":
                    return _error("SCRIPT_NODE_REQUIRED", f"Script attribute belongs to non-ScriptNode: {item['attr']}")
                script_nodes.add(node)
        resolved_connections = []
        for connection in connections or []:
            if not isinstance(connection, (list, tuple)) or len(connection) != 2:
                return _error("INVALID_CONNECTION", f"Each connection must be [source, target]: {connection}")
            try:
                source = _resolve_attribute(graph, graph_path, str(connection[0]))
                target = _resolve_attribute(graph, graph_path, str(connection[1]))
            except LookupError as exc:
                return _error("ATTRIBUTE_NOT_FOUND", str(exc))
            except ValueError as exc:
                return _error("INVALID_CONNECTION", str(exc))
            if _connection_exists(source, target):
                return _error(
                    "CONNECTION_ALREADY_EXISTS",
                    f"Connection already exists: {_attribute_path(source)} -> {_attribute_path(target)}",
                )
            resolved_connections.append((source, target))
        graph_disabled = bool(graph.is_disabled())
        applied_connections = []
        try:
            graph.set_disabled(True)
            for attribute, value, _ in resolved_values:
                og.Controller.set(attribute, value)
                if _json_value(og.Controller.get(attribute)) != _json_value(value):
                    raise RuntimeError(f"Attribute read-back mismatch: {_attribute_path(attribute)}")
            for source, target in resolved_connections:
                source_path, target_path = _attribute_path(source), _attribute_path(target)
                og.Controller.edit(graph_path, {og.Controller.Keys.CONNECT: [(source_path, target_path)]})
                if not _connection_exists(source, target):
                    raise RuntimeError(f"Connection read-back mismatch: {source_path} -> {target_path}")
                applied_connections.append((source, target))
            for node in script_nodes:
                force_recompile_scriptnode(graph, node)
            graph.set_disabled(graph_disabled)
        except Exception as exc:
            try:
                for source, target in reversed(applied_connections):
                    if _connection_exists(source, target):
                        og.Controller.edit(
                            graph_path,
                            {og.Controller.Keys.DISCONNECT: [(_attribute_path(source), _attribute_path(target))]},
                        )
                for attribute, _, old_value in reversed(resolved_values):
                    og.Controller.set(attribute, old_value)
                for node in script_nodes:
                    force_recompile_scriptnode(graph, node)
                graph.set_disabled(graph_disabled)
                rolled_back = all(
                    _json_value(og.Controller.get(attribute)) == _json_value(old_value)
                    for attribute, _, old_value in resolved_values
                ) and all(not _connection_exists(source, target) for source, target in resolved_connections)
            except Exception as rollback_exc:
                return _error(
                    "GRAPH_ROLLBACK_FAILED",
                    f"Graph edit failed ({exc}); rollback failed ({rollback_exc})",
                    readback={"rolled_back": False},
                )
            return _error(
                "GRAPH_TRANSACTION_ROLLED_BACK",
                str(exc),
                readback={"rolled_back": rolled_back},
            )
        readback = _graph_record(graph, include_attributes=True, include_values=False)
        return _success(
            "ACTION_GRAPH_EDITED",
            f"Updated Action Graph {graph_path}",
            {
                "graph_path": graph_path,
                "value_count": len(resolved_values),
                "connection_count": len(resolved_connections),
            },
            readback=readback,
        )
    except Exception as exc:
        return _error("GRAPH_EDIT_FAILED", str(exc))
