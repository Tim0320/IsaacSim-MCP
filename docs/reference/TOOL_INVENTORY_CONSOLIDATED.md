# MCP Tool Inventory

> 由 `scripts/generate_tool_inventory.py` 從 `isaac_mcp/tools/*.py` 與 `isaac_mcp/tool_profiles.py` 自動產生，請勿手工修改。

Package version：`0.6.0`
Tool profile：`consolidated`
Source-derived tool count：`98`

| Module | 數量 | Named tools |
|---|---:|---|
| `artifacts` | 4 | `cleanup_artifacts`, `delete_artifact`, `get_artifact_info`, `read_artifact` |
| `assets` | 6 | `generate_3d`, `import_urdf`, `list_nvidia_assets`, `load_usd`, `search_usd`, `spawn_nvidia_asset` |
| `capabilities` | 2 | `get_capabilities`, `get_runtime_status` |
| `consolidated` | 22 | `action_graph_connection`, `collision_group`, `control_gripper`, `control_mobile_base_velocity`, `control_timeline`, `create_ros2_publisher`, `job_control`, `light_config`, `material_binding`, `material_definition`, `motion_job`, `physics_body_config`, `physics_joint`, `query_action_graph`, `query_human`, `query_prim`, `robot_library`, `script_node_source`, `sdg_job_control`, `semantic_labels`, `set_human_action`, `typed_attribute` |
| `controllers` | 1 | `list_controller_profiles` |
| `graphs` | 6 | `create_action_graph`, `delete_action_graph`, `edit_action_graph`, `evaluate_action_graph`, `get_action_graph_status`, `set_action_graph_enabled` |
| `humans` | 5 | `bake_navmesh`, `delete_human`, `get_navmesh_status`, `set_human_behavior`, `spawn_human` |
| `jobs` | 2 | `list_jobs`, `start_job` |
| `motion` | 3 | `compute_ik`, `execute_trajectory`, `plan_joint_trajectory` |
| `objects` | 4 | `clone_object`, `create_object`, `delete_object`, `transform_object` |
| `replicator` | 5 | `create_sdg_job`, `delete_sdg_job`, `get_replicator_status`, `get_sdg_manifest`, `start_sdg_job` |
| `robots` | 5 | `create_robot`, `get_joint_state`, `get_robot_info`, `set_joint_command`, `set_joint_drive_config` |
| `ros2` | 3 | `delete_ros2_workflow`, `get_ros2_status`, `list_ros2_workflows` |
| `scene` | 13 | `apply_stage_batch`, `clear_scene`, `create_physics_scene`, `edit_composition_arc`, `edit_sublayer`, `get_scene_info`, `get_stage_composition`, `list_environments`, `load_environment`, `new_stage`, `open_stage`, `save_stage_as`, `set_variant_selection` |
| `sensors` | 7 | `capture_camera_output`, `create_camera`, `create_lidar`, `delete_sensor`, `get_camera_calibration`, `get_lidar_config`, `get_lidar_point_cloud` |
| `simulation` | 10 | `execute_script`, `get_isaac_logs`, `get_joint_config`, `get_physics_state`, `get_script_audit_log`, `get_script_policy`, `get_simulation_state`, `reload_script`, `set_physics_params`, `step_simulation` |

這份 inventory 證明 source 的 registration intent。目前 runtime support、backend state 與 prerequisites 以 `get_capabilities` 為準；live success 必須有 guarded read-back evidence。
