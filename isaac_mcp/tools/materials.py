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

"""Material MCP tools."""

import json
from typing import TYPE_CHECKING, Callable, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    @mcp.tool("create_material")
    def create_material(
        material_type: str = "pbr",
        prim_path: Optional[str] = None,
        color: Optional[List[float]] = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
        static_friction: float = 0.5,
        dynamic_friction: float = 0.5,
        restitution: float = 0.0,
    ) -> str:
        """Create a PBR or physics material.

        Args:
            material_type: "pbr" for visual material or "physics" for physics material.
            prim_path: Prim path for the material. Auto-generated if not set.
            color: [r, g, b] diffuse color (0-1). PBR only.
            roughness: Surface roughness (0-1). PBR only.
            metallic: Metallic value (0-1). PBR only.
            static_friction: Static friction coefficient (>=0). Physics only.
            dynamic_friction: Dynamic friction coefficient (>=0 and <= static). Physics only.
            restitution: Bounciness from 0 to 1. Physics only.
        """
        try:
            conn = get_connection()
            params = {
                "material_type": material_type,
                "roughness": roughness,
                "metallic": metallic,
                "static_friction": static_friction,
                "dynamic_friction": dynamic_friction,
                "restitution": restitution,
            }
            if prim_path:
                params["prim_path"] = prim_path
            if color:
                params["color"] = color
            result = conn.send_command("materials.create", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_material")
    def get_material(material_path: str) -> str:
        """Read PBR or physics material parameters and explicit units."""
        try:
            result = get_connection().send_command("materials.get", {"material_path": material_path})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("apply_material")
    def apply_material(material_path: str, target_prim_path: str, material_purpose: str = "auto") -> str:
        """Bind a material to an object.

        Args:
            material_path: Prim path of the material.
            target_prim_path: Prim path of the object to apply the material to.
            material_purpose: auto, physics, or visual. Auto selects from the material schema.
        """
        try:
            conn = get_connection()
            result = conn.send_command(
                "materials.apply",
                {
                    "material_path": material_path,
                    "target_prim_path": target_prim_path,
                    "material_purpose": material_purpose,
                },
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_material_binding")
    def get_material_binding(target_prim_path: str, material_purpose: str = "physics") -> str:
        """Read the resolved physics or visual material binding on a prim."""
        try:
            result = get_connection().send_command(
                "materials.get_binding",
                {"target_prim_path": target_prim_path, "material_purpose": material_purpose},
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})
