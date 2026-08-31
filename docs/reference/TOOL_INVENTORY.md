# MCP Tool Inventory

> 由 `scripts/generate_tool_inventory.py` 從 `isaac_mcp/tools/*.py` 與 `isaac_mcp/tool_profiles.py` 自動產生，請勿手工修改。

Package version：`0.6.0`
Tool profile：`legacy`
Source-derived tool count：`129`

| Module | 數量 | Named tools |
|---|---:|---|
| `artifacts` | 4 | `cleanup_artifacts`, `delete_artifact`, `get_artifact_info`, `read_artifact` |
| `assets` | 6 | `generate_3d`, `import_urdf`, `list_nvidia_assets`, `load_usd`, `search_usd`, `spawn_nvidia_asset` |
| `capabilities` | 2 | `get_capabilities`, `get_runtime_status` |
| `controllers` | 6 | `close_gripper`, `list_controller_profiles`, `open_gripper`, `set_gripper_width`, `set_mobile_base_velocity`, `stop_mobile_base` |
| `graphs` | 12 | `configure_script_node`, `connect_action_graph`, `create_action_graph`, `delete_action_graph`, `disconnect_action_graph`, `edit_action_graph`, `evaluate_action_graph`, `get_action_graph`, `get_action_graph_status`, `list_action_graphs`, `reload_script_node`, `set_action_graph_enabled` |
| `humans` | 10 | `bake_navmesh`, `delete_human`, `get_human`, `get_navmesh_status`, `list_humans`, `set_human_behavior`, `set_human_idle`, `set_human_look_at`, `set_human_target`, `spawn_human` |
| `jobs` | 4 | `cancel_job`, `get_job_status`, `list_jobs`, `start_job` |
| `lighting` | 2 | `create_light`, `modify_light` |
| `materials` | 4 | `apply_material`, `create_material`, `get_material`, `get_material_binding` |
| `motion` | 5 | `cancel_motion`, `compute_ik`, `execute_trajectory`, `get_motion_status`, `plan_joint_trajectory` |
| `objects` | 4 | `clone_object`, `create_object`, `delete_object`, `transform_object` |
| `physics` | 6 | `configure_physics_body`, `create_collision_group`, `create_physics_joint`, `get_collision_group`, `get_physics_body`, `get_physics_joint` |
| `replicator` | 7 | `cancel_sdg_job`, `create_sdg_job`, `delete_sdg_job`, `get_replicator_status`, `get_sdg_job_status`, `get_sdg_manifest`, `start_sdg_job` |
| `robots` | 9 | `create_robot`, `get_joint_positions`, `get_joint_state`, `get_robot_info`, `list_available_robots`, `refresh_robot_library`, `set_joint_command`, `set_joint_drive_config`, `set_joint_positions` |
| `ros2` | 8 | `create_ros2_camera_publisher`, `create_ros2_clock_publisher`, `create_ros2_joint_state_publisher`, `create_ros2_lidar_publisher`, `create_ros2_tf_publisher`, `delete_ros2_workflow`, `get_ros2_status`, `list_ros2_workflows` |
| `scene` | 19 | `apply_stage_batch`, `clear_scene`, `create_physics_scene`, `edit_composition_arc`, `edit_sublayer`, `get_prim_info`, `get_scene_info`, `get_semantic_labels`, `get_stage_composition`, `get_typed_attribute`, `list_environments`, `list_prims`, `load_environment`, `new_stage`, `open_stage`, `save_stage_as`, `set_semantic_labels`, `set_typed_attribute`, `set_variant_selection` |
| `sensors` | 8 | `capture_camera_output`, `capture_image`, `create_camera`, `create_lidar`, `delete_sensor`, `get_camera_calibration`, `get_lidar_config`, `get_lidar_point_cloud` |
| `simulation` | 13 | `execute_script`, `get_isaac_logs`, `get_joint_config`, `get_physics_state`, `get_script_audit_log`, `get_script_policy`, `get_simulation_state`, `pause_simulation`, `play_simulation`, `reload_script`, `set_physics_params`, `step_simulation`, `stop_simulation` |

這份 inventory 證明 source 的 registration intent。目前 runtime support、backend state 與 prerequisites 以 `get_capabilities` 為準；live success 必須有 guarded read-back evidence。
