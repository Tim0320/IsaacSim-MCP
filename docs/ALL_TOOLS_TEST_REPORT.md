# Isaac Sim MCP 6.0.1 全功能測試報告

測試日期：2026-08-20  
平台：Windows / Isaac Sim 6.0.1-rc.7 (`C:\isaacsim`)  
MCP Server：`.venv\Scripts\python.exe -m isaac_mcp.server`  
Isaac Extension：`isaac.sim.mcp_extension`  
TCP：`127.0.0.1:8766`，LISTENING（Kit PID 20692）

## 結果摘要

共列出並實際呼叫 42 個 MCP tools，沒有遺漏或額外的未識別工具。

| 結果 | 數量 | 說明 |
|---|---:|---|
| 可用 | 38 | 呼叫成功並驗證回傳或場景效果 |
| 部分可用 | 2 | 基本功能成功，但部分參數或操作在 6.0.1 adapter 不支援 |
| 外部設定阻擋 | 2 | 工具本身可呼叫，但缺少第三方服務金鑰 |
| 內部失敗 | 0 | 修正後沒有尚未排除的程式錯誤 |

## 逐項結果

| 類別 | Tool | 結果 | 驗證內容 |
|---|---|---|---|
| 場景 | `get_scene_info` | 可用 | 成功取得 stage、assets root 與 prim 數量 |
| 場景 | `create_physics_scene` | 可用 | 建立 PhysicsScene 與 ground plane |
| 場景 | `clear_scene` | 可用 | 可清除含已載入 environment 的重度測試場景 |
| 場景 | `list_prims` | 可用 | 成功列出 `/World` prims |
| 場景 | `get_prim_info` | 可用 | 成功取得 cube prim 資訊 |
| 場景 | `list_environments` | 可用 | 找到 28 個 environment |
| 場景 | `load_environment` | 可用 | 成功載入 `grid` |
| 物件 | `create_object` | 可用 | 建立帶 physics 的 cube |
| 物件 | `delete_object` | 可用 | 成功刪除 clone |
| 物件 | `transform_object` | 可用 | 修改位置與旋轉 |
| 物件 | `clone_object` | 可用 | 成功複製 cube |
| 燈光 | `create_light` | 可用 | 建立 SphereLight |
| 燈光 | `modify_light` | 可用 | 修改 intensity 與 color |
| 材質 | `create_material` | 可用 | 建立 PBR material |
| 材質 | `apply_material` | 可用 | 成功套用到 cube |
| 模擬 | `play_simulation` | 可用 | timeline 開始播放 |
| 模擬 | `pause_simulation` | 可用 | timeline 暫停 |
| 模擬 | `stop_simulation` | 可用 | timeline 停止並重設 |
| 模擬 | `step_simulation` | 可用 | 單步執行並觀察 prim/joint |
| 模擬 | `get_simulation_state` | 可用 | 成功取得 timeline 狀態 |
| 物理 | `set_physics_params` | 可用 | V6 PhysX gravity、120 Hz time step、GPU dynamics/GPU 或 CPU/MBP mapping 均完成雙重 read-back與 step timing 驗證 |
| 物理 | `get_physics_state` | 可用 | 成功取得 rigid-body 狀態 |
| Robot | `list_available_robots` | 可用 | 找到 207 個 robot 定義 |
| Robot | `refresh_robot_library` | 可用 | robot library 更新成功 |
| Robot | `create_robot` | 可用 | 建立 Franka |
| Robot | `get_robot_info` | 可用 | 成功取得 articulation/DOF 資訊 |
| Robot | `set_joint_positions` | 可用 | 成功設定所有 joints |
| Robot | `get_joint_positions` | 可用 | 成功讀回 joints |
| Robot | `get_joint_config` | 可用 | 成功取得 joint configuration |
| Sensor | `create_camera` | 可用 | 建立 320x240 camera |
| Sensor | `capture_image` | 可用 | 播放並暖機後成功輸出 PNG |
| Sensor | `create_lidar` | 可用 | 建立 `Example_Rotary` LiDAR |
| Sensor | `get_lidar_point_cloud` | 可用 | 播放並暖機後取得 189,472 points |
| Asset | `import_urdf` | 可用 | 匯入本地最小 URDF |
| Asset | `load_usd` | 可用 | 載入本地最小 USDA |
| Asset | `search_usd` | 外部設定阻擋 | 缺少 `NVIDIA_API_KEY` |
| 3D 生成 | `generate_3d` | 外部設定阻擋 | 缺少 `ARK_API_KEY`；後續服務也可能要求 `BEAVER3D_MODEL` |
| Script | `execute_script` | 可用 | inline Python 成功執行 |
| Script | `reload_script` | 可用 | 本地 script 成功重載 |
| Action Graph | `create_action_graph` | 可用 | 建立 execution graph 與 ScriptNode |
| Action Graph | `edit_action_graph` | 部分可用 | 一般 attribute 更新成功；inline `ScriptNode.inputs:script` 查找失敗 |
| 診斷 | `get_isaac_logs` | 可用 | 成功取得 Kit log |

## 已重現並修正的錯誤

`clear_scene` 原本在刪除 `/Environment/TestGrid` 後再次呼叫 `child.GetName()`，Isaac Sim 6.x 會立即讓該 `Usd.Prim` handle 失效，因此回傳：

```text
Accessed invalid expired 'Xform' prim </Environment/TestGrid>
```

修正方式是在 `delete_prim()` 前保存 prim name。修正後重新執行全部 42 個工具，`clear_scene` 與先前受殘留 graph 連帶影響的 `create_action_graph` 均通過。

## 使用限制與注意事項

- Camera 與 LiDAR 在建立後的第一個 frame 尚無資料；必須保持 simulation 播放，等待 sensor 初始化/暖機後再讀取。這是時序要求，不是工具失效。
- `set_physics_params` 的 `time_step`/`gpu_enabled` 僅在 V6 PhysX 宣稱 supported；V5 與 Newton 仍 fail closed。time step 會同步 Stage time codes 與 min frame-rate，詳見 `docs/PHYSICS_PARAMS.md`。
- `edit_action_graph` 可修改一般 attribute，但目前不能用測試格式更新 inline ScriptNode script。

### 2026-08-21 Action Graph 隔離重測

- `create_action_graph` 成功建立 `OnPlaybackTick → ScriptNode`，播放 0.8 秒後 marker 為 48 ticks。
- 暫停 0.5 秒後仍為 48 ticks，確認 `execution` evaluator 的 timeline gating 正常。
- `edit_action_graph` 修改 `ScriptNode.inputs:usePath` 成功，讀回值正確。
- `script_file` 流程與 `reload_script` 通過；成功重新編譯 `/World/MCPActionGraphFileTest/ScriptNode`，marker 達 36 ticks。
- 更新 `ScriptNode.inputs:script` 仍回傳 `OmniGraphError: Failed trying to look up attribute`，維持「部分可用」。
- 含 non-manifold SimReady collision 的資產 Stage 在播放時可觸發 `omni.physx.plugin.dll` crash；空白 Stage 的同一 Graph 測試正常。
- MCP 啟動時出現 Pydantic `IncompleteFieldDefinitionWarning`，未影響本次 42 個工具的列出與呼叫。

## 可重跑證據

- 測試程式：`scripts/test_all_tools.py`
- 原始機器可讀結果：`test_outputs/all_tools_results.json`
- Camera 影像：`test_outputs/camera.png`

重跑：

```powershell
.\.venv\Scripts\python.exe .\scripts\test_all_tools.py
```
