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

from typing import Any, Dict, List, Optional

from ..adapters.base import IsaacAdapterBase


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["graphs.create_action_graph"] = lambda **p: create_action_graph(adapter, **p)
    registry["graphs.edit_action_graph"] = lambda **p: edit_action_graph(adapter, **p)


def force_recompile_scriptnode(graph, node) -> None:
    """Force a ScriptNode to re-read and recompile its script.

    Resets the USD state attribute and clears the ScriptNode's internal shared
    caches so compute() detects a change even if a racing graph evaluation
    re-set omni_initialized. Safe to call when the scriptnode extension is not
    loaded (falls back to the attribute reset only).
    """
    import omni.graph.core as og

    attr = node.get_attribute("state:omni_initialized")
    if attr is not None and attr.is_valid():
        og.Controller.set(attr, False)
    try:
        from omni.graph.scriptnode.ogn.OgnScriptNodeDatabase import OgnScriptNodeDatabase

        shared = OgnScriptNodeDatabase.shared_internal_state(node)
        shared.use_path = None
        shared.script = None
    except Exception:
        pass


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
    try:
        import omni.graph.core as og

        # Ensure physics is ready so ScriptNode scripts can call
        # SingleArticulation.initialize() — even when the user
        # presses Play from the Isaac Sim UI.
        adapter._ensure_physics_world()

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
                    return {"status": "error", "message": f"Each node needs 'path' and 'type', got: {n}"}
                og_nodes.append((node_path, node_type))

        # Convert connection pairs (relative paths are resolved by og.Controller)
        og_connections = []
        if connections:
            for conn in connections:
                if len(conn) != 2:
                    return {"status": "error", "message": f"Each connection must be [source, target], got: {conn}"}
                og_connections.append((conn[0], conn[1]))

        # Convert value dicts (relative attr paths are resolved by og.Controller)
        og_values = []
        if values:
            for v in values:
                attr = v.get("attr", "")
                val = v.get("value")
                if not attr:
                    return {"status": "error", "message": f"Each value entry needs 'attr', got: {v}"}
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
                    if use_path_attr is not None and use_path_attr.is_valid():
                        og.Controller.set(use_path_attr, True)
                    if script_path_attr is not None and script_path_attr.is_valid():
                        og.Controller.set(script_path_attr, script_file)
                else:  # inline_script
                    script_attr = script_node.get_attribute("inputs:script")
                    if use_path_attr is not None and use_path_attr.is_valid():
                        og.Controller.set(use_path_attr, False)
                    if script_attr is not None and script_attr.is_valid():
                        og.Controller.set(script_attr, inline_script)

        return {
            "status": "success",
            "message": f"Action Graph created at {graph_path}",
            "graph_path": graph_path,
            "node_count": len(created_node_paths),
            "nodes": created_node_paths,
        }
    except Exception as e:
        import traceback

        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def edit_action_graph(
    adapter: IsaacAdapterBase,
    graph_path: str = "/World/ActionGraph",
    values: Optional[List[Dict[str, object]]] = None,
    connections: Optional[List[List[str]]] = None,
) -> Dict[str, Any]:
    """Edit an existing OmniGraph Action Graph: set attribute values or add connections.

    Uses og.Controller.edit() with SET_VALUES for standard attributes, and
    og.Controller.set() with attribute objects for usePath/scriptPath on ScriptNodes
    (matching the pattern from omni.graph.scriptnode tests).

    When script content or script path is changed, automatically resets
    state:omni_initialized to False to force the ScriptNode to reload.
    """
    try:
        import omni.graph.core as og

        keys = og.Controller.Keys
        changes_made = []
        script_changed = False
        graph = None

        # ── Set attribute values ───────────────────────────────────
        if values:
            # Separate into SET_VALUES-compatible and direct-set attrs.
            # usePath (bool) and scriptPath (token) need og.Controller.set()
            # on the attribute object (per ScriptNode test patterns).
            set_values_list = []
            direct_set_list = []  # (node_relative_path, attr_name, value)

            for v in values:
                attr_spec = v.get("attr", "")
                val = v.get("value")
                if not attr_spec:
                    return {"status": "error", "message": f"Each value entry needs 'attr', got: {v}"}

                # Detect script-related changes for auto-reset
                if "inputs:script" in attr_spec or "inputs:scriptPath" in attr_spec:
                    script_changed = True

                # usePath and scriptPath need direct attribute set
                if "inputs:usePath" in attr_spec or "inputs:scriptPath" in attr_spec:
                    direct_set_list.append((attr_spec, val))
                else:
                    set_values_list.append((attr_spec, val))

            # Apply SET_VALUES via og.Controller.edit() on existing graph
            if set_values_list:
                og.Controller.edit(
                    graph_path,
                    {keys.SET_VALUES: set_values_list},
                )
                changes_made.extend(attr for attr, _ in set_values_list)

            # Apply direct attribute sets for usePath/scriptPath
            if direct_set_list:
                if graph is None:
                    graph = og.get_graph_by_path(graph_path)
                if graph is None or not graph.is_valid():
                    return {"status": "error", "message": f"Graph not found at {graph_path}"}

                for attr_spec, val in direct_set_list:
                    # Resolve to absolute if relative
                    if not attr_spec.startswith("/"):
                        attr_spec = f"{graph_path}/{attr_spec}"

                    # Split "…/NodeName.inputs:attrName" into node path + attr name
                    for sep in (".inputs:", ".outputs:", ".state:"):
                        dot_idx = attr_spec.rfind(sep)
                        if dot_idx != -1:
                            break
                    else:
                        return {
                            "status": "error",
                            "message": f"Attribute path must contain 'inputs:', 'outputs:', or 'state:', got: {attr_spec}",
                        }

                    node_path = attr_spec[:dot_idx]
                    attr_name = attr_spec[dot_idx + 1 :]

                    node = graph.get_node(node_path)
                    if node is None or not node.is_valid():
                        return {"status": "error", "message": f"Node not found at {node_path}"}

                    attribute = node.get_attribute(attr_name)
                    if attribute is None or not attribute.is_valid():
                        return {
                            "status": "error",
                            "message": f"Attribute '{attr_name}' not found on node {node_path}",
                        }

                    og.Controller.set(attribute, val)
                    changes_made.append(f"{attr_name} on {node_path}")

            # Auto-reset ScriptNode when script content or path changes.
            #
            # Simply setting state:omni_initialized = False via og.Controller
            # is unreliable: setting inputs:scriptPath can trigger a graph
            # evaluation that immediately re-sets omni_initialized to True,
            # racing with our reset.
            #
            # Robust approach: clear the ScriptNode's internal shared_state
            # caches (use_path, script) so that compute() detects a mismatch
            # and forces a full re-read + recompile, regardless of the
            # omni_initialized attribute value.
            if script_changed:
                if graph is None:
                    graph = og.get_graph_by_path(graph_path)
                if graph is not None and graph.is_valid():
                    reset_nodes = set()
                    for v in values:
                        attr_spec = v.get("attr", "")
                        if "inputs:script" in attr_spec or "inputs:scriptPath" in attr_spec:
                            node_name = attr_spec.split(".")[0]
                            reset_nodes.add(node_name)

                    for node_name in reset_nodes:
                        node_path = f"{graph_path}/{node_name}"
                        node = graph.get_node(node_path)
                        if node is not None and node.is_valid():
                            force_recompile_scriptnode(graph, node)
                            changes_made.append(f"auto-reset state:omni_initialized on {node_path}")

        # ── Add new connections ────────────────────────────────────
        if connections:
            og_connections = []
            for conn in connections:
                if len(conn) != 2:
                    return {"status": "error", "message": f"Each connection must be [source, target], got: {conn}"}
                og_connections.append((conn[0], conn[1]))

            og.Controller.edit(
                graph_path,
                {keys.CONNECT: og_connections},
            )
            changes_made.append(f"{len(og_connections)} connection(s)")

        return {
            "status": "success",
            "message": f"Updated graph at {graph_path}",
            "graph_path": graph_path,
            "changes": changes_made,
        }
    except Exception as e:
        import traceback

        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
