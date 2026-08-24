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

"""Material creation and binding command handlers."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence

from ..adapters.base import IsaacAdapterBase


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["materials.create"] = lambda **p: create(adapter, **p)
    registry["materials.get"] = lambda **p: get_material(adapter, **p)
    registry["materials.apply"] = lambda **p: apply_material(adapter, **p)
    registry["materials.get_binding"] = lambda **p: get_binding(adapter, **p)


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, "applied": False}


def _require_stopped(adapter: IsaacAdapterBase) -> Optional[Dict[str, Any]]:
    state = str(adapter.get_simulation_state().get("timeline_state", "unknown")).lower()
    if state != "stopped":
        return _error(
            "TIMELINE_NOT_STOPPED", f"Physics material authoring requires stopped timeline; current state is {state}"
        )
    return None


def _number(value: float, name: str, minimum: float, maximum: Optional[float] = None) -> float:
    result = float(value)
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be finite and >= {minimum}{suffix}")
    return result


def create(
    adapter: IsaacAdapterBase,
    material_type: str = "pbr",
    prim_path: Optional[str] = None,
    color: Optional[Sequence[float]] = None,
    roughness: float = 0.5,
    metallic: float = 0.0,
    static_friction: float = 0.5,
    dynamic_friction: float = 0.5,
    restitution: float = 0.0,
) -> Dict[str, Any]:
    try:
        material_type = str(material_type).lower()
        if material_type not in {"pbr", "physics"}:
            raise ValueError(f"Unknown material type: {material_type}. Options: pbr, physics")
        if not prim_path:
            stage = adapter.get_stage()
            count = len(list(stage.TraverseAll()))
            prim_path = f"/World/Material_{count}"
        if material_type == "pbr":
            roughness = _number(roughness, "roughness", 0.0, 1.0)
            metallic = _number(metallic, "metallic", 0.0, 1.0)
            normalized_color = None
            if color is not None:
                if len(color) != 3:
                    raise ValueError("color must contain exactly three values from 0 to 1")
                normalized_color = [_number(value, "color", 0.0, 1.0) for value in color]
            adapter.create_pbr_material(prim_path, color=normalized_color, roughness=roughness, metallic=metallic)
        else:
            if stopped := _require_stopped(adapter):
                return stopped
            static_friction = _number(static_friction, "static_friction", 0.0)
            dynamic_friction = _number(dynamic_friction, "dynamic_friction", 0.0)
            restitution = _number(restitution, "restitution", 0.0, 1.0)
            if dynamic_friction > static_friction:
                raise ValueError("dynamic_friction must be <= static_friction")
            adapter.create_physics_material(
                prim_path, static_friction=static_friction, dynamic_friction=dynamic_friction, restitution=restitution
            )
        readback = adapter.get_material(prim_path)
        return {
            "status": "success",
            "message": f"Created {material_type} material",
            "prim_path": prim_path,
            "readback": readback,
        }
    except ValueError as exc:
        return _error("INVALID_MATERIAL", str(exc))
    except Exception as e:
        return _error("MATERIAL_CREATE_FAILED", str(e))


def get_material(adapter: IsaacAdapterBase, material_path: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not material_path:
            raise ValueError("material_path is required")
        return {"status": "success", **adapter.get_material(material_path)}
    except ValueError as exc:
        return _error("INVALID_MATERIAL", str(exc))
    except Exception as exc:
        return _error("MATERIAL_READ_FAILED", str(exc))


def apply_material(
    adapter: IsaacAdapterBase,
    material_path: Optional[str] = None,
    target_prim_path: Optional[str] = None,
    material_purpose: str = "auto",
) -> Dict[str, Any]:
    try:
        if not material_path or not target_prim_path:
            raise ValueError("material_path and target_prim_path are required")
        material_purpose = str(material_purpose).lower()
        if material_purpose not in {"auto", "physics", "visual"}:
            raise ValueError("material_purpose must be auto, physics, or visual")
        # Check both prims first. Binding a path that does not exist otherwise
        # surfaces as a raw USD C++ error naming NVIDIA's build tree
        # ("UsdRelationship::SetTargets ... Cannot map <>"), which says nothing
        # about which path was wrong. create_material auto-generates a path when
        # none is given, so pointing at a guessed one is an easy mistake.
        stage = adapter.get_stage()
        for label, path in (("material_path", material_path), ("target_prim_path", target_prim_path)):
            prim = stage.GetPrimAtPath(path) if stage else None
            if prim is None or not prim.IsValid():
                raise ValueError(
                    f"{label} '{path}' does not exist on the stage. "
                    "Use the prim_path returned by create_material, or list_prims to find it."
                )
        material = adapter.get_material(material_path)
        resolved_purpose = (
            "physics" if material_purpose == "auto" and material.get("material_type") == "physics" else material_purpose
        )
        if resolved_purpose == "auto":
            resolved_purpose = "visual"
        if resolved_purpose == "physics":
            if stopped := _require_stopped(adapter):
                return stopped
            if material.get("material_type") != "physics":
                raise ValueError("physics purpose requires a material with UsdPhysics.MaterialAPI")
        readback = adapter.apply_material(material_path, target_prim_path, material_purpose=resolved_purpose)
        return {
            "status": "success",
            "message": f"Applied {material_path} to {target_prim_path}",
            "readback": readback,
        }
    except ValueError as exc:
        return _error("INVALID_MATERIAL_BINDING", str(exc))
    except Exception as e:
        return _error("MATERIAL_BIND_FAILED", str(e))


def get_binding(
    adapter: IsaacAdapterBase,
    target_prim_path: Optional[str] = None,
    material_purpose: str = "physics",
) -> Dict[str, Any]:
    try:
        if not target_prim_path:
            raise ValueError("target_prim_path is required")
        material_purpose = str(material_purpose).lower()
        if material_purpose not in {"physics", "visual"}:
            raise ValueError("material_purpose must be physics or visual")
        return {"status": "success", **adapter.get_material_binding(target_prim_path, material_purpose)}
    except ValueError as exc:
        return _error("INVALID_MATERIAL_BINDING", str(exc))
    except Exception as exc:
        return _error("MATERIAL_BINDING_READ_FAILED", str(exc))
