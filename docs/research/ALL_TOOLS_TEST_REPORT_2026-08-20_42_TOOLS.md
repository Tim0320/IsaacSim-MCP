# Isaac Sim MCP 6.0.1 歷史 42-tool 測試報告

> 這是 2026-08-20 的原始證據快照。當時的 `scripts/test_all_tools.py` 會呼叫 `clear_scene`；Phase 6.1 後已停止提供該 destructive 重跑方式，只保留結果作為歷史 evidence。

平台：Windows / Isaac Sim 6.0.1-rc.7 (`C:\isaacsim`)
TCP：`127.0.0.1:8766`（Kit PID 20692）

## 結果摘要

共列出並實際呼叫 42 個 MCP tools：38 可用、2 部分可用、2 外部設定阻擋、0 內部失敗。

## 逐項結果

| 類別 | Tool | 結果 | 驗證內容 |
|---|---|---|---|
| 場景 | `get_scene_info` | 可用 | 取得 stage、assets root 與 prim 數量 |
| 場景 | `create_physics_scene` | 可用 | 建立 PhysicsScene 與 ground plane |
| 場景 | `clear_scene` | 可用 | 清除測試場景；此操作現已由 scratch guard 保護 |
| 場景 | `list_prims` | 可用 | 列出 `/World` prims |
| 場景 | `get_prim_info` | 可用 | 取得 cube prim 資訊 |
| 場景 | `list_environments` | 可用 | 找到 28 個 environment |
| 場景 | `load_environment` | 可用 | 載入 `grid` |
| 物件 | `create_object` | 可用 | 建立帶 physics 的 cube |
| 物件 | `delete_object` | 可用 | 刪除 clone |
| 物件 | `transform_object` | 可用 | 修改位置與旋轉 |
| 物件 | `clone_object` | 可用 | 複製 cube |
| 燈光 | `create_light` | 可用 | 建立 SphereLight |
| 燈光 | `modify_light` | 可用 | 修改 intensity 與 color |
| 材質 | `create_material` | 可用 | 建立 PBR material |
| 材質 | `apply_material` | 可用 | 套用到 cube |
| 模擬 | `play_simulation` | 可用 | timeline 播放 |
| 模擬 | `pause_simulation` | 可用 | timeline 暫停 |
| 模擬 | `stop_simulation` | 可用 | timeline 停止並重設 |
| 模擬 | `step_simulation` | 可用 | 單步並觀察 prim/joint |
| 模擬 | `get_simulation_state` | 可用 | 取得 timeline 狀態 |
| 物理 | `set_physics_params` | 可用 | V6 PhysX gravity、120 Hz、GPU/CPU mapping read-back |
| 物理 | `get_physics_state` | 可用 | 取得 rigid-body 狀態 |
| Robot | `list_available_robots` | 可用 | 找到 207 個 robot 定義 |
| Robot | `refresh_robot_library` | 可用 | library 更新成功 |
| Robot | `create_robot` | 可用 | 建立 Franka |
| Robot | `get_robot_info` | 可用 | 取得 articulation/DOF 資訊 |
| Robot | `set_joint_positions` | 可用 | 設定所有 joints |
| Robot | `get_joint_positions` | 可用 | 讀回 joints |
| Robot | `get_joint_config` | 可用 | 取得 joint configuration |
| Sensor | `create_camera` | 可用 | 建立 320x240 camera |
| Sensor | `capture_image` | 可用 | 暖機後輸出 PNG |
| Sensor | `create_lidar` | 可用 | 建立 `Example_Rotary` LiDAR |
| Sensor | `get_lidar_point_cloud` | 可用 | 暖機後取得 189,472 points |
| Asset | `import_urdf` | 可用 | 匯入本地最小 URDF |
| Asset | `load_usd` | 可用 | 載入本地最小 USDA |
| Asset | `search_usd` | 外部設定阻擋 | 缺少 `NVIDIA_API_KEY` |
| 3D 生成 | `generate_3d` | 外部設定阻擋 | 缺少 `ARK_API_KEY`；provider 也可能要求 `BEAVER3D_MODEL` |
| Script | `execute_script` | 可用 | inline Python 執行 |
| Script | `reload_script` | 可用 | 本地 script 重載 |
| Action Graph | `create_action_graph` | 可用 | 建立 execution graph 與 ScriptNode |
| Action Graph | `edit_action_graph` | 部分可用 | 一般 attribute 成功；inline script 當時查找失敗，後續 4.1 已修正並 live 驗收 |
| 診斷 | `get_isaac_logs` | 可用 | 取得 Kit log |

## 當時修正與限制

`clear_scene` 曾在刪除 `/Environment/TestGrid` 後讀取失效 `Usd.Prim`，產生 `Accessed invalid expired 'Xform' prim`。修正為刪除前保存 prim name，42-tool 重跑後通過。Camera/LiDAR 需要播放暖機；外部 provider tools 缺 key 時屬 blocked，不是 code failure。

原始輸出曾位於 ignored `test_outputs/all_tools_results.json` 與 `test_outputs/camera.png`。目前統一、tracked 的逐項 artifact 是 [`ALL_TOOLS_TEST_RESULTS.json`](ALL_TOOLS_TEST_RESULTS.json)。
