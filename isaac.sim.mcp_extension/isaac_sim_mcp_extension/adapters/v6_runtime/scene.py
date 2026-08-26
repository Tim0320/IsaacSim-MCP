"""Scene and prim operations for the Isaac Sim 6 adapter facade."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from ..transforms import read_transform, set_transform
from .context import RuntimeContext

if TYPE_CHECKING:
    from pxr import Usd


class SceneRuntime:
    """Own scene discovery, stage access, and prim authoring operations."""

    def __init__(self, context: RuntimeContext) -> None:
        self._context = context

    def get_stage(self) -> "Usd.Stage":
        return self._context.get_stage()

    def get_assets_root_path(self) -> str:
        from isaacsim.storage.native import get_assets_root_path

        return get_assets_root_path()

    def discover_environments(self) -> Dict[str, Dict[str, str]]:
        import omni.client

        root = self.get_assets_root_path()
        discovered: Dict[str, Dict[str, str]] = {}
        search_bases = ["/Isaac/Environments/", "/NVIDIA/Assets/Scenes/Templates/"]
        for base in search_bases:
            result, entries = omni.client.list(root + base)
            if result != omni.client.Result.OK:
                continue
            for entry in entries:
                name = entry.relative_path.rstrip("/")
                if name.lstrip("/").startswith("."):
                    continue
                dir_path = root + base + name + "/"
                r2, files = omni.client.list(dir_path)
                if r2 != omni.client.Result.OK:
                    continue
                for file_entry in files:
                    if file_entry.relative_path.endswith(".thumb.usd"):
                        continue
                    if file_entry.relative_path.endswith((".usd", ".usda")):
                        key = name.lower().replace(" ", "_")
                        if key not in discovered:
                            discovered[key] = {
                                "asset_path": base + name + "/" + file_entry.relative_path,
                                "description": name.replace("_", " "),
                            }
                        break
                for file_entry in files:
                    subname = file_entry.relative_path.rstrip("/")
                    if subname.lstrip("/").startswith("."):
                        continue
                    r3, subfiles = omni.client.list(dir_path + subname + "/")
                    if r3 != omni.client.Result.OK:
                        continue
                    for subfile in subfiles:
                        if subfile.relative_path.endswith(".thumb.usd"):
                            continue
                        if subfile.relative_path.endswith((".usd", ".usda")):
                            key = f"{name}_{subname}".lower().replace(" ", "_")
                            if key not in discovered:
                                discovered[key] = {
                                    "asset_path": base + name + "/" + subname + "/" + subfile.relative_path,
                                    "description": f"{name} {subname}".replace("_", " "),
                                }
                            break
        return discovered

    def load_environment(self, env_path: str, prim_path: str = "/Environment") -> None:
        from isaacsim.core.experimental.utils.stage import add_reference_to_stage

        add_reference_to_stage(env_path, prim_path)

    def create_prim(self, prim_path: str, prim_type: str = "Xform", **kwargs) -> "Usd.Prim":
        from isaacsim.core.experimental.utils.stage import define_prim

        return define_prim(prim_path, type_name=prim_type)

    def delete_prim(self, prim_path: str) -> bool:
        import omni.kit.commands

        omni.kit.commands.execute("DeletePrims", paths=[prim_path])
        return True

    def add_reference_to_stage(self, usd_path: str, prim_path: str) -> "Usd.Prim":
        from isaacsim.core.experimental.utils.stage import add_reference_to_stage

        return add_reference_to_stage(usd_path, prim_path)

    def set_prim_transform(
        self,
        prim_path: str,
        position: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
        scale: Optional[Sequence[float]] = None,
    ) -> None:
        from pxr import UsdGeom

        prim = self.get_stage().GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        set_transform(UsdGeom.Xformable(prim), position=position, rotation=rotation, scale=scale)

    def get_prim_transform(self, prim_path: str) -> Dict[str, Any]:
        from pxr import UsdGeom

        prim = self.get_stage().GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        return read_transform(UsdGeom.Xformable(prim))

    def list_prims(self, root_path: str = "/", prim_type: Optional[str] = None) -> List[Dict[str, str]]:
        root = self.get_stage().GetPrimAtPath(root_path)
        results: List[Dict[str, str]] = []
        for prim in root.GetAllChildren():
            type_name = prim.GetTypeName()
            if prim_type and type_name != prim_type:
                continue
            results.append({"path": str(prim.GetPath()), "type": type_name})
        return results

    def get_prim_info(self, prim_path: str) -> Dict[str, Any]:
        prim = self.get_stage().GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        info: Dict[str, Any] = {
            "path": prim_path,
            "type": prim.GetTypeName(),
            "transform": self.get_prim_transform(prim_path),
            "children": [str(child.GetPath()) for child in prim.GetAllChildren()],
        }
        if prim.GetTypeName() in ("Cube", "Sphere", "Cylinder", "Cone", "Capsule"):
            try:
                actual_size, _bbox = self.get_prim_actual_size(prim_path)
                info["actual_size"] = actual_size
            except Exception:
                pass
        return info

    def get_prim_actual_size(self, prim_path: str) -> Tuple[List[float], Tuple[List[float], List[float]]]:
        from pxr import Usd, UsdGeom

        prim = self.get_stage().GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        prim_type = prim.GetTypeName()
        xformable = UsdGeom.Xformable(prim)
        local_transform = xformable.GetLocalTransformation()
        scale = [
            float(local_transform.GetRow3(0).GetLength()),
            float(local_transform.GetRow3(1).GetLength()),
            float(local_transform.GetRow3(2).GetLength()),
        ]
        if prim_type == "Cube":
            size = self._attribute_value(UsdGeom.Cube(prim).GetSizeAttr(), 1.0)
            dims = [size * scale[0], size * scale[1], size * scale[2]]
        elif prim_type == "Sphere":
            diameter = 2.0 * self._attribute_value(UsdGeom.Sphere(prim).GetRadiusAttr(), 0.5)
            dims = [diameter * scale[0], diameter * scale[1], diameter * scale[2]]
        elif prim_type in ("Cylinder", "Cone"):
            geom = UsdGeom.Cylinder(prim) if prim_type == "Cylinder" else UsdGeom.Cone(prim)
            radius = self._attribute_value(geom.GetRadiusAttr(), 0.5)
            height = self._attribute_value(geom.GetHeightAttr(), 1.0)
            axis_attr = geom.GetAxisAttr()
            axis_value = axis_attr.Get() if axis_attr else None
            dims = self._axial_dims(str(axis_value or "Z"), height, 2.0 * radius, scale)
        elif prim_type == "Capsule":
            geom = UsdGeom.Capsule(prim)
            radius = self._attribute_value(geom.GetRadiusAttr(), 0.5)
            height = self._attribute_value(geom.GetHeightAttr(), 1.0)
            dims = [2.0 * radius * scale[0], 2.0 * radius * scale[1], (height + 2.0 * radius) * scale[2]]
        else:
            raise ValueError(f"Unsupported prim type for size calculation: {prim_type}")
        translation = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
        position = [float(translation[0]), float(translation[1]), float(translation[2])]
        half = [dimension / 2.0 for dimension in dims]
        bbox_min = [position[index] - half[index] for index in range(3)]
        bbox_max = [position[index] + half[index] for index in range(3)]
        return dims, (bbox_min, bbox_max)

    @staticmethod
    def _attribute_value(attribute: Any, default: float) -> float:
        value = attribute.Get() if attribute else None
        return float(value) if value is not None else default

    @staticmethod
    def _axial_dims(axis: str, height: float, diameter: float, scale: Sequence[float]) -> List[float]:
        if axis == "X":
            return [height * scale[0], diameter * scale[1], diameter * scale[2]]
        if axis == "Y":
            return [diameter * scale[0], height * scale[1], diameter * scale[2]]
        return [diameter * scale[0], diameter * scale[1], height * scale[2]]
