"""Asset import and copy operations for the Isaac Sim 6 adapter facade."""

from __future__ import annotations

import os
import tempfile
import weakref
from typing import Any

from ..base import IsaacAdapterBase


class AssetPolicyBridge:
    """Keep facade reference-authoring overrides visible to asset import."""

    def __init__(self, adapter: IsaacAdapterBase) -> None:
        self._adapter_ref = weakref.ref(adapter)

    def add_reference_to_stage(self, usd_path: str, prim_path: str) -> Any:
        adapter = self._adapter_ref()
        if adapter is None:
            raise RuntimeError("Isaac adapter facade is no longer available")
        return adapter.add_reference_to_stage(usd_path, prim_path)


class AssetRuntime:
    """Own V6 prim copying and two-step URDF import integration."""

    def __init__(self, bridge: AssetPolicyBridge) -> None:
        self._bridge = bridge

    def clone_prim(self, source_path: str, target_path: str) -> None:
        import omni.kit.commands

        omni.kit.commands.execute("CopyPrim", path_from=source_path, path_to=target_path)

    def import_urdf(self, urdf_path: str, prim_path: str = "/World/robot", **kwargs) -> Any:
        if not os.path.isfile(urdf_path):
            raise FileNotFoundError(f"URDF file not found: {urdf_path}")
        from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig

        usd_out_dir = kwargs.pop("usd_path", None) or tempfile.mkdtemp(prefix="urdf_import_")
        config = URDFImporterConfig(urdf_path=urdf_path, usd_path=usd_out_dir, **kwargs)
        importer = URDFImporter(config)
        usd_path = importer.import_urdf()
        return self._bridge.add_reference_to_stage(usd_path, prim_path)
