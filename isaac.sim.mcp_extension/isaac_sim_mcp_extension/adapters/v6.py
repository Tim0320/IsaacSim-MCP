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

"""Isaac Sim 6.0.0 adapter implementation (PhysX + Newton)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .base import IsaacAdapterBase
from .transforms import read_transform, set_transform
from .units import limit_units, normalize_limit
from .version import version_string

if TYPE_CHECKING:
    from pxr import Usd

CAMERA_ANNOTATORS = [
    "rgb",
    "distance_to_camera",
    "distance_to_image_plane",
    "semantic_segmentation",
    "instance_segmentation",
    "instance_id_segmentation",
    "normals",
    "motion_vectors",
]


def _recompile_scriptnodes_for_file(abs_path: str) -> list:
    """Recompile every Action-Graph ScriptNode whose scriptPath matches abs_path.

    Returns the list of recompiled node paths (empty if none matched).
    """
    import os

    try:
        import omni.graph.core as og

        from ..handlers.graphs import force_recompile_scriptnode
    except Exception:
        return []

    recompiled = []
    try:
        graphs = og.get_all_graphs() if hasattr(og, "get_all_graphs") else []
    except Exception:
        graphs = []
    for graph in graphs:
        try:
            for node in graph.get_nodes():
                attr = node.get_attribute("inputs:scriptPath")
                if attr is None or not attr.is_valid():
                    continue
                val = attr.get()
                if val and os.path.abspath(str(val)) == abs_path:
                    force_recompile_scriptnode(graph, node)
                    recompiled.append(node.get_prim_path())
        except Exception:
            continue
    return recompiled


class IsaacAdapterV6(IsaacAdapterBase):
    """Adapter for Isaac Sim 6.0.0 — backend-neutral (PhysX + Newton)."""

    def __init__(self) -> None:
        super().__init__()
        # The active engine is deliberately NOT captured here — see _engine.
        try:
            from isaacsim.core.version import get_version

            # 6.0 returns an 8-tuple, not a string — see adapters/version.py.
            self._isaacsim_version = version_string(get_version())
        except Exception:
            self._isaacsim_version = "unknown"
        # Articulation cache keyed by prim_path. Tensor-backed Articulations
        # bind to the current omni.physics.tensors SimulationView; that view
        # is destroyed and recreated on every timeline stop→play cycle, so the
        # cache is cleared on STOP. See _on_timeline_stop.
        self._articulations: Dict[str, Any] = {}
        # Sensor wrappers keyed by prim_path. Replicator annotators fill with
        # data on every render tick — discarding and recreating the wrapper
        # on each capture call (the 5.x pattern) means every call sees a
        # freshly-registered annotator with no accumulated frames, so
        # `get_data()` returns None. Long-lived wrappers let kit's normal
        # update tick populate the annotator between MCP calls.
        self._camera_sensors: Dict[str, Any] = {}
        self._lidar_sensors: Dict[str, Any] = {}
        self._lidar_actual_paths: Dict[str, str] = {}
        self._lidar_config_metadata: Dict[str, Dict[str, Any]] = {}
        # Pending Replicator render request, so repeated captures on an empty
        # sensor do not queue one task per call. See _request_render_frame.
        self._render_request = None
        self._timeline_stop_subscription = None
        try:
            import carb.eventdispatcher
            import omni.timeline

            def _on_timeline_stop(_event):
                self._articulations.clear()
                # Sensor wrappers hold annotator subscriptions and a render
                # product; release them on stop so a fresh play cycle
                # re-registers cleanly. Dropping the dict entry is not enough --
                # the subscriptions keep the wrapper, and the wrapper keeps its
                # prim, so the camera then could not be deleted and its render
                # product kept rendering. See base.release_sensor.
                try:
                    # Timeline Stop destroys runtime render products, while
                    # authoring metadata must survive so preset LiDAR paths can
                    # be wrapped again on the next Play cycle.
                    self.release_all_sensors(evict_metadata=False)
                except Exception as exc:
                    import carb

                    carb.log_error(f"IsaacSim-MCP sensor teardown on Timeline Stop failed: {exc}")

            self._timeline_stop_subscription = carb.eventdispatcher.get_eventdispatcher().observe_event(
                event_name=omni.timeline.GLOBAL_EVENT_STOP,
                on_event=_on_timeline_stop,
                observer_name="isaac_sim_mcp.v6.cache_reset_on_stop",
            )
        except Exception:
            pass

    @property
    def _engine(self) -> str:
        """Active physics backend: "physx" | "newton" | "remotesim" | "unknown".

        Read live on every access — never cached at construction time. Under the
        Newton kit the engine is still reported as the `physx` default while this
        extension is starting up: `isaacsim.physics.newton` registers the Newton
        backend later in the boot sequence. Measured on Isaac Sim 6.0.1 with
        isaac-sim.newton.sh:

            [3.978s] ext: isaac.sim.mcp_extension   <- adapter constructed here
            [6.649s] ext: isaacsim.physics.newton   <- engine becomes "newton"

        A value captured in __init__ therefore reports "physx" for the entire
        session under Newton, which is wrong in get_simulation_state and would
        silently mis-route any future backend-specific branch.
        """
        try:
            from isaacsim.core.simulation_manager import SimulationManager

            return SimulationManager.get_active_physics_engine()
        except Exception:
            return "unknown"

    # ── Scene ──────────────────────────────────────────────

    def get_stage(self) -> "Usd.Stage":
        import omni.usd

        return omni.usd.get_context().get_stage()

    def get_assets_root_path(self) -> str:
        from isaacsim.storage.native import get_assets_root_path

        return get_assets_root_path()

    def discover_environments(self) -> Dict[str, Dict[str, str]]:
        # Identical to V5 — uses omni.client, no Isaac Sim physics deps.
        import omni.client
        from isaacsim.storage.native import get_assets_root_path

        root = get_assets_root_path()
        discovered: Dict[str, Dict[str, str]] = {}
        search_bases = ["/Isaac/Environments/", "/NVIDIA/Assets/Scenes/Templates/"]
        for base in search_bases:
            result, entries = omni.client.list(root + base)
            if result != omni.client.Result.OK:
                continue
            for entry in entries:
                name = entry.relative_path.rstrip("/")
                # Skip hidden directories. Every asset folder keeps a ".thumbs"
                # of "<name>.thumb.usd" previews, which otherwise registered as
                # environments named e.g. "grid_.thumbs" pointing at a
                # thumbnail: 8 of the 36 entries returned on 6.0.1 were these.
                if name.lstrip("/").startswith("."):
                    continue
                dir_path = root + base + name + "/"
                r2, files = omni.client.list(dir_path)
                if r2 != omni.client.Result.OK:
                    continue
                for f in files:
                    if f.relative_path.endswith(".thumb.usd"):
                        continue  # preview image, not an environment
                    if f.relative_path.endswith(".usd") or f.relative_path.endswith(".usda"):
                        key = name.lower().replace(" ", "_")
                        if key not in discovered:
                            discovered[key] = {
                                "asset_path": base + name + "/" + f.relative_path,
                                "description": name.replace("_", " "),
                            }
                        break
                for f in files:
                    subname = f.relative_path.rstrip("/")
                    if subname.lstrip("/").startswith("."):
                        continue
                    r3, subfiles = omni.client.list(dir_path + subname + "/")
                    if r3 != omni.client.Result.OK:
                        continue
                    for sf in subfiles:
                        if sf.relative_path.endswith(".thumb.usd"):
                            continue
                        if sf.relative_path.endswith(".usd") or sf.relative_path.endswith(".usda"):
                            key = f"{name}_{subname}".lower().replace(" ", "_")
                            if key not in discovered:
                                discovered[key] = {
                                    "asset_path": base + name + "/" + subname + "/" + sf.relative_path,
                                    "description": f"{name} {subname}".replace("_", " "),
                                }
                            break
        return discovered

    def load_environment(self, env_path: str, prim_path: str = "/Environment") -> None:
        from isaacsim.core.experimental.utils.stage import add_reference_to_stage

        add_reference_to_stage(env_path, prim_path)

    # ── Prims ──────────────────────────────────────────────

    def create_prim(self, prim_path: str, prim_type: str = "Xform", **kwargs) -> "Usd.Prim":
        from isaacsim.core.experimental.utils.stage import define_prim

        return define_prim(prim_path, type_name=prim_type)

    def delete_prim(self, prim_path: str) -> bool:
        import omni.kit.commands

        # A live sensor wrapper keeps its prim alive; see release_sensor.
        self.release_sensor(prim_path)
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

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        xformable = UsdGeom.Xformable(prim)
        # Which op holds the rotation, and where it sits relative to scale,
        # decides whether a requested rotation replaces or compounds. See
        # adapters/transforms.py.
        set_transform(xformable, position=position, rotation=rotation, scale=scale)

    def get_prim_transform(self, prim_path: str) -> Dict[str, Any]:
        from pxr import UsdGeom

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        return read_transform(UsdGeom.Xformable(prim))

    def list_prims(self, root_path: str = "/", prim_type: Optional[str] = None) -> List[Dict[str, str]]:
        stage = self.get_stage()
        root = stage.GetPrimAtPath(root_path)
        results: List[Dict[str, str]] = []
        for prim in root.GetAllChildren():
            ptype = prim.GetTypeName()
            if prim_type and ptype != prim_type:
                continue
            results.append({"path": str(prim.GetPath()), "type": ptype})
        return results

    def get_prim_info(self, prim_path: str) -> Dict[str, Any]:
        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        transform = self.get_prim_transform(prim_path)
        children = [str(c.GetPath()) for c in prim.GetAllChildren()]
        info: Dict[str, Any] = {
            "path": prim_path,
            "type": prim.GetTypeName(),
            "transform": transform,
            "children": children,
        }
        if prim.GetTypeName() in ("Cube", "Sphere", "Cylinder", "Cone", "Capsule"):
            try:
                actual_size, _bbox = self.get_prim_actual_size(prim_path)
                info["actual_size"] = actual_size
            except Exception:
                pass
        return info

    def get_prim_actual_size(self, prim_path: str) -> Tuple[List[float], Tuple[List[float], List[float]]]:
        # Identical to V5 — pure pxr/UsdGeom math.
        from pxr import Usd, UsdGeom

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
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
            geom = UsdGeom.Cube(prim)
            size_attr = geom.GetSizeAttr()
            size = float(size_attr.Get()) if size_attr and size_attr.Get() is not None else 1.0
            dims = [size * scale[0], size * scale[1], size * scale[2]]
        elif prim_type == "Sphere":
            geom = UsdGeom.Sphere(prim)
            radius_attr = geom.GetRadiusAttr()
            radius = float(radius_attr.Get()) if radius_attr and radius_attr.Get() is not None else 0.5
            diameter = radius * 2.0
            dims = [diameter * scale[0], diameter * scale[1], diameter * scale[2]]
        elif prim_type == "Cylinder":
            geom = UsdGeom.Cylinder(prim)
            radius_attr = geom.GetRadiusAttr()
            height_attr = geom.GetHeightAttr()
            axis_attr = geom.GetAxisAttr()
            radius = float(radius_attr.Get()) if radius_attr and radius_attr.Get() is not None else 0.5
            height = float(height_attr.Get()) if height_attr and height_attr.Get() is not None else 1.0
            axis = axis_attr.Get() if axis_attr and axis_attr.Get() is not None else "Z"
            diameter = radius * 2.0
            if axis == "X":
                dims = [height * scale[0], diameter * scale[1], diameter * scale[2]]
            elif axis == "Y":
                dims = [diameter * scale[0], height * scale[1], diameter * scale[2]]
            else:
                dims = [diameter * scale[0], diameter * scale[1], height * scale[2]]
        elif prim_type == "Cone":
            geom = UsdGeom.Cone(prim)
            radius_attr = geom.GetRadiusAttr()
            height_attr = geom.GetHeightAttr()
            axis_attr = geom.GetAxisAttr()
            radius = float(radius_attr.Get()) if radius_attr and radius_attr.Get() is not None else 0.5
            height = float(height_attr.Get()) if height_attr and height_attr.Get() is not None else 1.0
            axis = axis_attr.Get() if axis_attr and axis_attr.Get() is not None else "Z"
            diameter = radius * 2.0
            if axis == "X":
                dims = [height * scale[0], diameter * scale[1], diameter * scale[2]]
            elif axis == "Y":
                dims = [diameter * scale[0], height * scale[1], diameter * scale[2]]
            else:
                dims = [diameter * scale[0], diameter * scale[1], height * scale[2]]
        elif prim_type == "Capsule":
            geom = UsdGeom.Capsule(prim)
            radius_attr = geom.GetRadiusAttr()
            height_attr = geom.GetHeightAttr()
            radius = float(radius_attr.Get()) if radius_attr and radius_attr.Get() is not None else 0.5
            height = float(height_attr.Get()) if height_attr and height_attr.Get() is not None else 1.0
            total_height = height + 2.0 * radius
            diameter = radius * 2.0
            dims = [diameter * scale[0], diameter * scale[1], total_height * scale[2]]
        else:
            raise ValueError(f"Unsupported prim type for size calculation: {prim_type}")
        world_transform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        translation = world_transform.ExtractTranslation()
        pos = [float(translation[0]), float(translation[1]), float(translation[2])]
        half = [d / 2.0 for d in dims]
        bbox_min = [pos[0] - half[0], pos[1] - half[1], pos[2] - half[2]]
        bbox_max = [pos[0] + half[0], pos[1] + half[1], pos[2] + half[2]]
        return dims, (bbox_min, bbox_max)

    # ── Robots ─────────────────────────────────────────────

    def create_xform_prim(self, prim_path: str) -> Any:
        from isaacsim.core.experimental.prims import XformPrim

        return XformPrim(paths=[prim_path])

    def create_articulation(self, prim_path: str, name: str) -> Any:
        from isaacsim.core.experimental.prims import Articulation

        return Articulation(paths=[prim_path])

    def _new_articulation(self, prim_path: str) -> Any:
        from isaacsim.core.experimental.prims import Articulation

        cached = self._articulations.get(prim_path)
        if cached is not None:
            return cached
        art = Articulation(paths=[prim_path])
        self._articulations[prim_path] = art
        return art

    def _runtime_articulation(self, prim_path: str) -> Any:
        """Return an articulation bound to the current physics tensor view.

        Robot discovery can create and cache a USD-backed wrapper before the
        first Play. Once physics starts, that wrapper may remain USD-valid but
        have no valid tensor entity. Runtime state and command calls must evict
        it and bind a fresh wrapper to the active SimulationView.
        """
        art = self._new_articulation(prim_path)
        try:
            tensor_valid = bool(art.is_physics_tensor_entity_valid())
        except Exception:
            tensor_valid = False
        if tensor_valid:
            return art
        self._articulations.pop(prim_path, None)
        return self._new_articulation(prim_path)

    def discover_robots(self) -> Dict[str, Dict[str, str]]:
        """Scan the Isaac Sim asset server for all available robot USD files."""
        import omni.client
        from isaacsim.storage.native import get_assets_root_path

        root = get_assets_root_path()
        robots_base = root + "/Isaac/Robots/"
        discovered: Dict[str, Dict[str, str]] = {}

        result, manufacturers = omni.client.list(robots_base)
        if result != omni.client.Result.OK:
            return discovered

        # The walk is a few hundred directory listings over three levels. Run
        # each level concurrently: the calls are network round-trips against the
        # asset server, so they are latency bound, not CPU bound. Sequentially
        # they cost ~45 s on a cold omni.client cache on 6.0.1 — and kit's main
        # loop is blocked for the whole of it, so the app is frozen. Ordering is
        # preserved by mapping over the input list, so the key-preference rules
        # below behave exactly as they did sequentially.
        def _list_dir(path: str):
            try:
                res, entries = omni.client.list(path)
                return entries if res == omni.client.Result.OK else []
            except Exception:
                return []

        def _map(paths):
            if len(paths) < 2:
                return [_list_dir(p) for p in paths]
            try:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=min(16, len(paths))) as pool:
                    return list(pool.map(_list_dir, paths))
            except Exception:
                # Any threading problem: fall back to the sequential walk.
                return [_list_dir(p) for p in paths]

        mfr_names = [m.relative_path.rstrip("/") for m in manufacturers]
        mfr_models = _map([robots_base + n + "/" for n in mfr_names])

        # Flatten to (manufacturer, model) pairs, then list every model dir at once.
        # Skip hidden directories: every manufacturer keeps a ".thumbs" folder of
        # "<model>.thumb.usd" preview files, which otherwise register as a robot
        # named ".thumbs" pointing at a thumbnail.
        pairs = [
            (mfr_name, model_entry.relative_path.rstrip("/"))
            for mfr_name, models in zip(mfr_names, mfr_models)
            for model_entry in models
            if not model_entry.relative_path.lstrip("/").startswith(".")
        ]
        model_files = _map([f"{robots_base}{mfr}/{model}/" for mfr, model in pairs])

        for (mfr_name, model_name), files in zip(pairs, model_files):
            for file_entry in files:
                fname = file_entry.relative_path
                if not (fname.endswith(".usd") or fname.endswith(".usda")):
                    continue
                if fname.endswith(".thumb.usd"):
                    continue  # preview image, not a robot
                asset_rel = f"/Isaac/Robots/{mfr_name}/{model_name}/{fname}"

                key = model_name.lower().replace(" ", "_")
                if key in discovered:
                    # Keep the simpler filename (shorter name wins). Rewrite the
                    # whole record, not just the path: two manufacturers can ship
                    # the same model directory name, and updating the path alone
                    # left entries describing one vendor while pointing at
                    # another's asset.
                    if len(fname) < len(discovered[key]["asset_path"].split("/")[-1]):
                        discovered[key] = {
                            "asset_path": asset_rel,
                            "description": f"{mfr_name} {model_name}",
                            "manufacturer": mfr_name,
                        }
                else:
                    discovered[key] = {
                        "asset_path": asset_rel,
                        "description": f"{mfr_name} {model_name}",
                        "manufacturer": mfr_name,
                    }
        return discovered

    def get_robot_joint_info(self, prim_path: str) -> Dict[str, Any]:
        import traceback

        from pxr import Usd, UsdPhysics

        joint_names: List[str] = []
        num_dof = 0
        try:
            self._ensure_physics_world()
            art = self._runtime_articulation(prim_path)
            joint_names = list(art.dof_names) if art.dof_names else []
            num_dof = int(art.num_dofs) if art.num_dofs else 0
        except Exception as e:
            print(f"v6.get_robot_joint_info: tensor API failed for {prim_path}: {e}")
            traceback.print_exc()

        stage = self.get_stage()
        root_prim = stage.GetPrimAtPath(prim_path)
        if not joint_names and root_prim.IsValid():
            for desc in Usd.PrimRange(root_prim):
                if desc.IsA(UsdPhysics.RevoluteJoint) or desc.IsA(UsdPhysics.PrismaticJoint):
                    joint_names.append(desc.GetName())
            num_dof = len(joint_names)

        joint_limits = []
        for jname in joint_names:
            limit_entry: Dict[str, Any] = {"name": jname}
            for desc in Usd.PrimRange(root_prim):
                if desc.GetName() != jname:
                    continue
                if desc.IsA(UsdPhysics.RevoluteJoint):
                    rev = UsdPhysics.RevoluteJoint(desc)
                    lo = rev.GetLowerLimitAttr().Get()
                    hi = rev.GetUpperLimitAttr().Get()
                    limit_entry["type"] = "revolute"
                    limit_entry["lower"] = normalize_limit(lo, "revolute")
                    limit_entry["upper"] = normalize_limit(hi, "revolute")
                    limit_entry["units"] = limit_units("revolute")
                    break
                if desc.IsA(UsdPhysics.PrismaticJoint):
                    pris = UsdPhysics.PrismaticJoint(desc)
                    lo = pris.GetLowerLimitAttr().Get()
                    hi = pris.GetUpperLimitAttr().Get()
                    limit_entry["type"] = "prismatic"
                    limit_entry["lower"] = normalize_limit(lo, "prismatic")
                    limit_entry["upper"] = normalize_limit(hi, "prismatic")
                    limit_entry["units"] = limit_units("prismatic")
                    break
            joint_limits.append(limit_entry)
        return {"joint_names": joint_names, "num_dof": num_dof, "joint_limits": joint_limits}

    def set_joint_positions(
        self,
        prim_path: str,
        positions: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        import warp as wp

        try:
            self._ensure_physics_world()
            art = self._runtime_articulation(prim_path)
            positions_arr = wp.array(np.asarray([list(positions)], dtype=np.float32), dtype=wp.float32)
            if joint_indices is not None:
                idx_arr = wp.array(np.asarray(joint_indices, dtype=np.int32), dtype=wp.int32)
                art.set_dof_position_targets(positions_arr, dof_indices=idx_arr)
            else:
                art.set_dof_position_targets(positions_arr)
            return
        except Exception:
            pass
        # USD-drive fallback (sim stopped / articulation not yet initialised)
        self._set_joint_drive_targets(prim_path, positions, joint_indices)

    def _set_joint_drive_targets(
        self,
        prim_path: str,
        positions: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        # Identical to V5 — pure pxr.UsdPhysics.
        from pxr import Usd, UsdPhysics

        stage = self.get_stage()
        root_prim = stage.GetPrimAtPath(prim_path)
        if not root_prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        joints = []
        for desc in Usd.PrimRange(root_prim):
            if desc.IsA(UsdPhysics.RevoluteJoint) or desc.IsA(UsdPhysics.PrismaticJoint):
                joints.append(desc)
        if joint_indices is not None:
            targets = list(zip(joint_indices, positions))
        else:
            targets = list(enumerate(positions))
        for idx, value in targets:
            if idx >= len(joints):
                continue
            joint_prim = joints[idx]
            is_revolute = joint_prim.IsA(UsdPhysics.RevoluteJoint)
            drive_type = "angular" if is_revolute else "linear"
            drive = UsdPhysics.DriveAPI.Get(joint_prim, drive_type)
            if not drive:
                drive = UsdPhysics.DriveAPI.Apply(joint_prim, drive_type)
            if is_revolute:
                drive.GetTargetPositionAttr().Set(float(np.degrees(value)))
            else:
                drive.GetTargetPositionAttr().Set(float(value * 100.0))

    def _get_joint_names(self, prim_path: str) -> List[str]:
        try:
            self._ensure_physics_world()
            art = self._new_articulation(prim_path)
            if art.dof_names:
                return list(art.dof_names)
        except Exception:
            pass
        from pxr import Usd, UsdPhysics

        stage = self.get_stage()
        root_prim = stage.GetPrimAtPath(prim_path)
        if not root_prim.IsValid():
            return []
        names: List[str] = []
        for desc in Usd.PrimRange(root_prim):
            if desc.IsA(UsdPhysics.RevoluteJoint) or desc.IsA(UsdPhysics.PrismaticJoint):
                names.append(desc.GetName())
        return names

    def get_joint_positions(self, prim_path: str) -> List[float]:
        try:
            self._ensure_physics_world()
            art = self._runtime_articulation(prim_path)
            positions = art.get_dof_positions()
            if positions is not None:
                # batched (1, num_dofs) wp.array → flat list
                arr = positions.numpy() if hasattr(positions, "numpy") else np.asarray(positions)
                return arr.reshape(-1).tolist()
        except Exception:
            pass
        # USD fallback identical to V5
        from pxr import Usd, UsdPhysics

        stage = self.get_stage()
        root_prim = stage.GetPrimAtPath(prim_path)
        if not root_prim.IsValid():
            return []
        positions_list: List[float] = []
        for desc in Usd.PrimRange(root_prim):
            if not (desc.IsA(UsdPhysics.RevoluteJoint) or desc.IsA(UsdPhysics.PrismaticJoint)):
                continue
            is_revolute = desc.IsA(UsdPhysics.RevoluteJoint)
            drive_type = "angular" if is_revolute else "linear"
            drive = UsdPhysics.DriveAPI.Get(desc, drive_type)
            if drive:
                target = drive.GetTargetPositionAttr().Get()
                if target is not None:
                    if is_revolute:
                        positions_list.append(float(np.radians(target)))
                    else:
                        positions_list.append(float(target / 100.0))
                else:
                    positions_list.append(0.0)
            else:
                positions_list.append(0.0)
        return positions_list

    @staticmethod
    def _flatten_joint_values(values: Any) -> List[float]:
        if values is None:
            return []
        if hasattr(values, "numpy"):
            values = values.numpy()
        if hasattr(values, "reshape"):
            reshaped = values.reshape(-1)
            if hasattr(reshaped, "tolist"):
                return [float(value) for value in reshaped.tolist()]
        if isinstance(values, (list, tuple)):
            flattened: List[float] = []
            for value in values:
                if isinstance(value, (list, tuple)):
                    flattened.extend(float(item) for item in value)
                else:
                    flattened.append(float(value))
            return flattened
        return [float(value) for value in values]

    @staticmethod
    def _joint_type_name(value: Any) -> str:
        normalized = str(value).lower()
        if "translation" in normalized:
            return "prismatic"
        if "rotation" in normalized:
            return "revolute"
        return "unknown"

    def get_joint_state(self, prim_path: str) -> Dict[str, Any]:
        """Read tensor-backed measured state and all active command targets."""
        self._ensure_physics_world()
        art = self._runtime_articulation(prim_path)
        names = list(art.dof_names or [])
        if not names:
            raise ValueError(f"No articulation DOFs found at {prim_path}")

        state = {
            "prim_path": prim_path,
            "joint_names": names,
            "joint_types": [self._joint_type_name(value) for value in list(art.dof_types or [])],
            "positions": self._flatten_joint_values(art.get_dof_positions()),
            "velocities": self._flatten_joint_values(art.get_dof_velocities()),
            "efforts": self._flatten_joint_values(art.get_dof_projected_joint_forces()),
            "position_targets": self._flatten_joint_values(art.get_dof_position_targets()),
            "velocity_targets": self._flatten_joint_values(art.get_dof_velocity_targets()),
            "effort_targets": self._flatten_joint_values(art.get_dof_efforts()),
        }
        for key in (
            "joint_types",
            "positions",
            "velocities",
            "efforts",
            "position_targets",
            "velocity_targets",
            "effort_targets",
        ):
            if len(state[key]) != len(names):
                raise RuntimeError(f"Articulation returned {len(state[key])} {key} entries for {len(names)} joints")
        return state

    def set_joint_command(
        self,
        prim_path: str,
        mode: str,
        values: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        """Apply one V6 Articulation command using DOF subset semantics."""
        import warp as wp

        self._ensure_physics_world()
        art = self._runtime_articulation(prim_path)
        count = len(list(art.dof_names or []))
        selected = list(range(count)) if joint_indices is None else list(joint_indices)
        if not selected or len(values) != len(selected):
            raise ValueError("Joint command value count must match the selected DOFs")
        if len(set(selected)) != len(selected) or any(index < 0 or index >= count for index in selected):
            raise ValueError("Joint command contains an invalid or duplicate DOF index")

        values_arr = wp.array(np.asarray([list(values)], dtype=np.float32), dtype=wp.float32)
        indices_arr = wp.array(np.asarray(selected, dtype=np.int32), dtype=wp.int32)
        if mode == "position":
            art.set_dof_position_targets(values_arr, dof_indices=indices_arr)
        elif mode == "velocity":
            art.set_dof_velocity_targets(values_arr, dof_indices=indices_arr)
        elif mode == "effort":
            art.set_dof_efforts(values_arr, dof_indices=indices_arr)
        else:
            raise ValueError(f"Unsupported joint command mode: {mode}")

    def get_joint_config(self, prim_path: str) -> Dict[str, Any]:
        from pxr import Usd, UsdPhysics

        self._ensure_physics_world()
        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        joint_names = self._get_joint_names(prim_path)
        current_pos_list = self.get_joint_positions(prim_path)

        runtime_targets: List[float] = []
        try:
            art = self._new_articulation(prim_path)
            targets = art.get_dof_position_targets()
            if targets is not None:
                arr = targets.numpy() if hasattr(targets, "numpy") else np.asarray(targets)
                runtime_targets = arr.reshape(-1).tolist()
        except Exception:
            pass

        joints_info = []
        for desc in Usd.PrimRange(prim):
            if desc.IsA(UsdPhysics.RevoluteJoint) or desc.IsA(UsdPhysics.PrismaticJoint):
                joint_data: Dict[str, Any] = {"name": desc.GetName()}
                if desc.IsA(UsdPhysics.RevoluteJoint):
                    joint_data["type"] = "revolute"
                    joint_api = UsdPhysics.RevoluteJoint(desc)
                else:
                    joint_data["type"] = "prismatic"
                    joint_api = UsdPhysics.PrismaticJoint(desc)
                lower_attr = joint_api.GetLowerLimitAttr()
                upper_attr = joint_api.GetUpperLimitAttr()
                # USD keeps revolute limits in degrees; positions below are in
                # radians. See adapters/units.py.
                joint_type = joint_data["type"]
                joint_data["lower_limit"] = normalize_limit(lower_attr.Get() if lower_attr else None, joint_type)
                joint_data["upper_limit"] = normalize_limit(upper_attr.Get() if upper_attr else None, joint_type)
                joint_data["limit_units"] = limit_units(joint_type)
                for drive_type in ["angular", "linear"]:
                    drive_api = UsdPhysics.DriveAPI.Get(desc, drive_type)
                    if drive_api:
                        joint_data["drive_type"] = drive_type
                        stiffness_attr = drive_api.GetStiffnessAttr()
                        damping_attr = drive_api.GetDampingAttr()
                        target_attr = drive_api.GetTargetPositionAttr()
                        joint_data["stiffness"] = stiffness_attr.Get() if stiffness_attr else None
                        joint_data["damping"] = damping_attr.Get() if damping_attr else None
                        joint_data["target_position"] = target_attr.Get() if target_attr else None
                        break
                jname = desc.GetName()
                if jname in joint_names:
                    idx = joint_names.index(jname)
                    if idx < len(current_pos_list):
                        joint_data["actual_position"] = current_pos_list[idx]
                    if idx < len(runtime_targets):
                        joint_data["target_position"] = float(runtime_targets[idx])
                    if joint_data.get("target_position") is not None and "actual_position" in joint_data:
                        joint_data["position_error"] = joint_data["target_position"] - joint_data["actual_position"]
                joints_info.append(joint_data)

        warnings = []
        for j in joints_info:
            stiff = j.get("stiffness")
            damp = j.get("damping")
            if stiff is not None and stiff == 0 and (damp is None or damp == 0):
                warnings.append(
                    f"Joint '{j['name']}' has stiffness=0 and damping=0 — "
                    f"its drive is effectively disabled and will not respond to position targets."
                )
        result: Dict[str, Any] = {
            "prim_path": prim_path,
            "joint_count": len(joints_info),
            "joints": joints_info,
        }
        if warnings:
            result["warnings"] = warnings
        return result

    # ── Physics ────────────────────────────────────────────

    def _ensure_physics_world(self) -> None:
        """Initialise SimulationManager (idempotent under both PhysX and Newton).

        Cleans stale PhysicsScene references first — the SimulationManager
        retains Python wrappers around scenes that may have been deleted via
        clear_scene, and calling setup_simulation/initialize_physics against
        them raises "Accessed invalid expired 'PhysicsScene' prim".
        """
        from isaacsim.core.simulation_manager import SimulationManager

        # Do nothing until the stage exists. setup_simulation() dereferences the
        # USD stage in native code, and Kit starts accepting MCP commands before
        # it has created one — measured on 6.0.1: the socket opens at [4.0s] and
        # the stage appears 2.86s later. A command landing in that window kills
        # the entire process:
        #
        #     [Fatal] [omni.usd] attempted member lookup on NULL TfWeakPtr<UsdStage>
        #
        # That is a native abort, not a Python exception, so it cannot be caught
        # — it has to be prevented. Reproduced 3/3 with any early execute_script,
        # including one whose body was just `print('hi')`, because this runs
        # before the submitted code does.
        # get_stage() can also raise while omni.usd is still coming up, so treat
        # "no stage" and "cannot ask yet" identically.
        try:
            if self.get_stage() is None:
                return
        except Exception:
            return
        try:
            SimulationManager._cleanup_stale_physics_scenes()
        except Exception:
            pass
        SimulationManager.setup_simulation(dt=1.0 / 60.0)
        SimulationManager.initialize_physics()

    def _arm_reset_point(self) -> None:
        """Give stop_simulation something to restore to, without running the sim.

        PhysX records its restore point on a Play, and it records the state as
        of the moment play() is called. V6 advances physics with
        SimulationManager.step(), which never plays, so a run driven purely by
        step_simulation had no restore point and stop_simulation silently did
        nothing — a cube stepped down from z=2 stayed on the ground.

        Play cannot simply be called and observed: timeline transitions are
        tick-driven, and a handler may not pump kit's event loop (see step), so
        is_playing() is still False on the next line. Queueing play() and
        pause() together sidesteps that — by the time the next tick lands the
        timeline is paused, and no frame ever runs free. Measured on 6.0.1: a
        cube left at z=50.0 was still at exactly 50.0 afterwards, physics step
        count unchanged, and a subsequent stop_simulation restored it to 50.0
        from 48.73.

        Deliberately NOT the agent's job: asking the caller to play then pause
        costs a network round trip between the two, during which the sim runs
        free — measured at ~1.4s of fall — which is exactly the imprecision
        step_simulation exists to remove.

        Queueing alone is not enough: the transition is tick-driven, so it lands
        a tick *after* this returns, and a stop_simulation issued promptly finds
        no restore point and silently keeps the stepped pose. Measured on 6.0.1:
        a cube stepped from z=2.0 stayed at z=-3.32 through stop when the two
        calls were back to back, and reset correctly with any delay between
        them -- so the bug hid behind human-speed interaction and only bites the
        agent-speed debug loop this tool exists to serve. One app.update() lands
        the transition before returning, which is exactly the piece of the V5
        step this adapter otherwise avoids.

        That single pump is deliberately *not* the pumped stepping V5 does: see
        step(), which keeps SimulationManager.step for the physics so no frame
        ever runs free. Verified on 6.0.1/physx -- pump-to-arm reproduces V6's
        exact stepped result (z=-3.322, identical to no arming) while V5-style
        pumped stepping lands at z=-2.987, and the reset then works with no
        delay, 3/3. Re-check under Newton before assuming it holds there.

        Only arms while the timeline is stopped, so it re-arms once per run and
        never disturbs a genuine Play already in progress.
        """
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            if timeline.is_stopped():
                timeline.play()
                timeline.pause()
                try:
                    import omni.kit.app

                    omni.kit.app.get_app().update()
                except Exception:
                    # Pumping from inside the dispatch coroutine is the hazard
                    # step() documents. It did not reproduce here on
                    # 6.0.1/physx, but if it ever does, losing the pump costs
                    # only the reset -- degrading to the old tick-late
                    # behaviour -- and must not break stepping itself.
                    pass
        except Exception:
            # Best effort: failing to arm costs the ability to reset, but must
            # never stop the caller from stepping.
            pass

    def create_world(self, **kwargs) -> Any:
        """V6 exposes SimulationManager (a class-level singleton) where V5 returned World()."""
        from isaacsim.core.simulation_manager import SimulationManager

        return SimulationManager

    def create_simulation_context(self, **kwargs) -> Any:
        from isaacsim.core.simulation_manager import SimulationManager

        return SimulationManager

    def create_physics_scene(self, gravity: Optional[Sequence[float]] = None, scene_name: str = "PhysicsScene") -> str:
        import omni.kit.commands

        scene_path = f"/World/{scene_name}"
        # Reuse a scene that already exists rather than adding a second one:
        # two PhysicsScenes break physics state reads. See _find_physics_scene.
        existing = self._find_physics_scene(preferred_path=scene_path)
        if existing is not None:
            scene_path = existing
        else:
            omni.kit.commands.execute("CreatePrim", prim_path=scene_path, prim_type="PhysicsScene")
        if gravity is not None:
            # Without this the argument was accepted and discarded — see
            # _apply_gravity.
            self._apply_gravity(scene_path, gravity)
        return scene_path

    def get_physics_state(self, prim_path: str) -> Dict[str, Any]:
        from pxr import UsdPhysics

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")

        result: Dict[str, Any] = {"prim_path": prim_path}
        has_rb = prim.HasAPI(UsdPhysics.RigidBodyAPI)
        result["has_rigid_body"] = has_rb
        if has_rb:
            rb = UsdPhysics.RigidBodyAPI(prim)
            kinematic_attr = rb.GetKinematicEnabledAttr()
            result["is_kinematic"] = kinematic_attr.Get() if kinematic_attr else False
        has_mass = prim.HasAPI(UsdPhysics.MassAPI)
        if has_mass:
            mass_api = UsdPhysics.MassAPI(prim)
            mass_attr = mass_api.GetMassAttr()
            result["mass"] = mass_attr.Get() if mass_attr else None
        result["collision_enabled"] = prim.HasAPI(UsdPhysics.CollisionAPI)

        if has_rb:
            lin_vel = [0.0, 0.0, 0.0]
            ang_vel = [0.0, 0.0, 0.0]
            try:
                from isaacsim.core.simulation_manager import SimulationManager

                view = SimulationManager.get_physics_simulation_view()
                if view is not None:
                    rb_view = view.create_rigid_body_view([prim_path])
                    vels = rb_view.get_velocities()
                    arr = vels.numpy() if hasattr(vels, "numpy") else np.asarray(vels)
                    if arr.size >= 6:
                        flat = arr.reshape(-1)[:6]
                        lin_vel = [float(flat[0]), float(flat[1]), float(flat[2])]
                        ang_vel = [float(flat[3]), float(flat[4]), float(flat[5])]
            except Exception:
                pass
            result["linear_velocity"] = lin_vel
            result["angular_velocity"] = ang_vel

        result["contacts"] = []
        return result

    # ── Sensors ────────────────────────────────────────────

    def _request_render_frame(self) -> bool:
        """Ask Replicator to render one frame, without starting the timeline.

        RTX sensor data comes from Replicator's orchestrator, which by default
        only captures while the timeline plays (/omni/replicator/captureOnPlay).
        The documented debug loop is step-only and never plays, so on 6.0.1 the
        orchestrator sat at STOPPED and every camera returned an empty frame
        forever.

        Two obvious remedies are wrong here:

          * orchestrator.run() starts the timeline. Measured on 6.0.1: from a
            stopped timeline it left playing=True, which turns the sim loose and
            destroys the frame-exact stepping step_simulation exists to provide.
          * The synchronous orchestrator.step() is refused outright by
            Replicator from inside kit — "Synchronous call to `step` can only be
            performed in a standalone workflow ... Please use the async function
            `step_async`" — which matches the rule that handlers must not pump
            kit's event loop.

        So schedule step_async and return immediately. It runs on kit's loop
        once this handler is done, captures a single frame with pause_timeline
        set, and leaves the timeline exactly as it found it. Measured: timeline
        stayed stopped, orchestrator reached STEPPED, the next capture returned
        a real image, and the kit log recorded no reentry errors.

        The frame is therefore ready on the *next* call, not this one — the
        caller is told to retry rather than being handed a blank image.
        """
        try:
            import asyncio

            import omni.replicator.core as rep

            # While Play is active, Kit's normal update loop is already
            # producing render frames. Calling step_async(pause_timeline=True)
            # here would stop that run and fire GLOBAL_EVENT_STOP, which releases
            # the long-lived CameraSensor before its first non-RGB frame arrives.
            try:
                import omni.timeline

                if omni.timeline.get_timeline_interface().is_playing():
                    return True
            except Exception:
                pass

            pending = self._render_request
            if pending is not None and not pending.done():
                return True
            self._render_request = asyncio.ensure_future(rep.orchestrator.step_async(pause_timeline=True))
            return True
        except Exception:
            return False

    def _apply_sensor_schema(self, prim_path: str) -> None:
        """Make an already-present prim acceptable to the RTX sensor wrappers.

        No-op when the prim does not exist yet — the wrapper will create it with
        the right schema itself. See create_camera for why this is needed.
        """
        try:
            prim = self.get_stage().GetPrimAtPath(prim_path)
            if prim and prim.IsValid() and "OmniSensorAPI" not in prim.GetAppliedSchemas():
                prim.ApplyAPI("OmniSensorAPI")
        except Exception:
            # Leave it to the sensor wrapper to raise a meaningful error.
            pass

    def create_camera(self, prim_path: str, resolution: Tuple[int, int] = (1280, 720), **kwargs) -> Any:
        # 6.0 RtxCamera takes a single `path: str` — the 5.x batched
        # (`prim_paths=[...], resolutions=[...]`) signature was removed.
        # Also stand up the CameraSensor runtime + RGB annotator now so kit's
        # background render ticks start filling the annotator immediately;
        # later capture_image calls read accumulated frames from the cache.
        from isaacsim.sensors.experimental.rtx import CameraSensor, RtxCamera

        # RtxCamera adopts an existing prim rather than redefining it, and it
        # does not apply OmniSensorAPI to one it did not create. Pointing
        # create_camera at a path that already holds a plain UsdGeom.Camera —
        # which imported USD scenes routinely ship — therefore failed with
        # "Prim at <path> does not have the 'OmniSensorAPI' schema", while the
        # same call on a fresh path succeeded. Reproduced on 6.0.1: fresh path
        # OK, plain Camera at the path FAIL, existing RTX camera OK.
        #
        # Apply the schema first so an existing camera prim reaches RtxCamera in
        # the same shape a newly created one would. A prim that does not exist
        # yet needs nothing: RtxCamera creates it correctly.
        if prim_path in self._camera_sensors:
            self.release_sensor(prim_path, evict_metadata=False)
        self._apply_sensor_schema(prim_path)
        camera = RtxCamera(path=prim_path)
        # CameraSensor expects (height, width). Adapter callers historically
        # pass (width, height) — translate so the cached resolution is sane.
        h, w = (resolution[1], resolution[0]) if len(resolution) == 2 else (720, 1280)
        self._camera_sensors[prim_path] = CameraSensor(
            path=prim_path,
            resolution=(h, w),
            annotators=CAMERA_ANNOTATORS,
        )
        return camera

    def capture_camera_image(self, prim_path: str) -> np.ndarray:
        # Reuse the wrapper cached by create_camera. Building a fresh
        # CameraSensor on every call re-registers the annotator with the
        # render pipeline and discards any frames produced since the prim
        # was created, so `get_data` returns None — that was the root cause
        # of the "empty data" symptom. With a long-lived wrapper, kit's
        # background update tick fills the annotator between MCP commands
        # and get_data returns the latest rendered frame.
        from isaacsim.sensors.experimental.rtx import CameraSensor

        sensor = self._camera_sensors.get(prim_path)
        if sensor is None:
            sensor = CameraSensor(path=prim_path, resolution=(720, 1280), annotators=CAMERA_ANNOTATORS)
            self._camera_sensors[prim_path] = sensor
        data, _info = sensor.get_data("rgb")
        if data is None:
            # Nothing rendered yet. Ask Replicator for a frame so the next call
            # succeeds, instead of leaving cameras permanently blank in the
            # step-only debug loop.
            self._request_render_frame()
            return np.zeros((0,), dtype=np.uint8)
        return data.numpy() if hasattr(data, "numpy") else np.asarray(data)

    def capture_camera_output(self, prim_path: str, annotator: str) -> tuple[np.ndarray, Dict[str, Any]]:
        """Return one Isaac Sim 6.x CameraSensor annotator frame.

        Annotators are attached lazily to the long-lived CameraSensor. Reusing
        the same render product is required: replacing the wrapper here would
        discard every frame accumulated between MCP calls.
        """
        from isaacsim.sensors.experimental.rtx import CameraSensor

        sensor = self._camera_sensors.get(prim_path)
        if sensor is None:
            sensor = CameraSensor(path=prim_path, resolution=(720, 1280), annotators=CAMERA_ANNOTATORS)
            self._camera_sensors[prim_path] = sensor
        elif annotator not in getattr(sensor, "_annotators", {}):
            sensor.attach_annotators(annotator)

        data, info = sensor.get_data(annotator)
        if data is None:
            self._request_render_frame()
            return np.zeros((0,), dtype=np.uint8), {}
        array = data.numpy() if hasattr(data, "numpy") else np.asarray(data)
        return array, info or {}

    def get_camera_calibration(self, prim_path: str) -> Dict[str, Any]:
        """Read a pinhole calibration contract from the USD camera and sensor."""
        from pxr import Usd, UsdGeom

        stage = self.get_stage()
        if stage is None:
            raise RuntimeError("USD stage is not available")
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.Camera):
            raise ValueError(f"Camera prim not found at {prim_path}")

        sensor = self._camera_sensors.get(prim_path)
        if sensor is None:
            raise RuntimeError(
                f"Camera resolution is unavailable for {prim_path}; create_camera must initialize it in this session"
            )
        height, width = (int(value) for value in sensor.resolution)

        camera = UsdGeom.Camera(prim)
        focal_length = float(camera.GetFocalLengthAttr().Get())
        horizontal_aperture = float(camera.GetHorizontalApertureAttr().Get())
        vertical_aperture = float(camera.GetVerticalApertureAttr().Get())
        horizontal_offset = float(camera.GetHorizontalApertureOffsetAttr().Get() or 0.0)
        vertical_offset = float(camera.GetVerticalApertureOffsetAttr().Get() or 0.0)
        projection = str(camera.GetProjectionAttr().Get())
        clipping = camera.GetClippingRangeAttr().Get()
        if horizontal_aperture <= 0 or vertical_aperture <= 0:
            raise ValueError("Camera aperture must be positive to calculate intrinsics")

        intrinsic_matrix = None
        if projection == "perspective":
            fx = width * focal_length / horizontal_aperture
            fy = height * focal_length / vertical_aperture
            cx = width * (0.5 + horizontal_offset / horizontal_aperture)
            cy = height * (0.5 + vertical_offset / vertical_aperture)
            intrinsic_matrix = [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]

        camera_to_world_matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        world_to_camera_matrix = camera_to_world_matrix.GetInverse()

        def matrix_rows(matrix):
            return [[float(matrix[row][column]) for column in range(4)] for row in range(4)]

        meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
        return {
            "camera_prim": prim_path,
            "resolution": {"width": width, "height": height},
            "projection": projection,
            "intrinsic_matrix": intrinsic_matrix,
            "intrinsic_convention": "pixels; origin top-left; x right; y down",
            "camera_to_world": matrix_rows(camera_to_world_matrix),
            "world_to_camera": matrix_rows(world_to_camera_matrix),
            "extrinsic_convention": "USD row-vector matrix; camera looks along local -Z with +Y up",
            "focal_length": focal_length,
            "horizontal_aperture": horizontal_aperture,
            "vertical_aperture": vertical_aperture,
            "horizontal_aperture_offset": horizontal_offset,
            "vertical_aperture_offset": vertical_offset,
            "optical_attribute_units": "tenths_of_stage_unit",
            "clipping_range": {"near": float(clipping[0]), "far": float(clipping[1]), "units": "stage_units"},
            "depth_units": "meters",
            "stage_units": "meters_per_unit",
            "meters_per_unit": meters_per_unit,
        }

    def create_lidar(self, prim_path: str, config: Optional[str] = None, **kwargs) -> Any:
        """Create a preset or validated generic Isaac Sim 6 RTX LiDAR."""
        from isaacsim.sensors.experimental.rtx import Lidar, LidarSensor

        from .lidar_config import build_generic_lidar_config

        if prim_path in self._lidar_sensors:
            self.release_sensor(prim_path, evict_metadata=False)
        variant = kwargs.pop("variant", None)
        custom_names = (
            "horizontal_fov_deg",
            "vertical_fov_deg",
            "horizontal_resolution_deg",
            "vertical_resolution_deg",
            "rotation_rate_hz",
            "min_range_m",
            "max_range_m",
        )
        custom_values = {name: kwargs.pop(name, None) for name in custom_names}
        if kwargs:
            raise ValueError("Unsupported LiDAR settings: " + ", ".join(sorted(kwargs)))
        if config is not None and any(value is not None for value in custom_values.values()):
            from .lidar_config import LidarConfigError

            raise LidarConfigError(
                "LIDAR_PRESET_CUSTOM_CONFIG_CONFLICT",
                "Named config presets cannot be combined with generic FOV, resolution, rate, or range settings",
            )
        if variant is not None and config is None:
            from .lidar_config import LidarConfigError

            raise LidarConfigError("LIDAR_VARIANT_REQUIRES_PRESET", "variant requires a named config preset")

        if config is not None:
            lidar = Lidar.create(
                path=prim_path,
                config=config,
                variant=variant,
                aux_output_level="FULL",
            )
            source_metadata = {"source": "preset", "config": config, "variant": variant}
        else:
            attributes, effective = build_generic_lidar_config(**custom_values)
            # Replicator's functional authoring path expands a plain Python
            # list into positional Vt array constructor arguments. Isaac Sim
            # 6.0.1 then raises FloatArray.__init__(FloatArray, float, ...).
            # Supply the exact USD value types at the adapter boundary.
            try:
                from pxr import Vt

                float_arrays = (
                    "omni:sensor:Core:emitterState:s001:azimuthDeg",
                    "omni:sensor:Core:emitterState:s001:elevationDeg",
                )
                uint_arrays = (
                    "omni:sensor:Core:numRaysPerLine",
                    "omni:sensor:Core:emitterState:s001:channelId",
                    "omni:sensor:Core:emitterState:s001:fireTimeNs",
                )
                for name in float_arrays:
                    attributes[name] = Vt.FloatArray(attributes[name])
                for name in uint_arrays:
                    attributes[name] = Vt.UIntArray(attributes[name])
            except (ImportError, AttributeError):
                # Offline unit tests intentionally run without pxr. Production
                # Kit always provides Vt, and the live harness covers this path.
                pass
            lidar = Lidar(
                path=prim_path,
                # A partial valid-azimuth window does not publish a completed
                # frame reliably when the model accumulates a full rotary
                # scan. Stream each sensor tick so callers can observe the
                # configured partial FOV while the timeline is running.
                accumulate_outputs=False,
                aux_output_level="FULL",
                attributes=attributes,
            )
            source_metadata = {"source": "generic", "requested": effective}

        actual_path = str(getattr(lidar, "paths", [prim_path])[0])
        self._lidar_actual_paths[prim_path] = actual_path
        self._lidar_config_metadata[prim_path] = source_metadata
        self._lidar_sensors[prim_path] = LidarSensor(
            lidar,
            annotators=["generic-model-output", "stable-id-map"],
        )
        return lidar

    def get_lidar_config(self, prim_path: str) -> Dict[str, Any]:
        """Read back the effective Core schema values from the USD prim."""
        actual_path = self._lidar_actual_paths.get(prim_path, prim_path)
        stage = self.get_stage()
        prim = stage.GetPrimAtPath(actual_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {actual_path}")

        attribute_names = {
            "valid_start_azimuth_deg": "omni:sensor:Core:validStartAzimuthDeg",
            "valid_end_azimuth_deg": "omni:sensor:Core:validEndAzimuthDeg",
            "start_azimuth_offset_deg": "omni:sensor:Core:startAzimuthOffsetDeg",
            "scan_rate_base_hz": "omni:sensor:Core:scanRateBaseHz",
            "tick_rate_hz": "omni:sensor:tickRate",
            "pattern_firing_rate_hz": "omni:sensor:Core:patternFiringRateHz",
            "near_range_m": "omni:sensor:Core:nearRangeM",
            "far_range_m": "omni:sensor:Core:farRangeM",
            "number_of_channels": "omni:sensor:Core:numberOfChannels",
            "number_of_emitters": "omni:sensor:Core:numberOfEmitters",
            "elevation_deg": "omni:sensor:Core:emitterState:s001:elevationDeg",
        }
        raw: Dict[str, Any] = {}
        for name, usd_name in attribute_names.items():
            attribute = prim.GetAttribute(usd_name)
            if not attribute.IsValid():
                raw[name] = None
                continue
            value = attribute.Get()
            if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
                value = [float(item) for item in value]
            raw[name] = value

        start = float(raw["valid_start_azimuth_deg"])
        end = float(raw["valid_end_azimuth_deg"])
        scan_rate = float(raw["scan_rate_base_hz"])
        firing_rate = float(raw["pattern_firing_rate_hz"])
        horizontal_fov = end - start
        horizontal_samples = int(round(firing_rate / scan_rate)) if scan_rate > 0 else 0
        elevations = sorted(set(float(value) for value in (raw["elevation_deg"] or [])))
        vertical_fov = elevations[-1] - elevations[0] if len(elevations) > 1 else 0.0
        gaps = [b - a for a, b in zip(elevations, elevations[1:])]
        vertical_resolution = gaps[0] if gaps and all(abs(value - gaps[0]) <= 1e-6 for value in gaps) else None
        effective = {
            "horizontal_fov_deg": horizontal_fov,
            "vertical_fov_deg": vertical_fov,
            "horizontal_resolution_deg": horizontal_fov / horizontal_samples if horizontal_samples else None,
            "vertical_resolution_deg": vertical_resolution,
            "rotation_rate_hz": scan_rate,
            "min_range_m": float(raw["near_range_m"]),
            "max_range_m": float(raw["far_range_m"]),
            "horizontal_samples": horizontal_samples,
            "vertical_channels": len(elevations),
        }
        return {
            "requested_prim_path": prim_path,
            "actual_prim_path": actual_path,
            **self._lidar_config_metadata.get(prim_path, {"source": "existing"}),
            "effective": effective,
            "schema_attributes": raw,
        }

    def get_lidar_point_cloud(self, prim_path: str) -> np.ndarray:
        frame = self.get_lidar_point_cloud_frame(prim_path)
        return frame["fields"]["points"]["data"]

    def get_lidar_point_cloud_frame(self, prim_path: str) -> Dict[str, Any]:
        """Decode one V6 GenericModelOutput frame into typed point fields."""
        # 6.0 LidarSensor uses the unified "generic-model-output" annotator;
        # the 5.x `RtxSensorCpu+IsaacComputeRTXLidarPointCloud` chain is gone.
        # See `capture_camera_image` for the caching rationale.
        import math

        from isaacsim.sensors.experimental.rtx import LidarSensor, parse_generic_model_output_data

        try:
            from isaacsim.sensors.experimental.rtx import parse_object_ids, parse_stable_id_map_data
        except ImportError:
            parse_object_ids = None
            parse_stable_id_map_data = None

        sensor = self._lidar_sensors.get(prim_path)
        if sensor is None:
            from isaacsim.sensors.experimental.rtx import Lidar

            actual_path = self._lidar_actual_paths.get(prim_path, prim_path)
            lidar = Lidar(path=actual_path, aux_output_level="FULL")
            sensor = LidarSensor(lidar, annotators=["generic-model-output", "stable-id-map"])
            self._lidar_sensors[prim_path] = sensor
        data, info = sensor.get_data("generic-model-output")
        array = None
        if data is not None:
            array = data.numpy() if hasattr(data, "numpy") else np.asarray(data)
        # LidarSensor signals "nothing rendered yet" with an empty array rather
        # than None (measured on 6.0.1: shape (0,), info {}), unlike CameraSensor
        # which returns None — so testing only for None missed the empty case.
        #
        # Deliberately no _request_render_frame() here. A single Replicator frame
        # fills a camera but not a lidar: measured on 6.0.1 with the orchestrator
        # at STEPPED and the request completed, the sensor was still empty, and
        # only play_simulation produced data. Requesting one would just make the
        # caller retry forever.
        if array is None or getattr(array, "size", 0) == 0:
            return self._empty_lidar_frame()

        # The "generic-model-output" annotator returns a packed GenericModelOutput
        # struct, not points: a uint8 buffer whose first four bytes are the magic
        # 0x4E474D4F ("OMGN"). Returning it raw meant callers received bytes and
        # the handler reported len(buffer) as a point count — 19,353,864 for one
        # frame on 6.0.1, which is the byte length.
        #
        # 5.x had a point-cloud annotator that needed no decoding; 6.0 replaced it
        # with this unified buffer plus parse_generic_model_output_data, and the
        # port kept the new annotator without adopting the decode.
        gmo = parse_generic_model_output_data(data)
        count = int(getattr(gmo, "numElements", 0) or 0)
        if count <= 0:
            return self._empty_lidar_frame()

        raw_x = list(np.asarray(gmo.x)[:count])
        raw_y = list(np.asarray(gmo.y)[:count])
        raw_z = list(np.asarray(gmo.z)[:count])
        coords_value = getattr(gmo, "elementsCoordsType", "CARTESIAN")
        coords_name = str(getattr(coords_value, "name", coords_value)).upper()
        spherical = "SPHERICAL" in coords_name

        if spherical:
            azimuth = [float(value) for value in raw_x]
            elevation = [float(value) for value in raw_y]
            ranges = [float(value) for value in raw_z]
            point_x = []
            point_y = []
            point_z = []
            for azimuth_deg, elevation_deg, range_m in zip(azimuth, elevation, ranges):
                azimuth_rad = math.radians(azimuth_deg)
                elevation_rad = math.radians(elevation_deg)
                range_xy = range_m * math.cos(elevation_rad)
                point_x.append(range_xy * math.cos(azimuth_rad))
                point_y.append(range_xy * math.sin(azimuth_rad))
                point_z.append(range_m * math.sin(elevation_rad))
            points = np.stack([point_x, point_y, point_z], axis=-1).astype(np.float32)
        else:
            point_x = [float(value) for value in raw_x]
            point_y = [float(value) for value in raw_y]
            point_z = [float(value) for value in raw_z]
            points = np.stack([point_x, point_y, point_z], axis=-1).astype(np.float32)
            ranges = [math.sqrt(x * x + y * y + z * z) for x, y, z in zip(point_x, point_y, point_z)]
            azimuth = [math.degrees(math.atan2(y, x)) for x, y in zip(point_x, point_y)]
            elevation = [
                math.degrees(math.atan2(z, math.sqrt(x * x + y * y))) for x, y, z in zip(point_x, point_y, point_z)
            ]

        fields: Dict[str, Dict[str, Any]] = {
            "points": {"data": points, "dtype": "float32", "units": "meters"},
            "range": {"data": np.asarray(ranges, dtype=np.float32), "dtype": "float32", "units": "meters"},
            "azimuth": {"data": np.asarray(azimuth, dtype=np.float32), "dtype": "float32", "units": "degrees"},
            "elevation": {"data": np.asarray(elevation, dtype=np.float32), "dtype": "float32", "units": "degrees"},
        }
        unavailable = ["semantic_id"]

        intensity = getattr(gmo, "scalar", None)
        if intensity is not None and len(intensity) >= count:
            fields["intensity"] = {
                "data": np.asarray(intensity[:count], dtype=np.float32),
                "dtype": "float32",
                "units": "normalized_return_strength",
            }
        else:
            unavailable.append("intensity")

        object_id_map: Dict[str, str] = {}
        object_ids = None
        if parse_object_ids is not None:
            try:
                object_ids = parse_object_ids(gmo.objId)[:count]
            except Exception:
                object_ids = None
        if object_ids is not None and len(object_ids) == count:
            mask = (1 << 64) - 1
            fields["object_id_low"] = {
                "data": np.asarray([int(value) & mask for value in object_ids], dtype=np.uint64),
                "dtype": "uint64",
                "units": "stable_object_id_low64",
            }
            fields["object_id_high"] = {
                "data": np.asarray([int(value) >> 64 for value in object_ids], dtype=np.uint64),
                "dtype": "uint64",
                "units": "stable_object_id_high64",
            }
            if parse_stable_id_map_data is not None:
                try:
                    stable_data, _stable_info = sensor.get_data("stable-id-map")
                    if stable_data is not None and getattr(stable_data, "size", 0) > 0:
                        stable_map = parse_stable_id_map_data(stable_data)
                        object_id_map = {f"{int(key):032x}": str(value) for key, value in stable_map.items()}
                except Exception:
                    object_id_map = {}
        else:
            unavailable.append("object_id")

        frame_value = getattr(gmo, "frameOfReference", "unknown")
        frame_name = str(getattr(frame_value, "name", frame_value)).lower()
        try:
            sensor_pose = self.get_prim_transform(self._lidar_actual_paths.get(prim_path, prim_path))
        except Exception:
            sensor_pose = None

        return {
            "fields": fields,
            "coordinate_type": "spherical" if spherical else "cartesian",
            "coordinate_frame": frame_name,
            "sensor_pose": sensor_pose,
            "sensor_timestamp_ns": int(getattr(gmo, "timestampNs", 0) or 0),
            "sensor_frame_id": int(getattr(gmo, "frameId", 0) or 0),
            "object_id_map": object_id_map,
            "unavailable_fields": unavailable,
        }

    @staticmethod
    def _empty_lidar_frame() -> Dict[str, Any]:
        return {
            "fields": {
                "points": {
                    "data": np.zeros((0, 3), dtype=np.float32),
                    "dtype": "float32",
                    "units": "meters",
                }
            },
            "coordinate_frame": "unknown",
            "unavailable_fields": ["intensity", "range", "azimuth", "elevation", "object_id", "semantic_id"],
        }

    # ── Materials ──────────────────────────────────────────

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
        from pxr import UsdPhysics

        stage = self.get_stage()
        material = UsdPhysics.MaterialAPI.Apply(stage.DefinePrim(prim_path))
        material.CreateStaticFrictionAttr(static_friction)
        material.CreateDynamicFrictionAttr(dynamic_friction)
        material.CreateRestitutionAttr(restitution)
        return material

    def apply_material(self, material_path: str, target_prim_path: str) -> None:
        from pxr import UsdShade

        stage = self.get_stage()
        material = UsdShade.Material(stage.GetPrimAtPath(material_path))
        target = stage.GetPrimAtPath(target_prim_path)
        UsdShade.MaterialBindingAPI(target).Bind(material)

    # ── Lighting ───────────────────────────────────────────

    def create_light(
        self,
        light_type: str,
        prim_path: str,
        intensity: float = 1000.0,
        color: Optional[Sequence[float]] = None,
        **kwargs,
    ) -> Any:
        from pxr import Gf, UsdLux

        stage = self.get_stage()
        light_classes = {
            "DistantLight": UsdLux.DistantLight,
            "DomeLight": UsdLux.DomeLight,
            "SphereLight": UsdLux.SphereLight,
            "RectLight": UsdLux.RectLight,
            "DiskLight": UsdLux.DiskLight,
            "CylinderLight": UsdLux.CylinderLight,
        }
        cls = light_classes.get(light_type)
        if not cls:
            raise ValueError(f"Unknown light type: {light_type}. Options: {list(light_classes.keys())}")
        light = cls.Define(stage, prim_path)
        light.CreateIntensityAttr(intensity)
        if color:
            light.CreateColorAttr(Gf.Vec3f(*color[:3]))
        position = kwargs.get("position")
        if position:
            self.set_prim_transform(prim_path, position=position)
        rotation = kwargs.get("rotation")
        if rotation:
            self.set_prim_transform(prim_path, rotation=rotation)
        return light

    def modify_light(
        self,
        prim_path: str,
        intensity: Optional[float] = None,
        color: Optional[Sequence[float]] = None,
    ) -> None:
        from pxr import Gf

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Light not found: {prim_path}")
        if intensity is not None:
            prim.GetAttribute("inputs:intensity").Set(intensity)
        if color is not None:
            prim.GetAttribute("inputs:color").Set(Gf.Vec3f(*color[:3]))

    # ── Assets ─────────────────────────────────────────────

    def clone_prim(self, source_path: str, target_path: str) -> None:
        import omni.kit.commands

        omni.kit.commands.execute("CopyPrim", path_from=source_path, path_to=target_path)

    # ── Assets ─────────────────────────────────────────────

    def import_urdf(self, urdf_path: str, prim_path: str = "/World/robot", **kwargs) -> Any:
        # 6.0 splits URDF import into two steps:
        #   1) URDFImporter.import_urdf() converts the .urdf to a .usd on disk
        #      (the `dest_path` kwarg from 5.x is gone — output dir is chosen
        #      via `usd_path` on the config, defaulting to the URDF's directory)
        #   2) the caller references that .usd into the live stage
        import os
        import tempfile

        if not os.path.isfile(urdf_path):
            raise FileNotFoundError(f"URDF file not found: {urdf_path}")
        from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig

        usd_out_dir = kwargs.pop("usd_path", None) or tempfile.mkdtemp(prefix="urdf_import_")
        config = URDFImporterConfig(urdf_path=urdf_path, usd_path=usd_out_dir, **kwargs)
        importer = URDFImporter(config)
        usd_path = importer.import_urdf()
        # Bring the generated USD into the live stage at the requested prim path
        return self.add_reference_to_stage(usd_path, prim_path)

    # ── Simulation ─────────────────────────────────────────

    def play(self) -> None:
        import omni.timeline

        self._ensure_physics_world()
        timeline = omni.timeline.get_timeline_interface()
        timeline.play()
        # CameraSensor's 6.0.1 reference flow commits the transition before the
        # next app update. This makes Play visible immediately to Replicator and
        # triggers its capture-on-play callbacks deterministically.
        timeline.commit()

    def pause(self) -> None:
        import omni.timeline

        omni.timeline.get_timeline_interface().pause()

    def stop(self) -> None:
        import omni.timeline

        # timeline.stop() already restores rigid bodies / articulations to their
        # spawn pose — it is what the Isaac UI Stop button does. Verified on
        # 6.0.1: a cube dropped from z=2 returns to exactly z=2 after this call.
        #
        # There used to be a SimulationManager.reset_simulation() here. That
        # method does not exist on 6.0.1 — the call raised
        # "type object 'SimulationManager' has no attribute 'reset_simulation'"
        # on every stop and a bare except swallowed it, so stop_simulation
        # reported success while doing nothing beyond the line above. Do not
        # reintroduce it without checking the API actually exists.
        omni.timeline.get_timeline_interface().stop()

    def step(
        self,
        num_steps: int = 1,
        observe_prims: Optional[List[str]] = None,
        observe_joints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # SimulationManager.step pumps only the physics pipeline (no asyncio
        # event-loop reentry), which avoids the "Cannot enter into task" errors
        # that omni.kit.app.update() triggers when called from inside the MCP
        # dispatch coroutine on Kit 107 (Isaac Sim 6.0). SocketServer
        # ._dispatch_command documents this as a hard constraint on handlers.
        #
        # Do NOT drive the *stepping* with app.update() here, the way V5 does.
        # Two separate reasons, and only the second is fatal:
        #
        # 1. It changes the physics. Pumped stepping runs real frames at the
        #    app's cadence and cannot stop the timeline on an exact boundary,
        #    so the same 60-frame fall lands at z=-2.987 instead of the
        #    SimulationManager.step result of z=-3.322, and the timeline is
        #    still playing on return — free-running between MCP calls is the
        #    imprecision step_simulation exists to remove.
        # 2. It has been observed to flood the log with
        #     RuntimeError: Cannot enter into task <...> while another task
        #     <SocketServer._dispatch_command...execute_wrapper> is being executed
        # killing unrelated kit tasks mid-flight (property window, viewport,
        # USD cache listener, throttling, HTTP server) and invalidating the
        # physics tensor view, after which get_velocities/get_transforms fail
        # with "Simulation view object is invalidated".
        #
        # That flood did not reproduce on 6.0.1/physx when re-checked: 60
        # pumped updates from inside this coroutine logged no task errors and
        # left the tensor view valid, so the hazard is evidently state- or
        # backend-dependent rather than unconditional. Treat it as real but not
        # universal, and keep the exactness argument in (1) as the standing
        # reason. _arm_reset_point does pump exactly once, guarded, because a
        # tick-late restore point breaks stop_simulation outright.
        from isaacsim.core.simulation_manager import SimulationManager

        self._ensure_physics_world()
        self._arm_reset_point()
        SimulationManager.step(steps=num_steps)

        result: Dict[str, Any] = {"stepped": num_steps}

        if observe_prims:
            from pxr import UsdPhysics

            prim_states = []
            stage = self.get_stage()
            for path in observe_prims:
                prim = stage.GetPrimAtPath(path)
                if not prim.IsValid():
                    prim_states.append({"prim_path": path, "error": "Prim not found"})
                    continue
                state: Dict[str, Any] = {"prim_path": path}
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    try:
                        from isaacsim.core.simulation_manager import SimulationManager

                        view = SimulationManager.get_physics_simulation_view()
                        rb_view = view.create_rigid_body_view([path]) if view is not None else None
                        if rb_view is not None:
                            transforms = rb_view.get_transforms()
                            arr = transforms.numpy() if hasattr(transforms, "numpy") else np.asarray(transforms)
                            if arr.size >= 3:
                                flat = arr.reshape(-1)
                                state["position"] = [float(flat[0]), float(flat[1]), float(flat[2])]
                        else:
                            transform = self.get_prim_transform(path)
                            state["position"] = transform.get("position", [0, 0, 0])
                    except Exception:
                        transform = self.get_prim_transform(path)
                        state["position"] = transform.get("position", [0, 0, 0])
                else:
                    transform = self.get_prim_transform(path)
                    state["position"] = transform.get("position", [0, 0, 0])
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    try:
                        ps = self.get_physics_state(path)
                        state["linear_velocity"] = ps.get("linear_velocity", [0, 0, 0])
                        state["angular_velocity"] = ps.get("angular_velocity", [0, 0, 0])
                    except Exception:
                        pass
                prim_states.append(state)
            result["prim_states"] = prim_states

        if observe_joints:
            joint_states = []
            for path in observe_joints:
                try:
                    positions = self.get_joint_positions(path)
                    names = self._get_joint_names(path)
                    joints_dict = dict(zip(names, positions)) if names else {"positions": positions}
                    joint_states.append({"prim_path": path, "joints": joints_dict})
                except Exception as e:
                    joint_states.append({"prim_path": path, "error": str(e)})
            result["joint_states"] = joint_states

        return result

    def get_simulation_state(self) -> Dict[str, Any]:
        import omni.timeline
        from pxr import UsdPhysics

        timeline = omni.timeline.get_timeline_interface()
        is_playing = timeline.is_playing()
        is_stopped = timeline.is_stopped()
        if is_playing:
            timeline_state = "playing"
        elif is_stopped:
            timeline_state = "stopped"
        else:
            timeline_state = "paused"

        # Report the physics clock, not the timeline clock. V6 advances physics
        # with SimulationManager.step(), which never runs the timeline (handlers
        # may not pump kit's event loop — see step), so timeline.get_current_time()
        # stays at 0.0 for the entire step-only debug loop no matter how far the
        # simulation has run. SimulationManager.get_simulation_time() tracks every
        # physics step and resets to 0 on stop, which is the "time since this run
        # began" that callers expect. Measured on 6.0.1: +1.0000s per step(60),
        # and back to ~0 after stop.
        try:
            from isaacsim.core.simulation_manager import SimulationManager

            current_time = float(SimulationManager.get_simulation_time())
        except Exception:
            current_time = timeline.get_current_time()
        stage = self.get_stage()
        physics_dt = 1.0 / 60.0
        # Kit accepts MCP commands before it has created a stage — measured on
        # 6.0.1 the socket opens 2.86s ahead of it, and 5.1.0 behaves the same.
        # Traversing None there raised "'NoneType' object has no attribute
        # 'Traverse'", turning a routine status query into an opaque error during
        # startup. The timeline state is still knowable, so report that and fall
        # back to the default physics_dt.
        prims = stage.Traverse() if stage is not None else []
        for prim in prims:
            try:
                if prim.IsA(UsdPhysics.Scene):
                    time_step_attr = prim.GetAttribute("physxScene:timeStepsPerSecond")
                    if time_step_attr and time_step_attr.Get():
                        steps_per_sec = time_step_attr.Get()
                        if steps_per_sec > 0:
                            physics_dt = 1.0 / steps_per_sec
                    break
            except Exception:
                pass

        return {
            "timeline_state": timeline_state,
            "current_time": current_time,
            "physics_dt": physics_dt,
            "engine": self._engine,
            "isaacsim_version": self._isaacsim_version,
        }

    def execute_script(self, code: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        import io
        import sys
        import traceback

        import carb
        import omni
        from pxr import Gf, Sdf, Usd, UsdGeom

        if cwd and cwd not in sys.path:
            sys.path.insert(0, cwd)

        local_ns = {"omni": omni, "carb": carb, "Usd": Usd, "UsdGeom": UsdGeom, "Sdf": Sdf, "Gf": Gf}

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = captured_out = io.StringIO()
        sys.stderr = captured_err = io.StringIO()
        try:
            self._ensure_physics_world()
            exec(code, local_ns)
            out = captured_out.getvalue()
            if out.strip():
                try:
                    from ..handlers.simulation import append_log

                    for line in out.splitlines():
                        append_log(f"[PRINT] {line}")
                except Exception:
                    pass
            return {
                "status": "success",
                "message": "Script executed successfully",
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        except Exception as e:
            out = captured_out.getvalue()
            if out.strip():
                try:
                    from ..handlers.simulation import append_log

                    for line in out.splitlines():
                        append_log(f"[PRINT] {line}")
                except Exception:
                    pass
            return {
                "status": "error",
                "message": str(e),
                "traceback": traceback.format_exc(),
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    _exec_namespaces: Dict[str, dict] = {}

    def reload_script(self, file_path: str, module_name: Optional[str] = None) -> Dict[str, Any]:
        import importlib
        import io
        import os
        import sys
        import traceback

        parent_dir = os.path.dirname(os.path.abspath(file_path))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)

        abs_path = os.path.abspath(file_path)

        # ScriptNode-aware reload: if any Action-Graph ScriptNode references this
        # file via inputs:scriptPath, force it to recompile (the standalone
        # re-exec below would not touch the running graph node).
        recompiled = _recompile_scriptnodes_for_file(abs_path)
        if recompiled:
            return {
                "status": "success",
                "message": f"Recompiled ScriptNode(s) referencing {os.path.basename(file_path)}",
                "recompiled_nodes": recompiled,
            }

        old_ns = self._exec_namespaces.get(abs_path)
        if old_ns:
            for key, val in old_ns.items():
                if hasattr(val, "unsubscribe"):
                    try:
                        val.unsubscribe()
                    except Exception:
                        pass

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = captured_out = io.StringIO()
        sys.stderr = captured_err = io.StringIO()
        try:
            if module_name:
                if module_name in sys.modules:
                    _module = importlib.reload(sys.modules[module_name])
                    msg = f"Module '{module_name}' reloaded successfully"
                else:
                    _module = importlib.import_module(module_name)
                    msg = f"Module '{module_name}' imported successfully"
            else:
                if not os.path.isfile(file_path):
                    return {"status": "error", "message": f"File not found: {file_path}"}
                with open(file_path, "r") as f:
                    code = f.read()
                import carb
                import omni
                from pxr import Gf, Sdf, Usd, UsdGeom

                local_ns = {
                    "omni": omni,
                    "carb": carb,
                    "Usd": Usd,
                    "UsdGeom": UsdGeom,
                    "Sdf": Sdf,
                    "Gf": Gf,
                    "__file__": file_path,
                }
                self._ensure_physics_world()
                exec(code, local_ns)
                self._exec_namespaces[abs_path] = local_ns
                msg = f"Script '{os.path.basename(file_path)}' executed successfully"

            out = captured_out.getvalue()
            if out.strip():
                try:
                    from ..handlers.simulation import append_log

                    for line in out.splitlines():
                        append_log(f"[PRINT] {line}")
                except Exception:
                    pass
            return {
                "status": "success",
                "message": msg,
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        except Exception as e:
            out = captured_out.getvalue()
            if out.strip():
                try:
                    from ..handlers.simulation import append_log

                    for line in out.splitlines():
                        append_log(f"[PRINT] {line}")
                except Exception:
                    pass
            return {
                "status": "error",
                "message": str(e),
                "traceback": traceback.format_exc(),
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
