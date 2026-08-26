# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Robot articulation, joint command, and drive configuration runtime."""

from __future__ import annotations

import math
import weakref
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..base import IsaacAdapterBase, JointDriveConfigApplyError
from ..units import limit_units, normalize_limit
from .physics import PhysicsRuntime
from .scene import SceneRuntime


class RobotPolicyBridge:
    """Expose cross-domain facade policy without making RobotRuntime own it."""

    def __init__(self, adapter: IsaacAdapterBase) -> None:
        self._adapter_ref = weakref.ref(adapter)

    def _adapter(self) -> IsaacAdapterBase:
        adapter = self._adapter_ref()
        if adapter is None:
            raise RuntimeError("Isaac adapter facade is no longer available")
        return adapter

    @property
    def active_backend(self) -> str:
        return str(getattr(self._adapter(), "_engine", "unknown"))

    def get_simulation_state(self) -> Dict[str, Any]:
        return self._adapter().get_simulation_state()

    def require_backend_capability(self, feature: str) -> Dict[str, Any]:
        return self._adapter().require_backend_capability(feature)


class RobotRuntime:
    """Own V6 articulation wrappers and robot/joint/drive raw runtime calls."""

    def __init__(self, scene: SceneRuntime, physics: PhysicsRuntime, bridge: RobotPolicyBridge) -> None:
        self._scene = scene
        self._physics = physics
        self._bridge = bridge
        self._articulations: Dict[str, Any] = {}

    def clear_runtime_cache(self) -> None:
        self._articulations.clear()

    def get_stage(self):
        return self._scene.get_stage()

    def _ensure_physics_world(self) -> None:
        self._physics._ensure_physics_world()

    @property
    def _engine(self) -> str:
        return self._bridge.active_backend

    def get_simulation_state(self) -> Dict[str, Any]:
        return self._bridge.get_simulation_state()

    def require_backend_capability(self, feature: str) -> Dict[str, Any]:
        return self._bridge.require_backend_capability(feature)

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
            array_kwargs = {"device": art._device} if getattr(art, "_device", None) is not None else {}
            positions_arr = wp.array(np.asarray([list(positions)], dtype=np.float32), dtype=wp.float32, **array_kwargs)
            if joint_indices is not None:
                idx_arr = wp.array(np.asarray(joint_indices, dtype=np.int32), dtype=wp.int32, **array_kwargs)
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

        array_kwargs = {"device": art._device} if getattr(art, "_device", None) is not None else {}
        values_arr = wp.array(np.asarray([list(values)], dtype=np.float32), dtype=wp.float32, **array_kwargs)
        indices_arr = wp.array(np.asarray(selected, dtype=np.int32), dtype=wp.int32, **array_kwargs)
        if mode == "position":
            art.set_dof_position_targets(values_arr, dof_indices=indices_arr)
        elif mode == "velocity":
            art.set_dof_velocity_targets(values_arr, dof_indices=indices_arr)
        elif mode == "effort":
            art.set_dof_efforts(values_arr, dof_indices=indices_arr)
        else:
            raise ValueError(f"Unsupported joint command mode: {mode}")

    def compute_holonomic_wheel_velocities(
        self,
        prim_path: str,
        com_prim_path: str,
        command: Sequence[float],
        joint_names: Sequence[str],
    ) -> List[float]:
        """Use NVIDIA's V6 USD setup and QP controller for a Kaya profile."""
        from isaacsim.robot.experimental.wheeled_robots.controllers import HolonomicController
        from isaacsim.robot.experimental.wheeled_robots.robots import HolonomicRobotUsdSetup

        stage = self.get_stage()
        if not stage.GetPrimAtPath(prim_path).IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        if not stage.GetPrimAtPath(com_prim_path).IsValid():
            raise ValueError(f"Holonomic center-of-mass prim not found: {com_prim_path}")
        setup = HolonomicRobotUsdSetup(robot_prim_path=prim_path, com_prim_path=com_prim_path)
        wheel_radius, wheel_positions, wheel_orientations, mecanum_angles, wheel_axis, up_axis = (
            setup.get_holonomic_controller_params()
        )
        controller = HolonomicController(
            wheel_radius=wheel_radius,
            wheel_positions=wheel_positions,
            wheel_orientations=wheel_orientations,
            mecanum_angles=mecanum_angles,
            wheel_axis=wheel_axis,
            up_axis=up_axis,
        )
        action = controller.forward(np.asarray(command, dtype=np.float64))
        # Isaac Sim 6 experimental HolonomicController returns an ndarray;
        # older controller variants wrap it in ArticulationAction.
        values = getattr(action, "joint_velocities", action)
        if values is None or len(values) != len(wheel_positions):
            raise RuntimeError("HolonomicController returned an invalid wheel velocity vector")
        setup_names = list(setup.get_articulation_controller_params())
        if len(set(setup_names)) != len(setup_names) or set(setup_names) != set(joint_names):
            raise ValueError(
                f"USD mecanum joint names {setup_names} do not exactly match profile joints {list(joint_names)}"
            )
        by_name = dict(zip(setup_names, values))
        return [float(by_name[name]) for name in joint_names]

    @staticmethod
    def _drive_units(joint_type: str) -> Dict[str, str]:
        if joint_type == "revolute":
            return {
                "stiffness": "newton_meters_per_radian",
                "damping": "newton_meter_seconds_per_radian",
                "max_force": "newton_meters",
                "max_velocity": "radians_per_second",
            }
        if joint_type == "prismatic":
            return {
                "stiffness": "newtons_per_meter",
                "damping": "newton_seconds_per_meter",
                "max_force": "newtons",
                "max_velocity": "meters_per_second",
            }
        return {field: "unknown" for field in ("stiffness", "damping", "max_force", "max_velocity")}

    def _drive_config_articulation(self, prim_path: str) -> Any:
        """Return a fresh USD-backed wrapper, avoiding stale tensor-view caches."""
        from isaacsim.core.experimental.prims import Articulation

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        art = Articulation(paths=[prim_path])
        if not art.valid:
            raise ValueError(f"Invalid articulation at {prim_path}")
        return art

    def get_joint_drive_config(self, prim_path: str) -> Dict[str, Any]:
        """Read typed drive configuration using the V6 Articulation USD backend."""
        self._ensure_physics_world()
        art = self._drive_config_articulation(prim_path)
        names = list(art.dof_names or [])
        types = [self._joint_type_name(value) for value in list(art.dof_types or [])]
        if not names:
            raise ValueError(f"No articulation DOFs found at {prim_path}")

        stiffnesses_raw, dampings_raw = art.get_dof_gains()
        stiffnesses = self._flatten_joint_values(stiffnesses_raw)
        dampings = self._flatten_joint_values(dampings_raw)
        max_forces = self._flatten_joint_values(art.get_dof_max_efforts())
        drive_types_raw = art.get_dof_drive_types()
        drive_types = list(drive_types_raw[0]) if drive_types_raw else []
        if self._engine == "newton":
            max_velocities: List[Optional[float]] = [None] * len(names)
        else:
            max_velocities = self._flatten_joint_values(art.get_dof_max_velocities())

        values_by_field = {
            "joint_types": types,
            "stiffness": stiffnesses,
            "damping": dampings,
            "max_force": max_forces,
            "max_velocity": max_velocities,
            "drive_type": drive_types,
        }
        for field, values in values_by_field.items():
            if len(values) != len(names):
                raise RuntimeError(f"Articulation returned {len(values)} {field} entries for {len(names)} joints")

        joints = []
        for index, name in enumerate(names):
            joint_type = types[index]
            joints.append(
                {
                    "index": index,
                    "name": name,
                    "type": joint_type,
                    "stiffness": stiffnesses[index],
                    "damping": dampings[index],
                    "max_force": max_forces[index],
                    "max_velocity": max_velocities[index],
                    "drive_type": drive_types[index],
                    "units": self._drive_units(joint_type),
                }
            )
        return {"prim_path": prim_path, "joint_count": len(joints), "joints": joints}

    def set_joint_drive_config(
        self,
        prim_path: str,
        config: Dict[str, Any],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        """Author selected USD drive fields and restore every changed opinion on failure."""
        self._ensure_physics_world()
        state = self.get_simulation_state()
        if str(state.get("timeline_state", "unknown")).lower() != "stopped":
            raise RuntimeError("Drive configuration requires a stopped timeline")
        if "max_velocity" in config:
            self.require_backend_capability("robot.joint_drive_config.max_velocity")

        art = self._drive_config_articulation(prim_path)
        count = len(list(art.dof_names or []))
        selected = list(range(count)) if joint_indices is None else list(joint_indices)
        if (
            not selected
            or len(set(selected)) != len(selected)
            or any(index < 0 or index >= count for index in selected)
        ):
            raise ValueError("Drive configuration contains an invalid or duplicate DOF index")

        from pxr import PhysxSchema, UsdPhysics

        paths = list((art.dof_paths or [[]])[0])
        joint_types = [self._joint_type_name(value) for value in list(art.dof_types or [])]
        if len(paths) != count or len(joint_types) != count:
            raise RuntimeError("Articulation DOF metadata is incomplete for drive authoring")

        stage = self.get_stage()
        snapshots: List[tuple[Any, bool, Any]] = []
        newly_applied: List[tuple[Any, Any, Optional[str]]] = []

        def _snapshot_and_set(attribute: Any, value: Any, label: str) -> None:
            authored = bool(attribute.HasAuthoredValueOpinion())
            previous = attribute.Get() if authored else None
            snapshots.append((attribute, authored, previous))
            if not attribute.Set(value):
                raise RuntimeError(f"Failed to author {label}")

        try:
            for index in selected:
                prim = stage.GetPrimAtPath(paths[index])
                if not prim.IsValid():
                    raise ValueError(f"Joint prim not found: {paths[index]}")
                joint_type = joint_types[index]
                if joint_type not in {"revolute", "prismatic"}:
                    raise ValueError(f"Unsupported DOF type at index {index}: {joint_type}")
                drive_axis = "angular" if joint_type == "revolute" else "linear"
                drive = UsdPhysics.DriveAPI.Get(prim, drive_axis)
                if not drive:
                    drive = UsdPhysics.DriveAPI.Apply(prim, drive_axis)
                    if not drive:
                        raise RuntimeError(f"Could not apply {drive_axis} DriveAPI at {paths[index]}")
                    newly_applied.append((prim, UsdPhysics.DriveAPI, drive_axis))

                if "drive_type" in config:
                    _snapshot_and_set(drive.GetTypeAttr(), config["drive_type"], f"drive_type[{index}]")
                if "stiffness" in config:
                    value = config["stiffness"]
                    if joint_type == "revolute":
                        value *= math.pi / 180.0
                    _snapshot_and_set(drive.GetStiffnessAttr(), value, f"stiffness[{index}]")
                if "damping" in config:
                    value = config["damping"]
                    if joint_type == "revolute":
                        value *= math.pi / 180.0
                    _snapshot_and_set(drive.GetDampingAttr(), value, f"damping[{index}]")
                if "max_force" in config:
                    _snapshot_and_set(drive.GetMaxForceAttr(), config["max_force"], f"max_force[{index}]")
                if "max_velocity" in config:
                    had_physx_api = prim.HasAPI(PhysxSchema.PhysxJointAPI)
                    physx_joint = (
                        PhysxSchema.PhysxJointAPI(prim) if had_physx_api else PhysxSchema.PhysxJointAPI.Apply(prim)
                    )
                    if not physx_joint:
                        raise RuntimeError(f"Could not apply PhysxJointAPI at {paths[index]}")
                    if not had_physx_api:
                        newly_applied.append((prim, PhysxSchema.PhysxJointAPI, None))
                    value = config["max_velocity"]
                    if joint_type == "revolute":
                        value *= 180.0 / math.pi
                    _snapshot_and_set(
                        physx_joint.GetMaxJointVelocityAttr(),
                        value,
                        f"max_velocity[{index}]",
                    )
        except Exception as apply_error:
            rollback_errors = []
            for attribute, authored, previous in reversed(snapshots):
                try:
                    restored = attribute.Set(previous) if authored else attribute.Clear()
                    if not restored:
                        rollback_errors.append(f"attribute {attribute.GetPath()}: restore returned false")
                except Exception as exc:
                    rollback_errors.append(f"attribute restore: {exc}")
            for prim, schema, instance in reversed(newly_applied):
                try:
                    removed = prim.RemoveAPI(schema, instance) if instance is not None else prim.RemoveAPI(schema)
                    if not removed:
                        rollback_errors.append(f"API {schema}: remove returned false")
                except Exception as exc:
                    rollback_errors.append(f"API remove: {exc}")
            if rollback_errors:
                raise JointDriveConfigApplyError(
                    f"Drive configuration failed: {apply_error}; rollback failed: {rollback_errors}",
                    rollback_succeeded=False,
                ) from apply_error
            raise JointDriveConfigApplyError(
                f"Drive configuration failed: {apply_error}; rollback succeeded",
                rollback_succeeded=True,
            ) from apply_error

    def get_joint_config(self, prim_path: str) -> Dict[str, Any]:
        from pxr import Usd, UsdPhysics

        self._ensure_physics_world()
        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        joint_names = self._get_joint_names(prim_path)
        current_pos_list = self.get_joint_positions(prim_path)
        typed_drive = self.get_joint_drive_config(prim_path)
        typed_drive_by_name = {joint["name"]: joint for joint in typed_drive["joints"]}

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
                if jname in typed_drive_by_name:
                    typed = typed_drive_by_name[jname]
                    joint_data.update(
                        {
                            "stiffness": typed["stiffness"],
                            "damping": typed["damping"],
                            "max_force": typed["max_force"],
                            "max_velocity": typed["max_velocity"],
                            "drive_type": typed["drive_type"],
                            "drive_units": typed["units"],
                        }
                    )
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
