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

import math
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .base import IsaacAdapterBase, SensorLifecycleState
from .v6_runtime import (
    CapabilityRuntime,
    PhysicsPolicyBridge,
    PhysicsRuntime,
    RobotPolicyBridge,
    RobotRuntime,
    RuntimeContext,
    SceneRuntime,
    SensorPolicyBridge,
    SensorRuntime,
)

if TYPE_CHECKING:
    from pxr import Usd


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
        self._sensor_runtime = SensorRuntime(self._scene_runtime, SensorPolicyBridge(self))
        # Preserve the existing attribute read by capability reporting.
        self._isaacsim_version = self._runtime_context.isaac_version
        # Motion state remains facade-owned until the independent D.7 slice.
        self._motion_trajectories: Dict[str, Dict[str, Any]] = {}
        self._motion_jobs: Dict[str, Dict[str, Any]] = {}
        self._motion_update_subscription = None
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

    @staticmethod
    def _motion_config(robot_model: str) -> Dict[str, str]:
        from isaacsim.robot_motion.motion_generation import interface_config_loader

        config = interface_config_loader.load_supported_lula_kinematics_solver_config(robot_model)
        if not config:
            raise ValueError(f"No Lula kinematics configuration for robot_model={robot_model!r}")
        return config

    def _motion_base_pose(self, prim_path: str) -> Tuple[np.ndarray, np.ndarray]:
        from pxr import UsdGeom

        prim = self.get_stage().GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        matrix = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
        position = np.asarray(matrix.ExtractTranslation(), dtype=np.float64)
        quat = matrix.ExtractRotationQuat()
        imag = quat.GetImaginary()
        orientation = np.asarray([quat.GetReal(), imag[0], imag[1], imag[2]], dtype=np.float64)
        return position, orientation

    @staticmethod
    def _orientation_error(a: np.ndarray, b: np.ndarray) -> float:
        a = a / np.linalg.norm(a)
        b = b / np.linalg.norm(b)
        return float(2.0 * math.acos(min(1.0, abs(float(np.dot(a, b))))))

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
        from isaacsim.robot_motion.motion_generation import LulaKinematicsSolver

        started = time.perf_counter()
        solver = LulaKinematicsSolver(**self._motion_config(robot_model))
        solver.sampling_seed = int(random_seed)
        solver.max_num_descents = int(max_iterations)
        base_position, base_orientation = self._motion_base_pose(prim_path)
        solver.set_robot_base_pose(base_position, base_orientation)
        joint_names = list(solver.get_joint_names())
        warm_start = None
        if seed_joint_positions is not None:
            if len(seed_joint_positions) != len(joint_names):
                raise ValueError(f"seed_joint_positions requires {len(joint_names)} active-joint values")
            warm_start = np.asarray(seed_joint_positions, dtype=np.float64)
        else:
            state = self.get_joint_state(prim_path)
            by_name = dict(zip(state["joint_names"], state["positions"]))
            warm_start = np.asarray([by_name[name] for name in joint_names], dtype=np.float64)
        orientation = None if target_orientation is None else np.asarray(target_orientation, dtype=np.float64)
        joints, success = solver.compute_inverse_kinematics(
            end_effector_frame,
            np.asarray(target_position, dtype=np.float64),
            orientation,
            warm_start=warm_start,
            position_tolerance=float(position_tolerance),
            orientation_tolerance=float(orientation_tolerance),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        achieved_position, achieved_rotation = solver.compute_forward_kinematics(end_effector_frame, joints)
        target = np.asarray(target_position, dtype=np.float64)
        position_error = float(np.linalg.norm(achieved_position - target))
        result: Dict[str, Any] = {
            "status": "success"
            if success and elapsed_ms <= timeout_ms
            else ("timeout" if elapsed_ms > timeout_ms else "error"),
            "code": "IK_SOLVED"
            if success and elapsed_ms <= timeout_ms
            else ("IK_TIMEOUT" if elapsed_ms > timeout_ms else "IK_NO_SOLUTION"),
            "message": "Inverse kinematics solved" if success else "Inverse kinematics did not converge",
            "prim_path": prim_path,
            "robot_model": robot_model,
            "end_effector_frame": end_effector_frame,
            "joint_names": joint_names,
            "joint_positions": np.asarray(joints).tolist(),
            "success": bool(success and elapsed_ms <= timeout_ms),
            "position_error": position_error,
            "position_error_units": "meters",
            "random_seed": int(random_seed),
            "elapsed_ms": round(elapsed_ms, 3),
            "collision_check": {
                "checked": False,
                "reason": "LulaKinematicsSolver does not support collision avoidance",
            },
            "applied": False,
        }
        if orientation is not None:
            from isaacsim.core.utils.numpy.rotations import rot_matrices_to_quats

            achieved_orientation = np.asarray(rot_matrices_to_quats(achieved_rotation), dtype=np.float64)
            result["orientation_error"] = self._orientation_error(achieved_orientation, orientation)
            result["orientation_error_units"] = "radians"
        return result

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
        from isaacsim.robot_motion.motion_generation import LulaCSpaceTrajectoryGenerator

        started = time.perf_counter()
        config = self._motion_config(robot_model)
        generator = LulaCSpaceTrajectoryGenerator(**config)
        active_names = list(generator.get_active_joints())
        if len(goal_joint_positions) != len(active_names):
            raise ValueError(f"goal_joint_positions requires {len(active_names)} active-joint values")
        state = self.get_joint_state(prim_path)
        by_name = dict(zip(state["joint_names"], state["positions"]))
        missing = [name for name in active_names if name not in by_name]
        if missing:
            raise ValueError(f"Robot articulation is missing Lula joints: {missing}")
        if start_joint_positions is None:
            start_positions = np.asarray([by_name[name] for name in active_names], dtype=np.float64)
            start_source = "measured_joint_state"
        else:
            if len(start_joint_positions) != len(active_names):
                raise ValueError(f"start_joint_positions requires {len(active_names)} active-joint values")
            start_positions = np.asarray(start_joint_positions, dtype=np.float64)
            start_source = "explicit_request"
        goal_positions = np.asarray(goal_joint_positions, dtype=np.float64)
        collision_check: Dict[str, Any]
        if planner == "rrt":
            from isaacsim.robot_motion.motion_generation import interface_config_loader
            from isaacsim.robot_motion.motion_generation.lula.path_planners import RRT

            planner_config = interface_config_loader.load_supported_path_planner_config(robot_model, "RRT")
            if not planner_config:
                raise ValueError(f"No Lula RRT configuration for robot_model={robot_model!r}")
            path_planner = RRT(**planner_config)
            base_position, base_orientation = self._motion_base_pose(prim_path)
            path_planner.set_robot_base_pose(base_position, base_orientation)
            path_planner.set_random_seed(int(random_seed))
            path_planner.set_max_iterations(int(max_iterations))
            path_planner.set_cspace_target(goal_positions)
            path_planner.update_world()
            watched = np.asarray([by_name[name] for name in path_planner.get_watched_joints()], dtype=np.float64)
            waypoints = path_planner.compute_path(start_positions, watched)
            if waypoints is None or len(waypoints) < 2:
                return {
                    "status": "error",
                    "code": "NO_COLLISION_FREE_PATH",
                    "message": "Lula RRT did not find a path within max_iterations",
                    "collision_check": {
                        "checked": True,
                        "path_valid": False,
                        "scope": "Lula robot model and registered world view",
                        "registered_environment_obstacle_count": 0,
                        "scene_obstacles_included": False,
                    },
                    "random_seed": int(random_seed),
                    "max_iterations": int(max_iterations),
                    "applied": False,
                }
            collision_check = {
                "checked": True,
                "path_valid": True,
                "scope": "Lula robot model and registered world view",
                "registered_environment_obstacle_count": 0,
                "scene_obstacles_included": False,
                "limitations": "Task 2.3 does not yet register USD scene obstacles in the Lula world view",
            }
        else:
            waypoints = np.stack([start_positions, goal_positions])
            collision_check = {
                "checked": False,
                "path_valid": None,
                "reason": "C-space spline generation does not perform collision checking",
            }
        trajectory = generator.compute_c_space_trajectory(np.asarray(waypoints, dtype=np.float64))
        if trajectory is None:
            raise RuntimeError("Lula could not generate a time-parameterized trajectory")
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms > timeout_ms:
            raise TimeoutError(f"Planning exceeded timeout_ms ({elapsed_ms:.3f} > {timeout_ms})")
        trajectory_id = f"traj-{uuid.uuid4()}"
        self._motion_trajectories[trajectory_id] = {
            "id": trajectory_id,
            "prim_path": prim_path,
            "joint_names": active_names,
            "joint_indices": [state["joint_names"].index(name) for name in active_names],
            "trajectory": trajectory,
            "duration": float(trajectory.end_time - trajectory.start_time),
            "created_at": time.time(),
            "collision_check": collision_check,
            "random_seed": int(random_seed),
        }
        return {
            "status": "success",
            "code": "TRAJECTORY_PLANNED",
            "message": "Trajectory planned; call execute_trajectory to start a non-blocking job",
            "trajectory_id": trajectory_id,
            "prim_path": prim_path,
            "joint_names": active_names,
            "waypoint_count": int(len(waypoints)),
            "duration_seconds": self._motion_trajectories[trajectory_id]["duration"],
            "planner": planner,
            "start_source": start_source,
            "collision_check": collision_check,
            "random_seed": int(random_seed),
            "max_iterations": int(max_iterations),
            "elapsed_ms": round(elapsed_ms, 3),
            "applied": False,
        }

    def _ensure_motion_subscription(self) -> None:
        if self._motion_update_subscription is not None:
            return
        import omni.kit.app

        self._motion_update_subscription = (
            omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(self._on_motion_update)
        )

    def execute_trajectory(self, trajectory_id: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        trajectory = self._motion_trajectories.get(trajectory_id)
        if trajectory is None:
            raise ValueError(f"Unknown trajectory_id: {trajectory_id}")
        for job in self._motion_jobs.values():
            if job["prim_path"] == trajectory["prim_path"] and job["state"] in {"running", "paused"}:
                raise ValueError(f"Robot already has active motion job {job['id']}")
        job_id = f"motion-{uuid.uuid4()}"
        now = time.perf_counter()
        self._motion_jobs[job_id] = {
            "id": job_id,
            "trajectory_id": trajectory_id,
            "prim_path": trajectory["prim_path"],
            "state": "queued",
            "progress": 0.0,
            "elapsed": 0.0,
            "last_update": now,
            "deadline": now + timeout_ms / 1000.0,
            "timeout_ms": int(timeout_ms),
            "error": None,
        }
        self._ensure_motion_subscription()
        return {
            "status": "success",
            "code": "MOTION_JOB_STARTED",
            "message": "Motion job queued and returned without blocking",
            "job_id": job_id,
            "trajectory_id": trajectory_id,
            "state": "queued",
            "non_blocking": True,
            "applied": False,
        }

    def _on_motion_update(self, _event: Any) -> None:
        import omni.timeline

        now = time.perf_counter()
        playing = bool(omni.timeline.get_timeline_interface().is_playing())
        for job in list(self._motion_jobs.values()):
            if job["state"] not in {"queued", "running", "paused"}:
                continue
            if now >= job["deadline"]:
                job.update(state="timeout", error="Execution deadline exceeded", last_update=now)
                continue
            if not playing:
                job.update(state="paused", last_update=now)
                continue
            trajectory = self._motion_trajectories.get(job["trajectory_id"])
            if trajectory is None:
                job.update(state="failed", error="Trajectory was evicted", last_update=now)
                continue
            dt = max(0.0, min(now - job["last_update"], 0.1))
            job["elapsed"] += dt
            job["last_update"] = now
            job["state"] = "running"
            duration = max(float(trajectory["duration"]), 1e-9)
            sample_time = min(trajectory["trajectory"].start_time + job["elapsed"], trajectory["trajectory"].end_time)
            try:
                positions, _velocities = trajectory["trajectory"].get_joint_targets(sample_time)
                self.set_joint_command(
                    trajectory["prim_path"], "position", np.asarray(positions).tolist(), trajectory["joint_indices"]
                )
                job["progress"] = min(1.0, job["elapsed"] / duration)
                if job["progress"] >= 1.0:
                    job["state"] = "completed"
            except Exception as exc:
                job.update(state="failed", error=str(exc))

    def cancel_motion(self, job_id: str) -> Dict[str, Any]:
        job = self._motion_jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job["state"] in {"completed", "cancelled", "failed", "timeout"}:
            return {
                "status": "success",
                "code": "MOTION_ALREADY_TERMINAL",
                "message": "Motion job was already terminal",
                **self._motion_job_snapshot(job),
                "applied": False,
            }
        job.update(state="cancelled", last_update=time.perf_counter())
        return {
            "status": "cancelled",
            "code": "MOTION_CANCELLED",
            "message": "Motion job cancelled; no further targets will be sent",
            **self._motion_job_snapshot(job),
            "applied": True,
        }

    @staticmethod
    def _motion_job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": job["id"],
            "trajectory_id": job["trajectory_id"],
            "prim_path": job["prim_path"],
            "state": job["state"],
            "progress": round(float(job["progress"]), 6),
            "elapsed_seconds": round(float(job["elapsed"]), 6),
            "timeout_ms": job["timeout_ms"],
            "error": job["error"],
            "terminal": job["state"] in {"completed", "cancelled", "failed", "timeout"},
        }

    def get_motion_status(self, job_id: str) -> Dict[str, Any]:
        job = self._motion_jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        return {
            "status": "success",
            "code": "MOTION_STATUS",
            "message": "Motion job status",
            **self._motion_job_snapshot(job),
        }

    def shutdown_motion(self) -> None:
        for job in self._motion_jobs.values():
            if job["state"] in {"queued", "running", "paused"}:
                job["state"] = "cancelled"
        self._motion_update_subscription = None
        self._motion_trajectories.clear()

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
            readback = self.get_material(prim_path)
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
            readback = self.get_material_binding(target_prim_path, material_purpose)
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

    def execute_script(
        self,
        code: str,
        cwd: Optional[str] = None,
        timeout_s: float = 30.0,
        max_output_bytes: int = 65536,
    ) -> Dict[str, Any]:
        import sys
        import traceback

        import carb
        import omni
        from pxr import Gf, Sdf, Usd, UsdGeom

        from ..execution_guard import (
            BoundedTextBuffer,
            ScriptExecutionTimeout,
            ScriptOutputLimitExceeded,
            cooperative_deadline,
        )

        if cwd and cwd not in sys.path:
            sys.path.insert(0, cwd)

        local_ns = {"omni": omni, "carb": carb, "Usd": Usd, "UsdGeom": UsdGeom, "Sdf": Sdf, "Gf": Gf}

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = captured_out = BoundedTextBuffer(max_output_bytes)
        sys.stderr = captured_err = BoundedTextBuffer(max_output_bytes)
        try:
            with cooperative_deadline(timeout_s):
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
        except (ScriptExecutionTimeout, ScriptOutputLimitExceeded) as e:
            out = captured_out.getvalue()
            return {
                "status": "timeout" if isinstance(e, ScriptExecutionTimeout) else "error",
                "code": "SCRIPT_TIMEOUT" if isinstance(e, ScriptExecutionTimeout) else "SCRIPT_OUTPUT_LIMIT_EXCEEDED",
                "message": str(e),
                "traceback": traceback.format_exc(),
                "stdout": out,
                "stderr": captured_err.getvalue(),
                "applied": None,
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

    def reload_script(
        self,
        file_path: str,
        module_name: Optional[str] = None,
        timeout_s: float = 30.0,
        max_output_bytes: int = 65536,
    ) -> Dict[str, Any]:
        import importlib
        import os
        import sys
        import traceback

        from ..execution_guard import (
            BoundedTextBuffer,
            ScriptExecutionTimeout,
            ScriptOutputLimitExceeded,
            cooperative_deadline,
        )

        parent_dir = os.path.dirname(os.path.abspath(file_path))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)

        abs_path = os.path.abspath(file_path)

        # ScriptNode-aware reload: if any Action-Graph ScriptNode references this
        # file via inputs:scriptPath, force it to recompile (the standalone
        # re-exec below would not touch the running graph node).
        with cooperative_deadline(timeout_s):
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
        sys.stdout = captured_out = BoundedTextBuffer(max_output_bytes)
        sys.stderr = captured_err = BoundedTextBuffer(max_output_bytes)
        try:
            with cooperative_deadline(timeout_s):
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
        except (ScriptExecutionTimeout, ScriptOutputLimitExceeded) as e:
            return {
                "status": "timeout" if isinstance(e, ScriptExecutionTimeout) else "error",
                "code": "SCRIPT_TIMEOUT" if isinstance(e, ScriptExecutionTimeout) else "SCRIPT_OUTPUT_LIMIT_EXCEEDED",
                "message": str(e),
                "traceback": traceback.format_exc(),
                "stdout": captured_out.getvalue(),
                "stderr": captured_err.getvalue(),
                "applied": None,
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
