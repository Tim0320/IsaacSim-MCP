"""Material authoring operations for the Isaac Sim 6 adapter facade."""

from __future__ import annotations

import math
import weakref
from typing import Any, Dict, Optional, Sequence

from ..base import IsaacAdapterBase
from .scene import SceneRuntime


class MaterialPolicyBridge:
    """Keep inherited material read-back and monkeypatch targets on the facade."""

    def __init__(self, adapter: IsaacAdapterBase) -> None:
        self._adapter_ref = weakref.ref(adapter)

    def _adapter(self) -> IsaacAdapterBase:
        adapter = self._adapter_ref()
        if adapter is None:
            raise RuntimeError("Isaac adapter facade is no longer available")
        return adapter

    def get_material(self, material_path: str) -> Dict[str, Any]:
        return self._adapter().get_material(material_path)

    def get_material_binding(self, target_prim_path: str, material_purpose: str) -> Dict[str, Any]:
        return self._adapter().get_material_binding(target_prim_path, material_purpose)


class MaterialRuntime:
    """Own V6 visual/physics material authoring and rollback."""

    def __init__(self, scene: SceneRuntime, bridge: MaterialPolicyBridge) -> None:
        self._scene = scene
        self._bridge = bridge

    def get_stage(self):
        return self._scene.get_stage()

    def create_pbr_material(
        self,
        prim_path: str,
        color: Optional[Sequence[float]] = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
    ) -> Any:
        from pxr import Gf, Sdf, UsdShade

        stage = self.get_stage()
        material = UsdShade.Material.Define(stage, prim_path)
        shader = UsdShade.Shader.Define(stage, f"{prim_path}/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
        if color:
            shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color[:3]))
        material.CreateSurfaceOutput().ConnectToSource(shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
        return material

    def create_physics_material(
        self,
        prim_path: str,
        static_friction: float = 0.5,
        dynamic_friction: float = 0.5,
        restitution: float = 0.0,
    ) -> Any:
        from pxr import UsdPhysics, UsdShade

        stage = self.get_stage()
        if stage.GetPrimAtPath(prim_path).IsValid():
            raise ValueError(f"Prim already exists: {prim_path}")
        try:
            shade_material = UsdShade.Material.Define(stage, prim_path)
            material = UsdPhysics.MaterialAPI.Apply(shade_material.GetPrim())
            material.CreateStaticFrictionAttr().Set(float(static_friction))
            material.CreateDynamicFrictionAttr().Set(float(dynamic_friction))
            material.CreateRestitutionAttr().Set(float(restitution))
            readback = self._bridge.get_material(prim_path)
            expected = (float(static_friction), float(dynamic_friction), float(restitution))
            actual = (readback["static_friction"], readback["dynamic_friction"], readback["restitution"])
            if not all(
                math.isclose(requested, observed, rel_tol=1e-6, abs_tol=1e-7)
                for requested, observed in zip(expected, actual)
            ):
                raise RuntimeError(f"Physics material read-back mismatch: expected {expected}, got {actual}")
            return material
        except Exception:
            stage.RemovePrim(prim_path)
            raise

    def apply_material(
        self, material_path: str, target_prim_path: str, material_purpose: str = "auto"
    ) -> Dict[str, Any]:
        from pxr import UsdShade

        stage = self.get_stage()
        material = UsdShade.Material(stage.GetPrimAtPath(material_path))
        target = stage.GetPrimAtPath(target_prim_path)
        if not material or not target.IsValid():
            raise ValueError("Material and target prim must exist")
        purpose_token = "physics" if material_purpose == "physics" else UsdShade.Tokens.allPurpose
        binding_api = UsdShade.MaterialBindingAPI.Apply(target)
        previous = binding_api.GetDirectBinding(purpose_token)
        previous_path = str(previous.GetMaterialPath()) if previous else ""
        previous_rel = previous.GetBindingRel() if previous else None
        previous_strength = (
            UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(previous_rel) if previous_rel else None
        )
        try:
            binding_api.Bind(material, UsdShade.Tokens.weakerThanDescendants, purpose_token)
            readback = self._bridge.get_material_binding(target_prim_path, material_purpose)
            if readback["material_path"] != material_path or readback["direct_material_path"] != material_path:
                raise RuntimeError("Material binding read-back did not match requested material")
            return readback
        except Exception:
            binding_api.UnbindDirectBinding(purpose_token)
            if previous_path:
                previous_material = UsdShade.Material(stage.GetPrimAtPath(previous_path))
                binding_api.Bind(
                    previous_material,
                    previous_strength or UsdShade.Tokens.weakerThanDescendants,
                    purpose_token,
                )
            raise
