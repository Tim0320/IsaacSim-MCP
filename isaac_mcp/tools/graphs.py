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

"""Action Graph MCP tools."""

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    def send(command: str, params: Dict[str, Any]) -> str:
        """Forward one graph command; the registry-wide wrapper adds schema 1.0."""
        try:
            result = get_connection().send_command(command, params)
            return json.dumps(result, indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("create_action_graph")
    def create_action_graph(
        graph_path: str = "/World/ActionGraph",
        nodes: Optional[List[Dict[str, str]]] = None,
        connections: Optional[List[List[str]]] = None,
        values: Optional[List[Dict[str, object]]] = None,
        evaluator: str = "execution",
        script_file: Optional[str] = None,
        inline_script: Optional[str] = None,
    ) -> str:
        """Create and wire an OmniGraph Action Graph.

        Builds a complete Action Graph with nodes, connections and attribute values
        using og.Controller.edit(). This is the programmatic equivalent of creating
        an Action Graph in the visual editor.

        Args:
            graph_path: USD prim path for the graph (default "/World/ActionGraph").
            nodes: List of node definitions. Each dict has:
                - "path": Node path relative to graph (e.g. "OnPlaybackTick")
                - "type": OmniGraph node type (e.g. "omni.graph.action.OnPlaybackTick")
            connections: List of [source_attr, target_attr] pairs for wiring nodes.
                Each attr is "NodePath.outputs:attrName" or "NodePath.inputs:attrName".
            values: List of attribute value overrides. Each dict has:
                - "attr": Full attribute path (e.g. "ScriptNode.inputs:script")
                - "value": The value to set
            evaluator: Graph evaluator type (default "execution", what Action
                Graphs use). "push" evaluates every application update regardless
                of the timeline, so an OnPlaybackTick-driven ScriptNode would keep
                running even while the simulation is stopped.
            script_file: Convenience shortcut — path to a local Python script file.
                When provided, automatically creates OnPlaybackTick → ScriptNode nodes,
                wires them, and attaches the script file (sets usePath + scriptPath).
                The nodes and connections parameters are ignored when script_file is set.
                RECOMMENDED for anything you will iterate on — edit the file and
                reload_script "just works", with the better reload story.
            inline_script: Convenience shortcut — inline Python (must define
                setup(db)/compute(db)). Auto-creates OnPlaybackTick → ScriptNode,
                wires them, and sets the script inline (usePath=False). For small,
                static graphs. For anything you will iterate on, prefer
                script_file — it has the better reload story (edit the file +
                reload_script "just works"; inline edits need edit_action_graph).

        Example (inline script — one-step):
            create_action_graph(
                inline_script="def setup(db): pass\\ndef compute(db): return True"
            )

        Example (script file — one-step, recommended for iteration):
            create_action_graph(
                script_file="/path/to/controller.py"
            )
        """
        try:
            conn = get_connection()
            params: Dict[str, object] = {"graph_path": graph_path, "evaluator": evaluator}
            if script_file is not None:
                params["script_file"] = script_file
            elif inline_script is not None:
                params["inline_script"] = inline_script
            else:
                if nodes is not None:
                    params["nodes"] = nodes
                if connections is not None:
                    params["connections"] = connections
                if values is not None:
                    params["values"] = values
            result = conn.send_command("graphs.create_action_graph", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("edit_action_graph")
    def edit_action_graph(
        graph_path: str = "/World/ActionGraph",
        values: Optional[List[Dict[str, object]]] = None,
        connections: Optional[List[List[str]]] = None,
    ) -> str:
        """Edit an existing OmniGraph Action Graph: set attribute values or add connections.

        Use this to update ScriptNode scripts (inline or file path), change attribute
        values, or add new connections on an already-created graph.

        For ScriptNode with a local file script, set both usePath and scriptPath:
            values=[
                {"attr": "ScriptNode.inputs:usePath", "value": true},
                {"attr": "ScriptNode.inputs:scriptPath", "value": "/path/to/script.py"}
            ]

        For ScriptNode with inline script:
            values=[
                {"attr": "ScriptNode.inputs:usePath", "value": false},
                {"attr": "ScriptNode.inputs:script", "value": "def compute(db): ..."}
            ]

        Args:
            graph_path: USD prim path of the existing graph (default "/World/ActionGraph").
            values: List of attribute value overrides. Each dict has:
                - "attr": Attribute path relative to graph (e.g. "ScriptNode.inputs:script")
                - "value": The value to set
            connections: List of [source_attr, target_attr] pairs to add.
        """
        try:
            conn = get_connection()
            params: Dict[str, object] = {"graph_path": graph_path}
            if values is not None:
                params["values"] = values
            if connections is not None:
                params["connections"] = connections
            result = conn.send_command("graphs.edit_action_graph", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("list_action_graphs")
    def list_action_graphs(root_path: str = "/World", include_disabled: bool = True) -> str:
        """List Action Graphs below a USD root, including disabled graphs by default.

        Args:
            root_path: USD subtree to inspect.
            include_disabled: Include graphs whose evaluation is disabled.
        """
        return send(
            "graphs.list_action_graphs",
            {"root_path": root_path, "include_disabled": include_disabled},
        )

    @mcp.tool("get_action_graph")
    def get_action_graph(
        graph_path: str,
        include_values: bool = False,
        include_script_source: bool = False,
    ) -> str:
        """Read one Action Graph's nodes, edges, state, and optional values or script source.

        Script source is omitted by default because inline source and local file
        contents may be large or sensitive.
        """
        return send(
            "graphs.get_action_graph",
            {
                "graph_path": graph_path,
                "include_values": include_values,
                "include_script_source": include_script_source,
            },
        )

    @mcp.tool("delete_action_graph")
    def delete_action_graph(graph_path: str, preview: bool = True) -> str:
        """Preview or delete one exact Action Graph, with deletion read-back."""
        return send("graphs.delete_action_graph", {"graph_path": graph_path, "preview": preview})

    @mcp.tool("connect_action_graph")
    def connect_action_graph(
        graph_path: str,
        source_attr: str,
        target_attr: str,
        preview: bool = True,
    ) -> str:
        """Preview or connect one source output to one target input in an Action Graph."""
        return send(
            "graphs.connect_action_graph",
            {
                "graph_path": graph_path,
                "source_attr": source_attr,
                "target_attr": target_attr,
                "preview": preview,
            },
        )

    @mcp.tool("disconnect_action_graph")
    def disconnect_action_graph(
        graph_path: str,
        source_attr: str,
        target_attr: str,
        preview: bool = True,
    ) -> str:
        """Preview or remove one exact connection from an Action Graph."""
        return send(
            "graphs.disconnect_action_graph",
            {
                "graph_path": graph_path,
                "source_attr": source_attr,
                "target_attr": target_attr,
                "preview": preview,
            },
        )

    @mcp.tool("set_action_graph_enabled")
    def set_action_graph_enabled(graph_path: str, enabled: bool, preview: bool = True) -> str:
        """Preview or enable/disable one Action Graph and read back its effective state."""
        return send(
            "graphs.set_action_graph_enabled",
            {"graph_path": graph_path, "enabled": enabled, "preview": preview},
        )

    @mcp.tool("get_action_graph_status")
    def get_action_graph_status(graph_path: str) -> str:
        """Read one Action Graph's enabled, evaluation, and error status."""
        return send("graphs.get_action_graph_status", {"graph_path": graph_path})

    @mcp.tool("evaluate_action_graph")
    def evaluate_action_graph(graph_path: str) -> str:
        """Explicitly evaluate one exact Action Graph and return post-evaluation status."""
        return send("graphs.evaluate_action_graph", {"graph_path": graph_path})

    @mcp.tool("configure_script_node")
    def configure_script_node(
        graph_path: str,
        node_path: str = "ScriptNode",
        mode: str = "inline",
        inline_script: Optional[str] = None,
        script_file: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Preview or configure one exact ScriptNode in explicit inline/file mode.

        ``mode='inline'`` requires ``inline_script`` and forbids ``script_file``.
        ``mode='file'`` requires ``script_file`` and forbids ``inline_script``.
        The extension validates the mode before mutating the graph.
        """
        params: Dict[str, Any] = {
            "graph_path": graph_path,
            "node_path": node_path,
            "mode": mode,
            "preview": preview,
        }
        if inline_script is not None:
            params["inline_script"] = inline_script
        if script_file is not None:
            params["script_file"] = script_file
        return send("graphs.configure_script_node", params)

    @mcp.tool("reload_script_node")
    def reload_script_node(
        graph_path: str,
        node_path: str = "ScriptNode",
        mode: Optional[str] = None,
        inline_script: Optional[str] = None,
        script_file: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Preview or recompile one exact ScriptNode without cross-graph fallback.

        Supply ``mode='inline'`` with ``inline_script`` to replace inline source.
        For ``mode='file'``, ``script_file`` may select a new canonical local file;
        when omitted, the node's existing canonical file path is reloaded. Omitting
        ``mode`` asks the extension to retain and validate the node's current mode.
        """
        params: Dict[str, Any] = {
            "graph_path": graph_path,
            "node_path": node_path,
            "preview": preview,
        }
        if mode is not None:
            params["mode"] = mode
        if inline_script is not None:
            params["inline_script"] = inline_script
        if script_file is not None:
            params["script_file"] = script_file
        return send("graphs.reload_script_node", params)
