import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V6_PATH = ROOT / "isaac.sim.mcp_extension" / "isaac_sim_mcp_extension" / "adapters" / "v6.py"

EXPECTED_PUBLIC_METHODS = {
    "add_reference_to_stage",
    "apply_material",
    "cancel_motion",
    "capture_camera_image",
    "capture_camera_output",
    "clone_prim",
    "compute_holonomic_wheel_velocities",
    "compute_ik",
    "configure_physics",
    "configure_physics_body",
    "create_articulation",
    "create_camera",
    "create_collision_group",
    "create_light",
    "create_lidar",
    "create_pbr_material",
    "create_physics_joint",
    "create_physics_material",
    "create_physics_scene",
    "create_prim",
    "create_simulation_context",
    "create_world",
    "create_xform_prim",
    "delete_prim",
    "discover_environments",
    "discover_robots",
    "execute_script",
    "execute_trajectory",
    "get_assets_root_path",
    "get_backend_capability_matrix",
    "get_camera_calibration",
    "get_collision_group",
    "get_joint_config",
    "get_joint_drive_config",
    "get_joint_positions",
    "get_joint_state",
    "get_lidar_config",
    "get_lidar_point_cloud",
    "get_lidar_point_cloud_frame",
    "get_motion_status",
    "get_physics_body",
    "get_physics_joint",
    "get_physics_state",
    "get_prim_actual_size",
    "get_prim_info",
    "get_prim_transform",
    "get_robot_joint_info",
    "get_simulation_state",
    "get_stage",
    "import_urdf",
    "list_prims",
    "load_environment",
    "modify_light",
    "pause",
    "plan_joint_trajectory",
    "play",
    "reload_script",
    "set_joint_command",
    "set_joint_drive_config",
    "set_joint_positions",
    "set_prim_transform",
    "shutdown_motion",
    "step",
    "stop",
}


def _v6_class() -> ast.ClassDef:
    tree = ast.parse(V6_PATH.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "IsaacAdapterV6")


def test_v6_public_method_surface_matches_phase_d_baseline() -> None:
    methods = {
        node.name
        for node in _v6_class().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    }
    assert methods == EXPECTED_PUBLIC_METHODS
    assert len(methods) == 64


def test_v6_runtime_components_are_not_imported_by_handlers() -> None:
    handlers = ROOT / "isaac.sim.mcp_extension" / "isaac_sim_mcp_extension" / "handlers"
    offenders = []
    for path in handlers.glob("*.py"):
        if "v6_runtime" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == []
