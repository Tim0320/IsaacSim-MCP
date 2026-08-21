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

"""Asset import and loading MCP tools."""

import json
from typing import TYPE_CHECKING, Callable, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    @mcp.tool("list_nvidia_assets")
    def list_nvidia_assets(
        category: Optional[str] = None,
        query: Optional[str] = None,
        max_results: int = 50,
    ) -> str:
        """List NVIDIA assets that can be spawned through MCP.

        Combines a verified Isaac/SimReady/Vegetation prop catalog with the
        robot library discovered from the running Isaac Sim 6.0 asset root.

        Args:
            category: Optional category: ``robot_arm``, ``quadruped``, ``agv``,
                ``robot_other``, ``conveyor``, ``warehouse``, ``factory``, or
                ``vegetation``, ``lifting``, or ``instrumentation``.
            query: Optional case-insensitive text filter across key,
                description, manufacturer, and asset path.
            max_results: Maximum returned entries, from 1 to 250.
        """
        try:
            params = {"max_results": max_results}
            if category is not None:
                params["category"] = category
            if query is not None:
                params["query"] = query
            result = get_connection().send_command("assets.list_nvidia", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("spawn_nvidia_asset")
    def spawn_nvidia_asset(
        asset_key: str,
        prim_path: Optional[str] = None,
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
    ) -> str:
        """Spawn one catalog asset into the CURRENT USD stage.

        Call ``list_nvidia_assets`` first to obtain an exact ``asset_key``.
        Robot keys create controllable articulations through the existing robot
        handler. Props, conveyors, warehouse equipment, and vegetation are
        referenced from verified NVIDIA USD paths and remain compatible with
        ``transform_object``, ``clone_object``, and ``delete_object``.

        Args:
            asset_key: Exact key returned by ``list_nvidia_assets``.
            prim_path: Optional absolute destination prim path. A unique path
                under ``/World/Assets`` is generated when omitted.
            position: Optional world ``[x, y, z]``.
            rotation: Optional XYZ Euler degrees ``[rx, ry, rz]``.
            scale: Optional ``[sx, sy, sz]`` multiplier.
        """
        try:
            params = {"asset_key": asset_key}
            optional = {
                "prim_path": prim_path,
                "position": position,
                "rotation": rotation,
                "scale": scale,
            }
            params.update({key: value for key, value in optional.items() if value is not None})
            result = get_connection().send_command("assets.spawn_nvidia", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("import_urdf")
    def import_urdf(urdf_path: str, prim_path: str = "/World/robot", position: Optional[List[float]] = None) -> str:
        """Import a robot from a URDF file into the scene.

        Args:
            urdf_path: Path to the URDF file.
            prim_path: Prim path for the imported robot.
            position: [x, y, z] world position.
        """
        try:
            conn = get_connection()
            params = {"urdf_path": urdf_path, "prim_path": prim_path}
            if position:
                params["position"] = position
            result = conn.send_command("assets.import_urdf", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("load_usd")
    def load_usd(
        usd_url: str,
        prim_path: str = "/World/my_usd",
        position: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
    ) -> str:
        """Load a USD asset from a URL or file path into the scene.

        Args:
            usd_url: URL or local path to the USD file.
            prim_path: Prim path for the loaded asset.
            position: [x, y, z] world position.
            scale: [sx, sy, sz] scale factors.
        """
        try:
            conn = get_connection()
            params = {"usd_url": usd_url, "prim_path": prim_path}
            if position:
                params["position"] = position
            if scale:
                params["scale"] = scale
            result = conn.send_command("assets.load_usd", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("search_usd")
    def search_usd(
        text_prompt: str,
        target_path: str = "/World/my_usd",
        position: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
    ) -> str:
        """Search the NVIDIA USD asset library by text description, then load the best match.

        Args:
            text_prompt: Text description of the 3D asset to search for.
            target_path: Prim path for the loaded result.
            position: [x, y, z] world position.
            scale: [sx, sy, sz] scale factors.
        """
        try:
            conn = get_connection()
            params = {"text_prompt": text_prompt, "target_path": target_path}
            if position:
                params["position"] = position
            if scale:
                params["scale"] = scale
            result = conn.send_command("assets.search_usd", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("generate_3d")
    def generate_3d(
        text_prompt: Optional[str] = None,
        image_url: Optional[str] = None,
        position: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
    ) -> str:
        """Generate a 3D model from text or image using Beaver3D, then load it into the scene.

        Args:
            text_prompt: Text description for 3D generation.
            image_url: URL of an image for 3D generation.
            position: [x, y, z] world position for the generated model.
            scale: [sx, sy, sz] scale factors.
        """
        try:
            conn = get_connection()
            params = {}
            if text_prompt:
                params["text_prompt"] = text_prompt
            if image_url:
                params["image_url"] = image_url
            if position:
                params["position"] = position
            if scale:
                params["scale"] = scale
            result = conn.send_command("assets.generate_3d", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})
