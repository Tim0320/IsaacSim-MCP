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

from .base import IsaacAdapterBase, SensorLifecycleState
from .v6_runtime import (
    AssetPolicyBridge,
    AssetRuntime,
    CapabilityRuntime,
    LightingPolicyBridge,
    LightingRuntime,
    MaterialPolicyBridge,
    MaterialRuntime,
    MotionRuntime,
    PhysicsPolicyBridge,
    PhysicsRuntime,
    RobotPolicyBridge,
    RobotRuntime,
    RuntimeContext,
    SceneRuntime,
    SensorPolicyBridge,
    SensorRuntime,
    SimulationPolicyBridge,
    SimulationRuntime,
)

if TYPE_CHECKING:
    from pxr import Usd


class IsaacAdapterV6(IsaacAdapterBase):
    """Isaac Sim 6 adapter with explicit per-backend capability guards."""

    def __init__(self) -> None:
        super().__init__()
        self._runtime_context = RuntimeContext.from_runtime()
        self._capability_runtime = CapabilityRuntime(self._runtime_context, self._backend_capability)
        self._scene_runtime = SceneRuntime(self._runtime_context)
        self._physics_runtime = PhysicsRuntime(
            self._runtime_context,
            self._scene_runtime,
            PhysicsPolicyBridge(self),
        )
        self._robot_runtime = RobotRuntime(
            self._scene_runtime,
            self._physics_runtime,
            RobotPolicyBridge(self),
        )
        self._motion_runtime = MotionRuntime(self._scene_runtime, self._robot_runtime)
        self._sensor_runtime = SensorRuntime(self._scene_runtime, SensorPolicyBridge(self))
        self._material_runtime = MaterialRuntime(self._scene_runtime, MaterialPolicyBridge(self))
        self._lighting_runtime = LightingRuntime(self._scene_runtime, LightingPolicyBridge(self))
        self._asset_runtime = AssetRuntime(AssetPolicyBridge(self))
        self._simulation_runtime = SimulationRuntime(self._runtime_context, SimulationPolicyBridge(self))
        # Preserve the existing attribute read by capability reporting.
        self._isaacsim_version = self._runtime_context.isaac_version
        # Cross-domain timeline coordination remains in the composition root.
        self._timeline_stop_subscription = None
        try:
            import carb.eventdispatcher
            import omni.timeline

            def _on_timeline_stop(_event):
                # Tensor-backed wrappers are bound to the SimulationView that
                # Timeline Stop destroys; the next Play must bind fresh ones.
                self._robot_runtime.clear_runtime_cache()
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
        return self._runtime_context.active_backend

    def get_backend_capability_matrix(self) -> Dict[str, Any]:
        """Return the audited Isaac Sim 6.0.1 PhysX/Newton matrix.

        PhysX evidence comes from the guarded Task 1.x, 2.x, and 3.1 live
        acceptance runs.  Newton remains fail-closed until the same feature is
        exercised under ``isaac-sim.newton``; implementation reuse is not
        treated as verification.
        """
        return self._capability_runtime.get_backend_capability_matrix()

    # ── Scene ──────────────────────────────────────────────

    def get_stage(self) -> "Usd.Stage":
        return self._scene_runtime.get_stage()

    def get_assets_root_path(self) -> str:
        return self._scene_runtime.get_assets_root_path()

    def discover_environments(self) -> Dict[str, Dict[str, str]]:
        return self._scene_runtime.discover_environments()

    def load_environment(self, env_path: str, prim_path: str = "/Environment") -> None:
        self._scene_runtime.load_environment(env_path, prim_path)

    # ── Prims ──────────────────────────────────────────────

    def create_prim(self, prim_path: str, prim_type: str = "Xform", **kwargs) -> "Usd.Prim":
        return self._scene_runtime.create_prim(prim_path, prim_type, **kwargs)

    def delete_prim(self, prim_path: str) -> bool:
        # A live sensor wrapper keeps its prim alive; see release_sensor.
        self.release_sensor(prim_path)
        return self._scene_runtime.delete_prim(prim_path)

    def add_reference_to_stage(self, usd_path: str, prim_path: str) -> "Usd.Prim":
        return self._scene_runtime.add_reference_to_stage(usd_path, prim_path)

    def set_prim_transform(
        self,
        prim_path: str,
        position: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
        scale: Optional[Sequence[float]] = None,
    ) -> None:
        self._scene_runtime.set_prim_transform(prim_path, position, rotation, scale)

    def get_prim_transform(self, prim_path: str) -> Dict[str, Any]:
        return self._scene_runtime.get_prim_transform(prim_path)

    def list_prims(self, root_path: str = "/", prim_type: Optional[str] = None) -> List[Dict[str, str]]:
        return self._scene_runtime.list_prims(root_path, prim_type)

    def get_prim_info(self, prim_path: str) -> Dict[str, Any]:
        return self._scene_runtime.get_prim_info(prim_path)

    def get_prim_actual_size(self, prim_path: str) -> Tuple[List[float], Tuple[List[float], List[float]]]:
        return self._scene_runtime.get_prim_actual_size(prim_path)

    # ── Robots ─────────────────────────────────────────────

    def create_xform_prim(self, prim_path: str) -> Any:
        return self._robot_runtime.create_xform_prim(prim_path)

    def create_articulation(self, prim_path: str, name: str) -> Any:
        return self._robot_runtime.create_articulation(prim_path, name)

    @property
    def _articulations(self) -> Dict[str, Any]:
        """Compatibility view; RobotRuntime owns the articulation cache."""
        return self._robot_runtime._articulations

    @_articulations.setter
    def _articulations(self, value: Dict[str, Any]) -> None:
        self._robot_runtime._articulations = value

    def _new_articulation(self, prim_path: str) -> Any:
        return self._robot_runtime._new_articulation(prim_path)

    def _runtime_articulation(self, prim_path: str) -> Any:
        return self._robot_runtime._runtime_articulation(prim_path)

    def discover_robots(self) -> Dict[str, Dict[str, str]]:
        return self._robot_runtime.discover_robots()

    def get_robot_joint_info(self, prim_path: str) -> Dict[str, Any]:
        return self._robot_runtime.get_robot_joint_info(prim_path)

    def set_joint_positions(
        self,
        prim_path: str,
        positions: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        self._robot_runtime.set_joint_positions(prim_path, positions, joint_indices)

    def _set_joint_drive_targets(
        self,
        prim_path: str,
        positions: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        self._robot_runtime._set_joint_drive_targets(prim_path, positions, joint_indices)

    def _get_joint_names(self, prim_path: str) -> List[str]:
        return self._robot_runtime._get_joint_names(prim_path)

    def get_joint_positions(self, prim_path: str) -> List[float]:
        return self._robot_runtime.get_joint_positions(prim_path)

    @staticmethod
    def _flatten_joint_values(values: Any) -> List[float]:
        return RobotRuntime._flatten_joint_values(values)

    @staticmethod
    def _joint_type_name(value: Any) -> str:
        return RobotRuntime._joint_type_name(value)

    def get_joint_state(self, prim_path: str) -> Dict[str, Any]:
        return self._robot_runtime.get_joint_state(prim_path)

    def set_joint_command(
        self,
        prim_path: str,
        mode: str,
        values: Sequence[float],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        self._robot_runtime.set_joint_command(prim_path, mode, values, joint_indices)

    # ── Motion generation and bounded job lifecycle ─────────────────────

    @property
    def _motion_trajectories(self) -> Dict[str, Dict[str, Any]]:
        """Compatibility view; MotionRuntime owns trajectory state."""
        return self._motion_runtime._motion_trajectories

    @_motion_trajectories.setter
    def _motion_trajectories(self, value: Dict[str, Dict[str, Any]]) -> None:
        self._motion_runtime._motion_trajectories = value

    @property
    def _motion_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Compatibility view; MotionRuntime owns job state."""
        return self._motion_runtime._motion_jobs

    @_motion_jobs.setter
    def _motion_jobs(self, value: Dict[str, Dict[str, Any]]) -> None:
        self._motion_runtime._motion_jobs = value

    @property
    def _motion_update_subscription(self) -> Any:
        """Compatibility view; MotionRuntime owns the Kit subscription."""
        return self._motion_runtime._motion_update_subscription

    @_motion_update_subscription.setter
    def _motion_update_subscription(self, value: Any) -> None:
        self._motion_runtime._motion_update_subscription = value

    @staticmethod
    def _motion_config(robot_model: str) -> Dict[str, str]:
        return MotionRuntime._motion_config(robot_model)

    def _motion_base_pose(self, prim_path: str) -> Tuple[np.ndarray, np.ndarray]:
        return self._motion_runtime._motion_base_pose(prim_path)

    @staticmethod
    def _orientation_error(a: np.ndarray, b: np.ndarray) -> float:
        return MotionRuntime._orientation_error(a, b)

    def compute_ik(
        self,
        prim_path: str,
        target_position: Sequence[float],
        end_effector_frame: str = "right_gripper",
        target_orientation: Optional[Sequence[float]] = None,
        seed_joint_positions: Optional[Sequence[float]] = None,
        random_seed: int = 123456,
        position_tolerance: float = 0.001,
        orientation_tolerance: float = 0.01,
        max_iterations: int = 100,
        timeout_ms: int = 2000,
        robot_model: str = "Franka",
    ) -> Dict[str, Any]:
        return self._motion_runtime.compute_ik(
            prim_path,
            target_position,
            end_effector_frame,
            target_orientation,
            seed_joint_positions,
            random_seed,
            position_tolerance,
            orientation_tolerance,
            max_iterations,
            timeout_ms,
            robot_model,
        )

    def plan_joint_trajectory(
        self,
        prim_path: str,
        goal_joint_positions: Sequence[float],
        start_joint_positions: Optional[Sequence[float]] = None,
        planner: str = "rrt",
        random_seed: int = 123456,
        max_iterations: int = 5000,
        timeout_ms: int = 5000,
        robot_model: str = "Franka",
    ) -> Dict[str, Any]:
        return self._motion_runtime.plan_joint_trajectory(
            prim_path,
            goal_joint_positions,
            start_joint_positions,
            planner,
            random_seed,
            max_iterations,
            timeout_ms,
            robot_model,
        )

    def _ensure_motion_subscription(self) -> None:
        self._motion_runtime._ensure_motion_subscription()

    def execute_trajectory(self, trajectory_id: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        return self._motion_runtime.execute_trajectory(trajectory_id, timeout_ms)

    def _on_motion_update(self, event: Any) -> None:
        self._motion_runtime._on_motion_update(event)

    def cancel_motion(self, job_id: str) -> Dict[str, Any]:
        return self._motion_runtime.cancel_motion(job_id)

    @staticmethod
    def _motion_job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
        return MotionRuntime._motion_job_snapshot(job)

    def get_motion_status(self, job_id: str) -> Dict[str, Any]:
        return self._motion_runtime.get_motion_status(job_id)

    def shutdown_motion(self) -> None:
        self._motion_runtime.shutdown_motion()

    def compute_holonomic_wheel_velocities(
        self,
        prim_path: str,
        com_prim_path: str,
        command: Sequence[float],
        joint_names: Sequence[str],
    ) -> List[float]:
        return self._robot_runtime.compute_holonomic_wheel_velocities(
            prim_path,
            com_prim_path,
            command,
            joint_names,
        )

    @staticmethod
    def _drive_units(joint_type: str) -> Dict[str, str]:
        return RobotRuntime._drive_units(joint_type)

    def _drive_config_articulation(self, prim_path: str) -> Any:
        return self._robot_runtime._drive_config_articulation(prim_path)

    def get_joint_drive_config(self, prim_path: str) -> Dict[str, Any]:
        return self._robot_runtime.get_joint_drive_config(prim_path)

    def set_joint_drive_config(
        self,
        prim_path: str,
        config: Dict[str, Any],
        joint_indices: Optional[List[int]] = None,
    ) -> None:
        self._robot_runtime.set_joint_drive_config(prim_path, config, joint_indices)

    def get_joint_config(self, prim_path: str) -> Dict[str, Any]:
        return self._robot_runtime.get_joint_config(prim_path)

    # ── Physics ────────────────────────────────────────────

    def _ensure_physics_world(self) -> None:
        self._physics_runtime._ensure_physics_world()

    def _arm_reset_point(self) -> None:
        self._physics_runtime._arm_reset_point()

    def create_world(self, **kwargs) -> Any:
        return self._physics_runtime.create_world(**kwargs)

    def create_simulation_context(self, **kwargs) -> Any:
        return self._physics_runtime.create_simulation_context(**kwargs)

    def create_physics_scene(self, gravity: Optional[Sequence[float]] = None, scene_name: str = "PhysicsScene") -> str:
        return self._physics_runtime.create_physics_scene(gravity, scene_name)

    def configure_physics(
        self,
        gravity: Optional[Sequence[float]] = None,
        time_step: Optional[float] = None,
        gpu_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self._physics_runtime.configure_physics(gravity, time_step, gpu_enabled)

    def configure_physics_body(
        self,
        prim_path: str,
        body_type: str,
        collider_enabled: bool,
        approximation: Optional[str] = None,
        mass_kg: Optional[float] = None,
        density_kg_m3: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self._physics_runtime.configure_physics_body(
            prim_path, body_type, collider_enabled, approximation, mass_kg, density_kg_m3
        )

    def get_physics_body(self, prim_path: str) -> Dict[str, Any]:
        return self._physics_runtime.get_physics_body(prim_path)

    def create_collision_group(
        self,
        group_path: str,
        collider_paths: Sequence[str],
        filtered_group_paths: Sequence[str],
        invert_filtered_groups: bool = False,
        merge_group_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._physics_runtime.create_collision_group(
            group_path,
            collider_paths,
            filtered_group_paths,
            invert_filtered_groups,
            merge_group_name,
        )

    def get_collision_group(self, group_path: str) -> Dict[str, Any]:
        return self._physics_runtime.get_collision_group(group_path)

    def create_physics_joint(
        self,
        joint_path: str,
        joint_type: str,
        body1: str,
        body0: Optional[str] = None,
        axis: Optional[str] = None,
        lower_limit: Optional[float] = None,
        upper_limit: Optional[float] = None,
        local_position0: Optional[Sequence[float]] = None,
        local_rotation0: Optional[Sequence[float]] = None,
        local_position1: Optional[Sequence[float]] = None,
        local_rotation1: Optional[Sequence[float]] = None,
        collision_enabled: bool = False,
    ) -> Dict[str, Any]:
        return self._physics_runtime.create_physics_joint(
            joint_path,
            joint_type,
            body1,
            body0,
            axis,
            lower_limit,
            upper_limit,
            local_position0,
            local_rotation0,
            local_position1,
            local_rotation1,
            collision_enabled,
        )

    def get_physics_joint(self, joint_path: str) -> Dict[str, Any]:
        return self._physics_runtime.get_physics_joint(joint_path)

    def get_physics_state(self, prim_path: str) -> Dict[str, Any]:
        return self._physics_runtime.get_physics_state(prim_path)

    # ── Sensors ────────────────────────────────────────────

    def _sensor_lifecycle_state(self) -> SensorLifecycleState:
        return self._sensor_runtime.lifecycle_state

    @property
    def _camera_sensors(self) -> Dict[str, Any]:
        """Compatibility view for handlers; SensorRuntime remains the owner."""
        return self._sensor_runtime.lifecycle_state.camera_sensors

    @property
    def _lidar_sensors(self) -> Dict[str, Any]:
        """Compatibility view for handlers; SensorRuntime remains the owner."""
        return self._sensor_runtime.lifecycle_state.lidar_sensors

    @property
    def _lidar_actual_paths(self) -> Dict[str, str]:
        """Compatibility view for handlers; SensorRuntime remains the owner."""
        return self._sensor_runtime.lifecycle_state.lidar_actual_paths

    @property
    def _lidar_config_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Compatibility view for handlers; SensorRuntime remains the owner."""
        return self._sensor_runtime.lifecycle_state.lidar_config_metadata

    def _request_render_frame(self) -> bool:
        return self._sensor_runtime._request_render_frame()

    def _apply_sensor_schema(self, prim_path: str) -> None:
        self._sensor_runtime._apply_sensor_schema(prim_path)

    def create_camera(self, prim_path: str, resolution: Tuple[int, int] = (1280, 720), **kwargs) -> Any:
        return self._sensor_runtime.create_camera(prim_path, resolution, **kwargs)

    def capture_camera_image(self, prim_path: str) -> np.ndarray:
        return self._sensor_runtime.capture_camera_image(prim_path)

    def capture_camera_output(self, prim_path: str, annotator: str) -> tuple[np.ndarray, Dict[str, Any]]:
        return self._sensor_runtime.capture_camera_output(prim_path, annotator)

    def get_camera_calibration(self, prim_path: str) -> Dict[str, Any]:
        return self._sensor_runtime.get_camera_calibration(prim_path)

    def create_lidar(self, prim_path: str, config: Optional[str] = None, **kwargs) -> Any:
        return self._sensor_runtime.create_lidar(prim_path, config, **kwargs)

    def get_lidar_config(self, prim_path: str) -> Dict[str, Any]:
        return self._sensor_runtime.get_lidar_config(prim_path)

    def get_lidar_point_cloud(self, prim_path: str) -> np.ndarray:
        return self._sensor_runtime.get_lidar_point_cloud(prim_path)

    def get_lidar_point_cloud_frame(self, prim_path: str) -> Dict[str, Any]:
        return self._sensor_runtime.get_lidar_point_cloud_frame(prim_path)

    @staticmethod
    def _empty_lidar_frame() -> Dict[str, Any]:
        return SensorRuntime._empty_lidar_frame()

    # ── Materials ──────────────────────────────────────────

    def create_pbr_material(
        self,
        prim_path: str,
        color: Optional[Sequence[float]] = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
    ) -> Any:
        return self._material_runtime.create_pbr_material(prim_path, color, roughness, metallic)

    def create_physics_material(
        self,
        prim_path: str,
        static_friction: float = 0.5,
        dynamic_friction: float = 0.5,
        restitution: float = 0.0,
    ) -> Any:
        return self._material_runtime.create_physics_material(prim_path, static_friction, dynamic_friction, restitution)

    def apply_material(
        self, material_path: str, target_prim_path: str, material_purpose: str = "auto"
    ) -> Dict[str, Any]:
        return self._material_runtime.apply_material(material_path, target_prim_path, material_purpose)

    # ── Lighting ───────────────────────────────────────────

    def create_light(
        self,
        light_type: str,
        prim_path: str,
        intensity: float = 1000.0,
        color: Optional[Sequence[float]] = None,
        **kwargs,
    ) -> Any:
        return self._lighting_runtime.create_light(light_type, prim_path, intensity, color, **kwargs)

    def modify_light(
        self,
        prim_path: str,
        intensity: Optional[float] = None,
        color: Optional[Sequence[float]] = None,
    ) -> None:
        return self._lighting_runtime.modify_light(prim_path, intensity, color)

    # ── Assets ─────────────────────────────────────────────

    def clone_prim(self, source_path: str, target_path: str) -> None:
        return self._asset_runtime.clone_prim(source_path, target_path)

    def import_urdf(self, urdf_path: str, prim_path: str = "/World/robot", **kwargs) -> Any:
        return self._asset_runtime.import_urdf(urdf_path, prim_path, **kwargs)

    # ── Simulation ─────────────────────────────────────────

    @property
    def _exec_namespaces(self) -> Dict[str, dict]:
        return self._simulation_runtime._exec_namespaces

    @_exec_namespaces.setter
    def _exec_namespaces(self, value: Dict[str, dict]) -> None:
        self._simulation_runtime._exec_namespaces = value

    def play(self) -> None:
        return self._simulation_runtime.play()

    def pause(self) -> None:
        return self._simulation_runtime.pause()

    def stop(self) -> None:
        return self._simulation_runtime.stop()

    def step(
        self,
        num_steps: int = 1,
        observe_prims: Optional[List[str]] = None,
        observe_joints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self._simulation_runtime.step(num_steps, observe_prims, observe_joints)

    def get_simulation_state(self) -> Dict[str, Any]:
        return self._simulation_runtime.get_simulation_state()

    def execute_script(
        self,
        code: str,
        cwd: Optional[str] = None,
        timeout_s: float = 30.0,
        max_output_bytes: int = 65536,
    ) -> Dict[str, Any]:
        return self._simulation_runtime.execute_script(code, cwd, timeout_s, max_output_bytes)

    def reload_script(
        self,
        file_path: str,
        module_name: Optional[str] = None,
        timeout_s: float = 30.0,
        max_output_bytes: int = 65536,
    ) -> Dict[str, Any]:
        return self._simulation_runtime.reload_script(file_path, module_name, timeout_s, max_output_bytes)
