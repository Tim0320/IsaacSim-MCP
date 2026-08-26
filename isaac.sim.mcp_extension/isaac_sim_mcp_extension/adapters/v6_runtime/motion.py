# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Motion planning, trajectory storage, and non-blocking execution runtime."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from .robots import RobotRuntime
from .scene import SceneRuntime


class MotionRuntime:
    """Own IK/planning state and motion-job lifecycle for the V6 facade."""

    def __init__(self, scene: SceneRuntime, robots: RobotRuntime) -> None:
        self._scene = scene
        self._robots = robots
        self._motion_trajectories: Dict[str, Dict[str, Any]] = {}
        self._motion_jobs: Dict[str, Dict[str, Any]] = {}
        self._motion_update_subscription = None

    def get_stage(self):
        return self._scene.get_stage()

    def get_joint_state(self, prim_path: str) -> Dict[str, Any]:
        return self._robots.get_joint_state(prim_path)

    def set_joint_command(
        self,
        prim_path: str,
        mode: str,
        values: Sequence[float],
        joint_indices: Optional[list[int]] = None,
    ) -> None:
        self._robots.set_joint_command(prim_path, mode, values, joint_indices)

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
