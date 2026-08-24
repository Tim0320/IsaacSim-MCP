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

"""Abstract base adapter for Isaac Sim version-specific APIs."""

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:
    from pxr import Usd


class SensorLifecycleError(RuntimeError):
    """A sensor runtime could not be deterministically released."""

    code = "SENSOR_RELEASE_FAILED"

    def __init__(self, message: str, report: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.report = report or {}


class JointDriveConfigApplyError(RuntimeError):
    """A drive write failed after apply began, with explicit rollback status."""

    def __init__(self, message: str, *, rollback_succeeded: bool) -> None:
        super().__init__(message)
        self.rollback_succeeded = rollback_succeeded


class IsaacAdapterBase(ABC):
    """Abstract interface that isolates all Isaac Sim version-specific API calls.

    Handler code should never import isaacsim.* directly — use this adapter instead.
    Each supported Isaac Sim version provides a concrete implementation.
    """

    # ── Scene ──────────────────────────────────────────────

    @abstractmethod
    def get_stage(self) -> Usd.Stage:
        """Return the current USD stage."""
        ...

    @abstractmethod
    def get_assets_root_path(self) -> str:
        """Return the root path for Isaac Sim built-in assets."""
        ...

    @abstractmethod
    def discover_environments(self) -> Dict[str, Dict[str, str]]:
        """Scan the asset server for available environment USD files."""
        ...

    @abstractmethod
    def load_environment(self, env_path: str, prim_path: str = "/Environment") -> None:
        """Load an environment USD into the stage."""
        ...

    # ── Prims ──────────────────────────────────────────────

    @abstractmethod
    def create_prim(self, prim_path: str, prim_type: str = "Xform", **kwargs) -> Usd.Prim:
        """Create a USD prim at the given path."""
        ...

    @abstractmethod
    def delete_prim(self, prim_path: str) -> bool:
        """Delete a prim from the stage. Returns True on success."""
        ...

    @abstractmethod
    def add_reference_to_stage(self, usd_path: str, prim_path: str) -> Usd.Prim:
        """Add a USD reference to the stage at prim_path."""
        ...

    @abstractmethod
    def set_prim_transform(
        self,
        prim_path: str,
        position: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
        scale: Optional[Sequence[float]] = None,
    ) -> None:
        """Set position, rotation, and/or scale on a prim."""
        ...

    @abstractmethod
    def get_prim_transform(self, prim_path: str) -> Dict[str, Any]:
        """Return position, rotation, scale of a prim."""
        ...

    @abstractmethod
    def list_prims(self, root_path: str = "/", prim_type: Optional[str] = None) -> List[Dict[str, str]]:
        """List prims under root_path, optionally filtered by type."""
        ...

    @abstractmethod
    def get_prim_info(self, prim_path: str) -> Dict[str, Any]:
        """Return detailed info about a prim (type, transform, properties)."""
        ...

    @abstractmethod
    def get_prim_actual_size(self, prim_path: str) -> Tuple[List[float], Tuple[List[float], List[float]]]:
        """Return actual dimensions and bounding box for a geometric prim.

        Returns:
            A tuple of (actual_size, (bbox_min, bbox_max)) where:
            - actual_size: [x, y, z] dimensions in meters (default_size * scale)
            - bbox_min: [x, y, z] world-space minimum corner
            - bbox_max: [x, y, z] world-space maximum corner
        """
        ...

    # ── Robots ─────────────────────────────────────────────

    @abstractmethod
    def create_xform_prim(self, prim_path: str) -> Any:
        """Create an XFormPrim wrapper for positioning."""
        ...

    @abstractmethod
    def create_articulation(self, prim_path: str, name: str) -> Any:
        """Create an Articulation wrapper for a robot at prim_path."""
        ...

    @abstractmethod
    def discover_robots(self) -> Dict[str, Dict[str, str]]:
        """Scan the asset server for available robot USD files.

        Returns a dict mapping robot key to {"asset_path": ..., "description": ..., "manufacturer": ...}.
        """
        ...

    @abstractmethod
    def get_robot_joint_info(self, prim_path: str) -> Dict[str, Any]:
        """Return joint names, DOF count, and current positions for a robot."""
        ...

    @abstractmethod
    def set_joint_positions(
        self, prim_path: str, positions: Sequence[float], joint_indices: Optional[List[int]] = None
    ) -> None:
        """Set target joint positions on a robot articulation."""
        ...

    @abstractmethod
    def get_joint_positions(self, prim_path: str) -> List[float]:
        """Read current joint positions from a robot articulation."""
        ...

    def get_joint_state(self, prim_path: str) -> Dict[str, Any]:
        """Read complete measured state and command targets for an articulation.

        The legacy default preserves position-only support. Isaac Sim 6.x
        overrides this with tensor-backed velocity, effort, and target data.
        """
        info = self.get_robot_joint_info(prim_path)
        names = list(info.get("joint_names", []))
        joint_types = [str(item.get("type", "unknown")) for item in info.get("joint_limits", [])]
        return {
            "prim_path": prim_path,
            "joint_names": names,
            "joint_types": joint_types,
            "positions": self.get_joint_positions(prim_path),
            "velocities": None,
            "efforts": None,
            "position_targets": None,
            "velocity_targets": None,
            "effort_targets": None,
        }

    def set_joint_command(
        self,
        prim_path: str,
        mode: str,
        values: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        """Apply one validated joint command.

        Legacy adapters retain their existing position target path. Velocity
        and effort require the Isaac Sim 6.x adapter.
        """
        if mode == "position":
            self.set_joint_positions(prim_path, values, joint_indices)
            return
        raise NotImplementedError(f"Joint command mode '{mode}' requires the Isaac Sim 6.x adapter")

    def compute_ik(self, **_params: Any) -> Dict[str, Any]:
        """Solve inverse kinematics without applying a command."""
        raise NotImplementedError("Motion generation requires the Isaac Sim 6.x adapter")

    def plan_joint_trajectory(self, **_params: Any) -> Dict[str, Any]:
        """Create an opaque, executable trajectory."""
        raise NotImplementedError("Motion generation requires the Isaac Sim 6.x adapter")

    def execute_trajectory(self, **_params: Any) -> Dict[str, Any]:
        """Start a non-blocking trajectory job."""
        raise NotImplementedError("Motion execution requires the Isaac Sim 6.x adapter")

    def cancel_motion(self, **_params: Any) -> Dict[str, Any]:
        """Cancel a running trajectory job."""
        raise NotImplementedError("Motion execution requires the Isaac Sim 6.x adapter")

    def get_motion_status(self, **_params: Any) -> Dict[str, Any]:
        """Return a trajectory job snapshot."""
        raise NotImplementedError("Motion execution requires the Isaac Sim 6.x adapter")

    def shutdown_motion(self) -> None:
        """Release motion update subscriptions during extension shutdown."""
        return None

    def compute_holonomic_wheel_velocities(
        self,
        prim_path: str,
        com_prim_path: str,
        command: Sequence[float],
        joint_names: Sequence[str],
    ) -> List[float]:
        """Resolve USD geometry and return targets in the requested joint-name order."""
        raise NotImplementedError("Holonomic controller profiles require the Isaac Sim 6.x adapter")

    def get_joint_drive_config(self, prim_path: str) -> Dict[str, Any]:
        """Return typed drive gains, limits, and drive modes in runtime units."""
        raise NotImplementedError("Joint drive configuration requires the Isaac Sim 6.x adapter")

    def set_joint_drive_config(
        self,
        prim_path: str,
        config: Dict[str, Any],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        """Atomically apply one validated drive configuration to selected DOFs."""
        raise NotImplementedError("Joint drive configuration requires the Isaac Sim 6.x adapter")

    @abstractmethod
    def get_joint_config(self, prim_path: str) -> Dict[str, Any]:
        """Return joint drive configuration: stiffness, damping, limits, target vs actual positions."""
        ...

    # ── Physics ────────────────────────────────────────────

    @abstractmethod
    def create_world(self, **kwargs) -> Any:
        """Create a World instance for simulation management."""
        ...

    @abstractmethod
    def create_simulation_context(self, **kwargs) -> Any:
        """Create a SimulationContext for physics stepping."""
        ...

    @abstractmethod
    def create_physics_scene(self, gravity: Optional[Sequence[float]] = None, scene_name: str = "PhysicsScene") -> str:
        """Create a physics scene prim with gravity settings."""
        ...

    @abstractmethod
    def get_physics_state(self, prim_path: str) -> Dict[str, Any]:
        """Return physics state for a prim: rigid body, mass, velocities, contacts."""
        ...

    # ── Sensor lifecycle ───────────────────────────────────

    def release_sensor(self, prim_path: str, *, evict_metadata: bool = True) -> Dict[str, Any]:
        """Destroy and forget one cached RTX sensor with auditable teardown.

        Isaac Sim 6.0.1 ``_SensorRuntime`` owns the annotators, writers and
        Hydra texture. Its ``_invalidate_sensor`` method is the implementation
        used by ``__del__`` and is the only complete teardown path. Calling
        ``detach_annotators`` without the required annotator list raises and
        leaves the render product alive, so lifecycle errors must remain
        explicit and the cache reference must remain available for a retry.
        """
        actual_paths = getattr(self, "_lidar_actual_paths", None)
        actual_prim_path = actual_paths.get(prim_path, prim_path) if actual_paths is not None else prim_path
        sensor = None
        sensor_type = None
        cache = None
        for cache_name, candidate_type in (("_camera_sensors", "camera"), ("_lidar_sensors", "lidar")):
            candidate_cache = getattr(self, cache_name, None)
            if candidate_cache is not None and prim_path in candidate_cache:
                sensor = candidate_cache[prim_path]
                sensor_type = candidate_type
                cache = candidate_cache
                break

        annotators_before = sorted((getattr(sensor, "_annotators", None) or {}).keys()) if sensor is not None else []
        writers_before = sorted((getattr(sensor, "_writers", None) or {}).keys()) if sensor is not None else []
        hydra_texture = getattr(sensor, "_hydra_texture", None) if sensor is not None else None
        render_product_path = str(getattr(hydra_texture, "path", "")) or None
        if render_product_path is None and sensor is not None:
            candidate_path = getattr(sensor, "_render_product_path", None)
            render_product_path = str(candidate_path) if candidate_path else None

        report: Dict[str, Any] = {
            "prim_path": prim_path,
            "actual_prim_path": actual_prim_path,
            "sensor_type": sensor_type,
            "found": sensor is not None,
            "teardown_method": None,
            "annotators_before": annotators_before,
            "writers_before": writers_before,
            "render_product_path": render_product_path,
        }

        if sensor is not None:
            try:
                invalidate = getattr(sensor, "_invalidate_sensor", None)
                destroy = getattr(sensor, "destroy", None)
                if callable(invalidate):
                    report["teardown_method"] = "_invalidate_sensor"
                    invalidate()
                elif callable(destroy):
                    report["teardown_method"] = "destroy"
                    destroy()
                else:
                    report["teardown_method"] = "explicit_detach"
                    detach_writer = getattr(sensor, "detach_writer", None)
                    if callable(detach_writer):
                        for writer_name in writers_before:
                            detach_writer(writer_name)
                    detach_annotators = getattr(sensor, "detach_annotators", None)
                    if callable(detach_annotators) and annotators_before:
                        detach_annotators(annotators_before)
                    hydra_texture = getattr(sensor, "_hydra_texture", None)
                    texture_destroy = getattr(hydra_texture, "destroy", None)
                    if callable(texture_destroy):
                        texture_destroy()
                        sensor._hydra_texture = None
                annotators_after = sorted((getattr(sensor, "_annotators", None) or {}).keys())
                writers_after = sorted((getattr(sensor, "_writers", None) or {}).keys())
                texture_after = getattr(sensor, "_hydra_texture", None)
                if report["teardown_method"] in {"_invalidate_sensor", "explicit_detach"} and (
                    annotators_after or writers_after or texture_after is not None
                ):
                    raise RuntimeError("sensor runtime still owns annotators, writers, or a Hydra texture")
            except Exception as exc:
                report["error"] = str(exc)
                raise SensorLifecycleError(f"Failed to release sensor at {prim_path}: {exc}", report) from exc
            cache.pop(prim_path, None)
        else:
            annotators_after = []
            writers_after = []
            texture_after = None

        initialized = getattr(self, "_initialized_cameras", None)
        if initialized is not None:
            initialized.discard(prim_path)

        if evict_metadata and actual_paths is not None:
            actual_paths.pop(prim_path, None)
        config_metadata = getattr(self, "_lidar_config_metadata", None)
        if evict_metadata and config_metadata is not None:
            config_metadata.pop(prim_path, None)

        report.update(
            {
                "annotators_after": annotators_after,
                "writers_after": writers_after,
                "render_product_released": texture_after is None,
                "cache_evicted": all(
                    prim_path not in (getattr(self, cache_name, None) or {})
                    for cache_name in ("_camera_sensors", "_lidar_sensors")
                ),
                "metadata_evicted": evict_metadata
                and (
                    prim_path not in (getattr(self, "_lidar_actual_paths", None) or {})
                    and prim_path not in (getattr(self, "_lidar_config_metadata", None) or {})
                ),
            }
        )
        return report

    def release_all_sensors(self, *, evict_metadata: bool = True) -> List[Dict[str, Any]]:
        """Release every cached sensor — used when clearing the whole scene."""
        reports = []
        for cache_name in ("_camera_sensors", "_lidar_sensors"):
            cache = getattr(self, cache_name, None) or {}
            for prim_path in list(cache):
                reports.append(self.release_sensor(prim_path, evict_metadata=evict_metadata))
        return reports

    # ── Sensors ────────────────────────────────────────────

    @abstractmethod
    def create_camera(self, prim_path: str, resolution: Tuple[int, int] = (1280, 720), **kwargs) -> Any:
        """Create a camera sensor at prim_path."""
        ...

    @abstractmethod
    def capture_camera_image(self, prim_path: str) -> np.ndarray:
        """Capture an RGB image from a camera. Returns image data."""
        ...

    def capture_camera_output(self, prim_path: str, annotator: str) -> tuple[np.ndarray, Dict[str, Any]]:
        """Capture a typed camera annotator output and its auxiliary info."""
        raise NotImplementedError("Typed camera annotators require the Isaac Sim 6.x RTX CameraSensor adapter")

    def get_camera_calibration(self, prim_path: str) -> Dict[str, Any]:
        """Read intrinsic/extrinsic camera calibration and unit metadata."""
        raise NotImplementedError("Camera calibration requires the Isaac Sim 6.x RTX CameraSensor adapter")

    @abstractmethod
    def create_lidar(self, prim_path: str, config: Optional[str] = None, **kwargs) -> Any:
        """Create a lidar sensor at prim_path."""
        ...

    @abstractmethod
    def get_lidar_config(self, prim_path: str) -> Dict[str, Any]:
        """Read effective LiDAR configuration and authored schema attributes."""
        ...

    @abstractmethod
    def get_lidar_point_cloud(self, prim_path: str) -> np.ndarray:
        """Get point cloud data from a lidar sensor."""
        ...

    def get_lidar_point_cloud_frame(self, prim_path: str) -> Dict[str, Any]:
        """Get point fields plus sensor/frame metadata.

        Older adapters expose XYZ only. The default preserves that support while
        V6 overrides this method with GenericModelOutput auxiliary fields.
        """
        points = self.get_lidar_point_cloud(prim_path)
        return {
            "fields": {
                "points": {
                    "data": points,
                    "dtype": "float32",
                    "units": "meters",
                }
            },
            "coordinate_frame": "sensor",
            "unavailable_fields": [
                "intensity",
                "range",
                "azimuth",
                "elevation",
                "object_id",
                "semantic_id",
            ],
        }

    # ── Materials ──────────────────────────────────────────

    @abstractmethod
    def create_pbr_material(
        self,
        prim_path: str,
        color: Optional[Sequence[float]] = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
    ) -> Any:
        """Create an OmniPBR material."""
        ...

    @abstractmethod
    def create_physics_material(
        self,
        prim_path: str,
        static_friction: float = 0.5,
        dynamic_friction: float = 0.5,
        restitution: float = 0.0,
    ) -> Any:
        """Create a physics material with friction/restitution."""
        ...

    @abstractmethod
    def apply_material(self, material_path: str, target_prim_path: str) -> None:
        """Bind a material to a prim."""
        ...

    # ── Lighting ───────────────────────────────────────────

    @abstractmethod
    def create_light(
        self,
        light_type: str,
        prim_path: str,
        intensity: float = 1000.0,
        color: Optional[Sequence[float]] = None,
        **kwargs,
    ) -> Any:
        """Create a light prim (Distant, Dome, Sphere, Rect, Disk, Cylinder)."""
        ...

    @abstractmethod
    def modify_light(
        self, prim_path: str, intensity: Optional[float] = None, color: Optional[Sequence[float]] = None
    ) -> None:
        """Modify properties of an existing light."""
        ...

    @abstractmethod
    def clone_prim(self, source_path: str, target_path: str) -> None:
        """Copy a prim from source_path to target_path."""
        ...

    # ── Assets ─────────────────────────────────────────────

    @abstractmethod
    def import_urdf(self, urdf_path: str, prim_path: str = "/World/robot", **kwargs) -> Any:
        """Import a robot from a URDF file."""
        ...

    # ── Simulation ─────────────────────────────────────────

    @contextlib.contextmanager
    def _graphs_suspended(self):
        """Disable Action Graphs for the duration of a step, then restore them.

        Stepping runs the timeline for the requested frames, which fires
        OnPlaybackTick and evaluates every Action Graph. A ScriptNode controller
        therefore re-commands the robot on every stepped frame and silently
        overwrites whatever set_joint_positions just asked for — the caller sees
        its own targets replaced by the controller's with no error anywhere.

        The two debug modes are meant to stay separate: step on a frozen
        timeline for the MCP loop, play for an Action-Graph run. Suspending the
        graphs keeps that promise, and matches V6, whose SimulationManager.step
        pumps only the physics pipeline.

        Graphs the caller had already disabled are left alone, and everything is
        restored even if the step raises.
        """
        suspended = []
        try:
            import omni.graph.core as og

            graphs = og.get_all_graphs() if hasattr(og, "get_all_graphs") else []
            for graph in graphs:
                try:
                    if not graph.is_disabled():
                        graph.set_disabled(True)
                        suspended.append(graph)
                except Exception:
                    continue
        except Exception:
            pass  # No OmniGraph in this runtime — nothing to suspend.
        try:
            yield [g.get_path_to_graph() for g in suspended] if suspended else []
        finally:
            for graph in suspended:
                try:
                    graph.set_disabled(False)
                except Exception:
                    pass

    def _find_physics_scene(self, preferred_path: Optional[str] = None) -> Optional[str]:
        """Path of a PhysicsScene already on the stage, preferring `preferred_path`.

        Isaac Sim 6.0 ships a `/PhysicsScene` on a new stage. Adding a second one
        at `/World/PhysicsScene` — which create_physics_scene did unconditionally
        — leaves two scenes, and the omni.physics.tensors backend then refuses
        state reads: get_velocities fails with "Failed to get rigid body
        velocities from backend", which get_physics_state and step's observations
        swallow into a plausible-looking [0, 0, 0].

        Verified on 6.0.1: a body in free fall reported zero velocity with both
        scenes present, and -1.9840 m/s immediately after the duplicate was
        removed, with nothing else changed.
        """
        try:
            stage = self.get_stage()
            if stage is None:
                return None
            if preferred_path:
                prim = stage.GetPrimAtPath(preferred_path)
                if prim and prim.IsValid() and prim.GetTypeName() == "PhysicsScene":
                    return preferred_path
            for prim in stage.Traverse():
                if prim.GetTypeName() == "PhysicsScene":
                    return prim.GetPath().pathString
        except Exception:
            pass
        return None

    def _apply_gravity(self, scene_path: str, gravity: Sequence[float]) -> bool:
        """Write a gravity vector onto a PhysicsScene. Returns True if applied.

        USD stores gravity as a direction plus a magnitude, not as a vector, so a
        caller-supplied [x, y, z] has to be decomposed. Both adapters used to
        accept `gravity` and drop it: create_physics_scene only ran CreatePrim,
        leaving the scene at its defaults (direction (0,0,0), magnitude -inf,
        meaning "engine default"). set_physics_params reported "Physics
        parameters updated" while changing nothing — asking for Mars gravity
        [0, 0, -3.72] on 6.0.1 still produced a measured -4.7415 m/s after 30
        frames, i.e. Earth.

        A zero-length vector has no direction to derive, so it is treated as
        "straight down" with zero magnitude rather than producing NaNs.
        """
        from pxr import Gf, UsdPhysics

        prim = self.get_stage().GetPrimAtPath(scene_path)
        if not prim or not prim.IsValid():
            return False
        vector = Gf.Vec3f(float(gravity[0]), float(gravity[1]), float(gravity[2]))
        magnitude = float(vector.GetLength())
        direction = Gf.Vec3f(vector / magnitude) if magnitude > 0 else Gf.Vec3f(0.0, 0.0, -1.0)
        scene = UsdPhysics.Scene(prim)
        scene.CreateGravityDirectionAttr().Set(direction)
        scene.CreateGravityMagnitudeAttr().Set(magnitude)
        return True

    def _stage_has_physics_scene(self) -> bool:
        """True when the stage carries at least one PhysicsScene prim."""
        try:
            for prim in self.get_stage().Traverse():
                if prim.GetTypeName() == "PhysicsScene":
                    return True
        except Exception:
            return False
        return False

    def _resync_physics_scene_cache(self) -> None:
        """Rebuild SimulationManager's PhysxSceneAPI cache from the live stage.

        SimulationManager keys cached PhysxSceneAPI handles by prim path and
        maintains them with add/delete callbacks. Deleting a PhysicsScene does
        not reliably evict its entry (see the "TODO: match physics scene prim
        path" in isaacsim.core.simulation_manager), so after clear_scene the
        cache can map a path whose prim is valid again — because the scene was
        re-created — onto an API bound to the deleted prim. Reading through it
        then raises "Accessed schema on invalid prim", which breaks
        initialize_physics() and everything that depends on it.

        Re-applying the schema to the prims currently on the stage restores the
        cache. Best effort: the cache is private, so guard every access.
        """
        try:
            from isaacsim.core.simulation_manager import SimulationManager
            from pxr import PhysxSchema
        except Exception:
            return
        apis = getattr(SimulationManager, "_physics_scene_apis", None)
        if apis is None:
            return
        try:
            stage = self.get_stage()
            apis.clear()
            for prim in stage.Traverse():
                if prim.GetTypeName() == "PhysicsScene":
                    apis[str(prim.GetPath())] = PhysxSchema.PhysxSceneAPI.Apply(prim)
        except Exception:
            pass

    def _ensure_physics_world(self) -> None:
        """Ensure a World with initialised physics exists.

        Called by play() and create_action_graph() to guarantee that
        SingleArticulation.initialize() works inside ScriptNode scripts.

        The default implementation uses isaacsim.core.api.World (Isaac Sim 5.x).
        Override in version-specific adapters if the API differs.
        """
        try:
            from isaacsim.core.api import World
        except ImportError:
            return  # Non-v5 runtimes may not have isaacsim.core.api

        # Initialising physics before the stage has a PhysicsScene builds a
        # simulation view with no articulation data, and adding a scene later
        # does NOT rebuild it. Every subsequent SingleArticulation.initialize()
        # then fails with "'NoneType' object has no attribute 'link_names'", so
        # create_robot silently returns without joint_names / num_dof / warnings
        # and the process cannot recover — verified on 5.1, where even deleting
        # the scene and rebuilding World did not restore it.
        #
        # Any tool can warm physics (execute_script, step, play), so the damage
        # depends purely on call order. There is nothing meaningful to
        # initialise without a scene, so do nothing and let create_physics_scene
        # (or the caller) establish one first.
        if not self._stage_has_physics_scene():
            return

        def _prepare(world):
            """Build the World if absent and make sure physics is initialised."""
            if world is None:
                world = World(
                    physics_dt=1.0 / 60.0,
                    rendering_dt=1.0 / 60.0,
                    stage_units_in_meters=1.0,
                )
            if world.physics_sim_view is None:
                world.initialize_physics()
            return world

        try:
            _prepare(World.instance())
        except Exception:
            # The cached World outlives the prims it was built against, so after
            # clear_scene (or any prim deletion) it dereferences dead handles and
            # raises "Accessed schema on invalid prim". Note the raise can come
            # from merely reading physics_sim_view, not just from
            # initialize_physics(), so the whole preparation is guarded.
            #
            # Untreated this wedges every tool routed through here — play, step,
            # execute_script, reload_script, get_joint_config,
            # create_action_graph — until Kit is restarted. Drop the stale
            # singleton and rebuild against the live stage.
            self._resync_physics_scene_cache()
            try:
                World.clear_instance()
            except Exception:
                pass
            try:
                _prepare(None)
            except Exception as exc:
                # Still best effort: this helper only pre-warms physics. Raising
                # here would take down every tool that calls it, so report and
                # continue — whatever actually needs physics will fail with its
                # own specific error instead of a blanket wedge. The message
                # reaches kit's log, which get_isaac_logs surfaces.
                print(f"_ensure_physics_world: could not initialise physics ({exc}); continuing without it")

    @abstractmethod
    def play(self) -> None:
        """Start the simulation."""
        ...

    @abstractmethod
    def pause(self) -> None:
        """Pause the simulation."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the simulation."""
        ...

    @abstractmethod
    def step(
        self, num_steps: int = 1, observe_prims: Optional[List[str]] = None, observe_joints: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Step the simulation forward and optionally observe prim/joint states.

        Args:
            num_steps: Number of frames to step.
            observe_prims: Prim paths to snapshot after stepping (transform + velocity).
            observe_joints: Articulation paths to snapshot (joint positions).
        """
        ...

    @abstractmethod
    def get_simulation_state(self) -> Dict[str, Any]:
        """Return current timeline state, simulation time, physics dt, and step count."""
        ...

    @abstractmethod
    def execute_script(self, code: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """Execute arbitrary Python code in the Isaac Sim context.

        Args:
            code: Python code to execute.
            cwd: Optional working directory to add to sys.path before execution.
        """
        ...

    @abstractmethod
    def reload_script(self, file_path: str, module_name: Optional[str] = None) -> Dict[str, Any]:
        """Reload a Python script or module into the Isaac Sim runtime.

        Args:
            file_path: Path to the Python file.
            module_name: If provided, reload this module. Otherwise execute the file.
        """
        ...
