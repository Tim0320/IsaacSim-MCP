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

"""Test that all tool modules have correct structure."""

import ast
import os

from isaac_mcp.tool_inventory import tool_names

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "isaac_mcp", "tools")

EXPECTED_MODULES = [
    "capabilities.py",
    "controllers.py",
    "artifacts.py",
    "scene.py",
    "objects.py",
    "physics.py",
    "replicator.py",
    "ros2.py",
    "humans.py",
    "jobs.py",
    "lighting.py",
    "robots.py",
    "motion.py",
    "sensors.py",
    "materials.py",
    "assets.py",
    "simulation.py",
]


def test_all_tool_modules_exist():
    for filename in EXPECTED_MODULES:
        path = os.path.join(TOOLS_DIR, filename)
        assert os.path.exists(path), f"Missing tool module: {filename}"


def test_all_tool_modules_have_register_tools():
    for filename in EXPECTED_MODULES:
        path = os.path.join(TOOLS_DIR, filename)
        with open(path) as f:
            tree = ast.parse(f.read())
        func_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        assert "register_tools" in func_names, f"{filename} missing register_tools() function"


def test_init_imports_all_modules():
    path = os.path.join(TOOLS_DIR, "__init__.py")
    with open(path) as f:
        content = f.read()
    for module_name in [
        "capabilities",
        "artifacts",
        "scene",
        "objects",
        "physics",
        "replicator",
        "ros2",
        "humans",
        "jobs",
        "lighting",
        "robots",
        "sensors",
        "materials",
        "assets",
        "simulation",
    ]:
        assert module_name in content, f"tools/__init__.py missing import of {module_name}"


def test_named_tool_inventory_matches_authoritative_source_inventory():
    names = []
    for filename in EXPECTED_MODULES + ["graphs.py"]:
        path = os.path.join(TOOLS_DIR, filename)
        with open(path) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "tool":
                    name = decorator.args[0]
                    if isinstance(name, ast.Constant) and isinstance(name.value, str):
                        names.append(name.value)

    assert set(names) == set(tool_names())
    assert len(names) == len(set(names))
    assert {"start_job", "get_job_status", "cancel_job", "list_jobs"} <= set(names)
    assert "get_capabilities" in names
    assert {
        "compute_ik",
        "plan_joint_trajectory",
        "execute_trajectory",
        "cancel_motion",
        "get_motion_status",
    } <= set(names)
    assert {
        "get_replicator_status",
        "create_sdg_job",
        "start_sdg_job",
        "get_sdg_job_status",
        "cancel_sdg_job",
        "get_sdg_manifest",
        "delete_sdg_job",
    } <= set(names)
    assert {
        "list_controller_profiles",
        "set_gripper_width",
        "open_gripper",
        "close_gripper",
        "set_mobile_base_velocity",
        "stop_mobile_base",
    } <= set(names)
    assert "get_lidar_config" in names
    assert {
        "spawn_human",
        "list_humans",
        "get_human",
        "delete_human",
        "set_human_target",
        "set_human_look_at",
        "set_human_idle",
        "set_human_behavior",
        "get_navmesh_status",
        "bake_navmesh",
    } <= set(names)
    assert "delete_sensor" in names
    assert {"get_joint_state", "set_joint_command", "set_joint_drive_config"} <= set(names)
    assert {"get_artifact_info", "read_artifact", "delete_artifact", "cleanup_artifacts"} <= set(names)
    assert {
        "configure_physics_body",
        "get_physics_body",
        "create_collision_group",
        "get_collision_group",
        "create_physics_joint",
        "get_physics_joint",
    } <= set(names)
    assert {"create_material", "apply_material", "get_material", "get_material_binding"} <= set(names)
    assert {
        "list_action_graphs",
        "get_action_graph",
        "delete_action_graph",
        "connect_action_graph",
        "disconnect_action_graph",
        "set_action_graph_enabled",
        "get_action_graph_status",
        "evaluate_action_graph",
        "configure_script_node",
        "reload_script_node",
    } <= set(names)
