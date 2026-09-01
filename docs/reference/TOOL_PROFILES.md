# MCP Tool Profiles

`ISAAC_MCP_TOOL_PROFILE` 決定 MCP initialization 對 client 公開的 tool surface。它不會改變 TCP `8766`、Isaac Extension command registry、response envelope 或 runtime 行為。

| Profile | Public tools | 用途 |
|---|---:|---|
| `legacy` | 129 | 預設；完整保留既有 Codex、Claude Desktop 與其他 client 設定。 |
| `consolidated` | 98 | 對話導向的精簡 action space；同一資源的讀寫或控制操作以 discriminator 合併。 |
| `full` | 151 | 同時公開新舊名稱；只供 migration、contract test 與 client 更新。 |

設定範例：

```powershell
$env:ISAAC_MCP_TOOL_PROFILE = "consolidated"
.\.venv\Scripts\python.exe -m isaac_mcp.server
```

變更後必須重新啟動 MCP Server，讓 client 重新取得 tool list。未知 profile 會在啟動時直接回報 `ValueError`。

`.env.example` 是設定範例，server 不會自動載入。環境變數必須存在於啟動 `python -m isaac_mcp.server` 的 process；修改檔案或在另一個 PowerShell 設定環境變數，不會重建已執行 server 的 tool surface。

## Runtime discovery

不要從 README、connector 畫面或歷史 task 推測 active profile。連到實際 endpoint 後查詢 MCP `tools/list` 與 `get_capabilities.data.mcp_server`：

| Active profile | `public_tool_count` | Probe tools |
|---|---:|---|
| `legacy` | 129 | 有 `play_simulation`、`open_gripper`；沒有 `control_timeline`、`control_gripper`。 |
| `consolidated` | 98 | 有 `control_timeline`、`control_gripper`；沒有 `play_simulation`、`open_gripper`。 |
| `full` | 151 | 新舊名稱都存在，只供 migration 與 contract verification。 |

若 client 顯示 legacy 名稱，但 active endpoint 回報 `consolidated` 並對 legacy call 回 `Unknown tool`，代表 client 保存了舊 tool schema，或 public URL 指向另一個 server instance。先核對 public endpoint 的 `tools/list`，再重新連線並讓 connector 重新 discovery。短期 migration 可使用 `full`；完成更新後應回到選定的 production profile。

## 合併對照

| 類別 | Consolidated tool | `action` / selector | 被取代的 legacy tools |
|---|---|---|---|
| Prim | `query_prim` | `list`, `get` | `list_prims`, `get_prim_info` |
| USD Semantic | `semantic_labels` | `get`, `set` | `get_semantic_labels`, `set_semantic_labels` |
| USD Attribute | `typed_attribute` | `get`, `set` | `get_typed_attribute`, `set_typed_attribute` |
| Rigid Body | `physics_body_config` | `get`, `configure` | `get_physics_body`, `configure_physics_body` |
| Collision | `collision_group` | `get`, `create` | `get_collision_group`, `create_collision_group` |
| Physics Joint | `physics_joint` | `get`, `create` | `get_physics_joint`, `create_physics_joint` |
| Simulation | `control_timeline` | `play`, `pause`, `stop` | `play_simulation`, `pause_simulation`, `stop_simulation` |
| Robot Library | `robot_library` | `list`, `refresh` | `list_available_robots`, `refresh_robot_library` |
| Robot Joint Read | `get_joint_state` | 原 schema | `get_joint_positions` |
| Robot Joint Control | `set_joint_command` | `mode=position|velocity|effort` | `set_joint_positions` |
| Gripper | `control_gripper` | `set_width`, `open`, `close` | `set_gripper_width`, `open_gripper`, `close_gripper` |
| AGV / Mobile Base | `control_mobile_base_velocity` | `set`, `stop` | `set_mobile_base_velocity`, `stop_mobile_base` |
| Robot Motion | `motion_job` | `get`, `cancel` | `get_motion_status`, `cancel_motion` |
| Camera Capture | `capture_camera_output` | `output_type=rgb|depth|...` | `capture_image` |
| Material Definition | `material_definition` | `get`, `create` | `get_material`, `create_material` |
| Material Binding | `material_binding` | `get`, `apply` | `get_material_binding`, `apply_material` |
| Lighting | `light_config` | `create`, `modify` | `create_light`, `modify_light` |
| Human | `query_human` | `list`, `get` | `list_humans`, `get_human` |
| Human Action | `set_human_action` | `target`, `look_at`, `idle` | `set_human_target`, `set_human_look_at`, `set_human_idle` |
| ROS 2 Publisher | `create_ros2_publisher` | `publisher_type=clock|tf|joint_state|camera|lidar` | 五個 typed publisher tools |
| SDG | `sdg_job_control` | `get`, `cancel` | `get_sdg_job_status`, `cancel_sdg_job` |
| Generic Job | `job_control` | `get`, `cancel` | `get_job_status`, `cancel_job` |
| Action Graph | `query_action_graph` | `list`, `get` | `list_action_graphs`, `get_action_graph` |
| Action Graph Connection | `action_graph_connection` | `connect`, `disconnect` | `connect_action_graph`, `disconnect_action_graph` |
| ScriptNode | `script_node_source` | `configure`, `reload` | `configure_script_node`, `reload_script_node` |

每個 consolidated tool 都呼叫原本的 legacy wrapper，而不是複製 Extension payload 邏輯。缺少 branch-specific 必填參數時回 `INVALID_ARGUMENT`，不會送出 runtime command。

## 相容性規則

- 沒有設定環境變數時仍為 `legacy`。
- `legacy` 的 tool names、required parameters 與 defaults 不變。
- `consolidated` 只隱藏被取代的 public wrappers；未參與合併的 tools 保持原樣。
- `full` 不能當成一般 production profile，因為較大的 action space 會降低 agent 選擇精準度。
- `get_capabilities` 回報目前 profile 與 public tool count；client 不應硬編碼數量。
