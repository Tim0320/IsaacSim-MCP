"""Explicit robot controller profiles used by high-level named tools."""

from __future__ import annotations

from typing import Any

CONTROLLER_PROFILES: dict[str, dict[str, Any]] = {
    "franka_parallel_gripper": {
        "kind": "gripper",
        "robot": "NVIDIA Franka Panda",
        "joint_names": ["panda_finger_joint1", "panda_finger_joint2"],
        "joint_type": "prismatic",
        "min_width_m": 0.0,
        "max_width_m": 0.08,
        "open_width_m": 0.08,
        "closed_width_m": 0.0,
        "mapping": "symmetric_half_width",
    },
    "nvidia_jetbot_differential": {
        "kind": "differential_mobile_base",
        "robot": "NVIDIA Jetbot",
        "joint_names": ["left_wheel_joint", "right_wheel_joint"],
        "joint_type": "revolute",
        "wheel_radius_m": 0.03,
        "wheel_base_m": 0.1125,
        "max_linear_speed_mps": 0.5,
        "max_lateral_speed_mps": 0.0,
        "max_yaw_speed_radps": 5.0,
    },
    "nvidia_kaya_holonomic": {
        "kind": "holonomic_mobile_base",
        "robot": "NVIDIA Kaya",
        "joint_names": ["axle_0_joint", "axle_1_joint", "axle_2_joint"],
        "joint_type": "revolute",
        "com_prim_suffix": "/base_link/control_offset",
        "max_linear_speed_mps": 1.0,
        "max_lateral_speed_mps": 1.0,
        "max_yaw_speed_radps": 3.0,
    },
}


def public_profiles() -> dict[str, dict[str, Any]]:
    """Return a detached, JSON-safe profile snapshot."""
    return {name: dict(profile) for name, profile in CONTROLLER_PROFILES.items()}
