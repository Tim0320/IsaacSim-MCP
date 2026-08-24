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

"""Scene management MCP tools."""

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    def send(command: str, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            result = get_connection().send_command(command, params or {})
            return json.dumps(result, indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("get_scene_info")
    def get_scene_info() -> str:
        """Ping the Isaac Sim extension server and return scene information including stage path, assets root, and prim count."""
        try:
            conn = get_connection()
            result = conn.send_command("scene.get_info")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("create_physics_scene")
    def create_physics_scene(gravity: Optional[List[float]] = None, scene_name: str = "PhysicsScene") -> str:
        """Create a physics scene with ground plane. Call get_scene_info first to verify connection.

        Args:
            gravity: Gravity vector [x, y, z]. Default is standard gravity.
            scene_name: Name for the physics scene prim.
        """
        try:
            conn = get_connection()
            params = {"scene_name": scene_name}
            if gravity is not None:
                params["gravity"] = gravity
            result = conn.send_command("scene.create_physics", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("clear_scene")
    def clear_scene(keep_physics: bool = False, keep_environment: bool = False) -> str:
        """Remove all prims from the scene.

        Also empties any environment loaded by load_environment, so a later
        create_physics_scene(floor=True) does not stack a second ground under
        the first. The stage's defaultLight is always kept — a stage with no
        light renders black, which looks like a broken camera.

        Args:
            keep_physics: If True, keep physics scene prims.
            keep_environment: If True, keep the loaded environment. Reloading one
                costs seconds, so pass this when clearing objects between attempts.
        """
        try:
            conn = get_connection()
            result = conn.send_command(
                "scene.clear", {"keep_physics": keep_physics, "keep_environment": keep_environment}
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("list_prims")
    def list_prims(root_path: str = "/", prim_type: Optional[str] = None) -> str:
        """List all prims in the scene, optionally filtered by type.

        Args:
            root_path: Root path to start listing from.
            prim_type: Filter by prim type (e.g. "Mesh", "Xform").
        """
        try:
            conn = get_connection()
            params = {"root_path": root_path}
            if prim_type:
                params["prim_type"] = prim_type
            result = conn.send_command("scene.list_prims", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_prim_info")
    def get_prim_info(prim_path: str) -> str:
        """Get detailed information about a specific prim.

        Returns type, children, and a transform block holding position,
        rotation [rx, ry, rz] in degrees (XYZ order, the same convention
        transform_object accepts), and scale. For geometric prims (Cube,
        Sphere, Cylinder, Cone, Capsule), also returns actual_size [x, y, z]
        in meters accounting for scale and default primitive dimensions.

        Args:
            prim_path: The USD prim path to inspect.
        """
        try:
            conn = get_connection()
            result = conn.send_command("scene.get_prim_info", {"prim_path": prim_path})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("list_environments")
    def list_environments() -> str:
        """List all available environments discovered from the Isaac Sim asset server.
        Includes warehouses, offices, outdoor scenes, and more."""
        try:
            conn = get_connection()
            result = conn.send_command("scene.list_environments")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("load_environment")
    def load_environment(environment: str, prim_path: Optional[str] = None) -> str:
        """Load a pre-built environment into the scene. Supports fuzzy matching.
        Call list_environments first to see available options.

        Many shipped environments are authored Y-up and/or in centimeters; those
        are rotated and rescaled to match the stage, and the response reports what
        was applied under "corrections". It also returns "bounds" with the
        environment's extent and floor_height, so objects can be placed on the
        ground without a second query. Read prim_path from the response rather
        than assuming it — it defaults to a named child of /Environment.

        Args:
            environment: Environment name or search term (e.g. "warehouse", "hospital", "office").
            prim_path: Prim path for the loaded environment. Defaults to
                /Environment/<name>, which keeps it separate from the stage's
                default lighting and lets clear_scene remove it.
        """
        try:
            conn = get_connection()
            params: Dict[str, Any] = {"environment": environment}
            if prim_path:
                params["prim_path"] = prim_path
            result = conn.send_command("scene.load_environment", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("new_stage")
    def new_stage(scratch_stage: bool = False, scratch_root: Optional[str] = None, preview: bool = True) -> str:
        """Preview or create a new empty stage. Requires scratch_stage=true, a scratch_root, stopped timeline, and defaults to preview-only."""
        return send("stage.new", {"scratch_stage": scratch_stage, "scratch_root": scratch_root, "preview": preview})

    @mcp.tool("open_stage")
    def open_stage(
        path: str,
        scratch_stage: bool = False,
        scratch_root: Optional[str] = None,
        preview: bool = True,
        readback_root_path: str = "/",
    ) -> str:
        """Preview or open a local USD stage inside scratch_root. Destructive stage replacement requires explicit scratch_stage=true."""
        return send(
            "stage.open",
            {
                "path": path,
                "scratch_stage": scratch_stage,
                "scratch_root": scratch_root,
                "preview": preview,
                "readback_root_path": readback_root_path,
            },
        )

    @mcp.tool("save_stage_as")
    def save_stage_as(
        path: str,
        scratch_stage: bool = False,
        scratch_root: Optional[str] = None,
        overwrite: bool = False,
        preview: bool = True,
        readback_root_path: str = "/",
    ) -> str:
        """Preview or export the current stage to a different local USD file inside scratch_root. Source overwrite is always rejected."""
        return send(
            "stage.save_as",
            {
                "path": path,
                "scratch_stage": scratch_stage,
                "scratch_root": scratch_root,
                "overwrite": overwrite,
                "preview": preview,
                "readback_root_path": readback_root_path,
            },
        )

    @mcp.tool("get_stage_composition")
    def get_stage_composition(root_path: str = "/") -> str:
        """Read the root layer, full layer stack, prim count, references/payloads, variant selections, semantics, and stage metadata."""
        return send("stage.get_composition", {"root_path": root_path})

    @mcp.tool("edit_sublayer")
    def edit_sublayer(action: str, layer_path: str, index: int = -1, preview: bool = True) -> str:
        """Preview or add/remove a root-layer subLayer path with stopped-timeline and exact read-back checks."""
        return send(
            "stage.edit_sublayer", {"action": action, "layer_path": layer_path, "index": index, "preview": preview}
        )

    @mcp.tool("edit_composition_arc")
    def edit_composition_arc(
        prim_path: str,
        arc_type: str,
        action: str,
        asset_path: Optional[str] = None,
        target_prim_path: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Preview or edit a reference/payload arc. Payloads also support load/unload; every mutation is read back and rolled back on failure."""
        return send(
            "stage.edit_composition_arc",
            {
                "prim_path": prim_path,
                "arc_type": arc_type,
                "action": action,
                "asset_path": asset_path,
                "target_prim_path": target_prim_path,
                "preview": preview,
            },
        )

    @mcp.tool("set_variant_selection")
    def set_variant_selection(prim_path: str, variant_set: str, selection: str, preview: bool = True) -> str:
        """Preview or select an existing USD variant after validating the set and available names."""
        return send(
            "stage.set_variant",
            {"prim_path": prim_path, "variant_set": variant_set, "selection": selection, "preview": preview},
        )

    @mcp.tool("get_semantic_labels")
    def get_semantic_labels(prim_path: str) -> str:
        """Read Isaac Sim 6.0.1 LabelsAPI taxonomies and labels, plus any legacy semantic labels."""
        return send("stage.get_semantics", {"prim_path": prim_path})

    @mcp.tool("set_semantic_labels")
    def set_semantic_labels(
        prim_path: str,
        taxonomy: str,
        labels: List[str],
        overwrite: bool = False,
        preview: bool = True,
    ) -> str:
        """Preview or apply Isaac Sim 6.0.1 UsdSemantics LabelsAPI labels under one taxonomy with read-back."""
        return send(
            "stage.set_semantics",
            {
                "prim_path": prim_path,
                "taxonomy": taxonomy,
                "labels": labels,
                "overwrite": overwrite,
                "preview": preview,
            },
        )

    @mcp.tool("get_typed_attribute")
    def get_typed_attribute(prim_path: str, attribute: str) -> str:
        """Read a USD attribute value, declared type, and authored-value state in JSON-safe form."""
        return send("stage.get_attribute", {"prim_path": prim_path, "attribute": attribute})

    @mcp.tool("set_typed_attribute")
    def set_typed_attribute(
        prim_path: str,
        attribute: str,
        type_name: str,
        value: Any,
        custom: bool = True,
        overwrite: bool = False,
        preview: bool = True,
    ) -> str:
        """Preview or set a finite, explicitly typed USD attribute. Existing attributes require overwrite=true and cannot change type."""
        return send(
            "stage.set_attribute",
            {
                "prim_path": prim_path,
                "attribute": attribute,
                "type_name": type_name,
                "value": value,
                "custom": custom,
                "overwrite": overwrite,
                "preview": preview,
            },
        )

    @mcp.tool("apply_stage_batch")
    def apply_stage_batch(operations: List[Dict[str, Any]], preview: bool = True, readback_root_path: str = "/") -> str:
        """Preview or atomically apply up to 100 layer/arc/variant/semantic/attribute edits. Any failed operation restores the stage snapshot."""
        return send(
            "stage.apply_batch",
            {"operations": operations, "preview": preview, "readback_root_path": readback_root_path},
        )
