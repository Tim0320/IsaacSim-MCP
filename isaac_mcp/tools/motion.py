"""Named MCP tools for bounded robot motion generation and execution."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    def send(command: str, params: dict) -> str:
        return json.dumps(get_connection().send_command(command, params), indent=2)

    @mcp.tool("compute_ik")
    def compute_ik(
        prim_path: str,
        target_position: List[float],
        end_effector_frame: str = "right_gripper",
        target_orientation: Optional[List[float]] = None,
        seed_joint_positions: Optional[List[float]] = None,
        random_seed: int = 123456,
        position_tolerance: float = 0.001,
        orientation_tolerance: float = 0.01,
        max_iterations: int = 100,
        timeout_ms: int = 2000,
        robot_model: str = "Franka",
    ) -> str:
        """Solve bounded Lula inverse kinematics without moving the robot.

        Quaternion order is scalar-first [w, x, y, z]. The explicit warm-start
        and random seed make repeated requests reproducible. The result reports
        achieved end-effector errors and whether collision checking was done.
        """
        return send(
            "motion.compute_ik",
            {
                "prim_path": prim_path,
                "target_position": target_position,
                "end_effector_frame": end_effector_frame,
                "target_orientation": target_orientation,
                "seed_joint_positions": seed_joint_positions,
                "random_seed": random_seed,
                "position_tolerance": position_tolerance,
                "orientation_tolerance": orientation_tolerance,
                "max_iterations": max_iterations,
                "timeout_ms": timeout_ms,
                "robot_model": robot_model,
            },
        )

    @mcp.tool("plan_joint_trajectory")
    def plan_joint_trajectory(
        prim_path: str,
        goal_joint_positions: List[float],
        start_joint_positions: Optional[List[float]] = None,
        planner: str = "rrt",
        random_seed: int = 123456,
        max_iterations: int = 5000,
        timeout_ms: int = 5000,
        robot_model: str = "Franka",
    ) -> str:
        """Plan a bounded joint trajectory and return an opaque trajectory_id.

        planner="rrt" uses NVIDIA Lula RRT and reports collision_checked=true;
        planner="cspace" creates a deterministic spline and explicitly reports
        collision_checked=false. start_joint_positions defaults to measured state;
        pass it explicitly for reproducible offline planning. This call never executes.
        """
        return send(
            "motion.plan_joint_trajectory",
            {
                "prim_path": prim_path,
                "goal_joint_positions": goal_joint_positions,
                "start_joint_positions": start_joint_positions,
                "planner": planner,
                "random_seed": random_seed,
                "max_iterations": max_iterations,
                "timeout_ms": timeout_ms,
                "robot_model": robot_model,
            },
        )

    @mcp.tool("execute_trajectory")
    def execute_trajectory(trajectory_id: str, timeout_ms: int = 30000) -> str:
        """Start a trajectory job and return immediately without blocking the MCP worker."""
        return send(
            "motion.execute_trajectory",
            {
                "trajectory_id": trajectory_id,
                "timeout_ms": timeout_ms,
            },
        )

    @mcp.tool("cancel_motion")
    def cancel_motion(job_id: str) -> str:
        """Cancel a running motion job and hold its last commanded position."""
        return send(
            "motion.cancel",
            {
                "job_id": job_id,
            },
        )

    @mcp.tool("get_motion_status")
    def get_motion_status(job_id: str) -> str:
        """Read motion job state, progress, timing, and terminal error details."""
        return send(
            "motion.get_status",
            {
                "job_id": job_id,
            },
        )
