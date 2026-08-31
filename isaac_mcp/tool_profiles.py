"""Profile-aware public MCP tool selection.

The legacy profile is the compatibility default.  The consolidated profile
replaces closely related public wrappers while retaining the same extension
commands and response envelopes.  Full is intended for migration and tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

TOOL_PROFILE_ENV = "ISAAC_MCP_TOOL_PROFILE"
DEFAULT_TOOL_PROFILE = "legacy"
VALID_TOOL_PROFILES = frozenset({"legacy", "consolidated", "full"})

# Each key is the canonical consolidated tool.  Values are legacy public names
# hidden when the consolidated profile is active.
CONSOLIDATED_REPLACEMENTS: dict[str, tuple[str, ...]] = {
    "query_prim": ("list_prims", "get_prim_info"),
    "semantic_labels": ("get_semantic_labels", "set_semantic_labels"),
    "typed_attribute": ("get_typed_attribute", "set_typed_attribute"),
    "physics_body_config": ("configure_physics_body", "get_physics_body"),
    "collision_group": ("create_collision_group", "get_collision_group"),
    "physics_joint": ("create_physics_joint", "get_physics_joint"),
    "control_timeline": ("play_simulation", "pause_simulation", "stop_simulation"),
    "robot_library": ("list_available_robots", "refresh_robot_library"),
    "get_joint_state": ("get_joint_positions",),
    "set_joint_command": ("set_joint_positions",),
    "control_gripper": ("set_gripper_width", "open_gripper", "close_gripper"),
    "control_mobile_base_velocity": ("set_mobile_base_velocity", "stop_mobile_base"),
    "motion_job": ("get_motion_status", "cancel_motion"),
    "capture_camera_output": ("capture_image",),
    "material_definition": ("create_material", "get_material"),
    "material_binding": ("apply_material", "get_material_binding"),
    "light_config": ("create_light", "modify_light"),
    "query_human": ("list_humans", "get_human"),
    "set_human_action": ("set_human_target", "set_human_look_at", "set_human_idle"),
    "create_ros2_publisher": (
        "create_ros2_clock_publisher",
        "create_ros2_tf_publisher",
        "create_ros2_joint_state_publisher",
        "create_ros2_camera_publisher",
        "create_ros2_lidar_publisher",
    ),
    "sdg_job_control": ("get_sdg_job_status", "cancel_sdg_job"),
    "job_control": ("get_job_status", "cancel_job"),
    "query_action_graph": ("list_action_graphs", "get_action_graph"),
    "action_graph_connection": ("connect_action_graph", "disconnect_action_graph"),
    "script_node_source": ("configure_script_node", "reload_script_node"),
}

# These canonical names already existed before consolidation and therefore stay
# visible in the legacy profile.
PREEXISTING_CANONICAL_TOOLS = frozenset({"get_joint_state", "set_joint_command", "capture_camera_output"})
ADDED_CONSOLIDATED_TOOLS = frozenset(CONSOLIDATED_REPLACEMENTS).difference(PREEXISTING_CANONICAL_TOOLS)
REPLACED_LEGACY_TOOLS = frozenset(
    legacy_name for legacy_names in CONSOLIDATED_REPLACEMENTS.values() for legacy_name in legacy_names
)


def resolve_tool_profile(value: str | None = None) -> str:
    """Resolve and validate the selected public tool profile."""
    profile = (value if value is not None else os.getenv(TOOL_PROFILE_ENV, DEFAULT_TOOL_PROFILE)).strip().lower()
    if profile not in VALID_TOOL_PROFILES:
        choices = ", ".join(sorted(VALID_TOOL_PROFILES))
        raise ValueError(f"{TOOL_PROFILE_ENV} must be one of: {choices}; received {profile!r}")
    return profile


def select_tool_names(names: Iterable[str], profile: str | None = None) -> tuple[str, ...]:
    """Filter the full decorated surface to one deterministic public profile."""
    selected = set(names)
    resolved = resolve_tool_profile(profile)
    if resolved == "legacy":
        selected.difference_update(ADDED_CONSOLIDATED_TOOLS)
    elif resolved == "consolidated":
        selected.difference_update(REPLACED_LEGACY_TOOLS)
    return tuple(sorted(selected))
