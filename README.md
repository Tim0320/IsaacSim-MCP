# IsaacSim-MCP

用 Model Context Protocol（MCP）控制 NVIDIA Isaac Sim。AI 助理可以建立工廠場景、載入 NVIDIA 資產、操作機器人與人物、讀取感測器、控制模擬，以及建立 Action Graph。

此版本以 Windows 與 **Isaac Sim 6.0.1** 為主要驗證環境，包含 68 個 MCP tools、NVIDIA Replicator Agent 人物支援、NVIDIA 資產目錄，以及工廠配置與互動範例。

> 本專案延伸自 [whats2000/isaacsim-mcp-server](https://github.com/whats2000/isaacsim-mcp-server)，沿用 MIT License。原始作者與後續貢獻者資訊保留於 `LICENSE` 及原始檔案標頭。

## 功能

- 建立、查詢與清除 USD 場景
- 建立基本物件、燈光、PBR 材質與 physics material
- 載入 USD、匯入 URDF、搜尋及生成 3D 資產
- 建立機器人並讀寫 articulation joint
- 產生 NVIDIA IRA 動畫人物，支援 wander、patrol、stop、manual
- 建立 Camera 與 RTX LiDAR，輸出 RGB 影像及點雲
- 播放、暫停、停止及逐 frame 執行模擬
- 建立 Action Graph、ScriptNode、連線與 attribute
- 執行或重新載入 Isaac Sim Python script
- 建立 10 個工作區、3 台 AGV、機器手臂、輸送帶與人物的工廠範例

## IsaacSim-MCP 1.x 感測能力基準

研究工作中的 `1.1～1.6` 已完成，對應 task 文件 Phase 1 的六個 Camera、LiDAR、artifact 與 lifecycle 項目。這個編號是研究項目標籤，不是 Python package 版本。

| 項目 | 已完成能力 | 主要 tools | 契約與 live verifier |
|---|---|---|---|
| 1.1 | Camera RGB metadata、受控 PNG artifact、有限制的 inline PNG | `create_camera`, `capture_image` | [`CAMERA_RGB.md`](docs/CAMERA_RGB.md)／[`verify_camera_rgb_live.py`](scripts/verify_camera_rgb_live.py) |
| 1.2 | depth、distance、三種 segmentation、normals、motion vectors、calibration | `capture_camera_output`, `get_camera_calibration` | [`CAMERA_OUTPUTS.md`](docs/CAMERA_OUTPUTS.md)／[`verify_camera_outputs_live.py`](scripts/verify_camera_outputs_live.py) |
| 1.3 | Cartesian RTX LiDAR point cloud、range、角度、intensity 與 object ID | `get_lidar_point_cloud` | [`LIDAR_POINT_CLOUD.md`](docs/LIDAR_POINT_CLOUD.md)／[`verify_lidar_point_cloud_live.py`](scripts/verify_lidar_point_cloud_live.py) |
| 1.4 | named preset 或 generic FOV／解析度／rate／range，並讀回有效 USD 設定 | `create_lidar`, `get_lidar_config` | [`LIDAR_CONFIG.md`](docs/LIDAR_CONFIG.md)／[`verify_lidar_config_live.py`](scripts/verify_lidar_config_live.py) |
| 1.5 | Camera/LiDAR 共用 artifact handle、chunk、SHA-256、TTL、容量與 cleanup | `get_artifact_info`, `read_artifact`, `delete_artifact`, `cleanup_artifacts` | [`ARTIFACT_TRANSPORT.md`](docs/ARTIFACT_TRANSPORT.md)／[`verify_artifact_transport_live.py`](scripts/verify_artifact_transport_live.py) |
| 1.6 | 完整 sensor teardown、刪除後 read-back、同路徑重建與重複 pipeline 防護 | `delete_sensor`、sensor-aware `delete_object` | [`SENSOR_LIFECYCLE.md`](docs/SENSOR_LIFECYCLE.md)／[`verify_sensor_lifecycle_live.py`](scripts/verify_sensor_lifecycle_live.py) |

完整研究現況、缺漏位置、限制與歷史驗收證據請讀 [`ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`](docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md)。後續 agent 應先讀專案 skill 的 [`isaacsim-mcp-1x.md`](.agents/skills/omniverse-windows-workspace/references/isaacsim-mcp-1x.md)，再讀對應契約與 verifier。

> [!IMPORTANT]
> 2026-08-23 的 Isaac Sim `6.0.1-rc.7` live 結果是已完成的歷史基準。要宣稱目前仍可用，必須重新核對 Git HEAD、`get_capabilities`、adapter/backend、TCP `8766`、physics GPU ordinal、scratch stage、read-back、cleanup 與 log/native-dump 證據。`9904` 文件 MCP、static tests 或 artifact hash 都不能單獨證明 live stage 控制成功。

## IsaacSim-MCP 2.x Robot 控制

| 研究項目 | 能力 | Named tools | 契約／驗證 |
|---|---|---|---|
| 2.1 | 完整 joint name/index mapping、position/velocity/effort measured state 與三種 atomic command mode | `get_joint_state`, `set_joint_command` | [`ROBOT_JOINT_CONTROL.md`](docs/ROBOT_JOINT_CONTROL.md)／[`verify_robot_joint_control_live.py`](scripts/verify_robot_joint_control_live.py) |
| 2.2 | Drive stiffness/damping、max force/velocity、force/acceleration mode 的 stopped-timeline atomic setter | `set_joint_drive_config`, `get_joint_config` | [`ROBOT_JOINT_DRIVE_CONFIG.md`](docs/ROBOT_JOINT_DRIVE_CONFIG.md)／[`verify_robot_joint_drive_config_live.py`](scripts/verify_robot_joint_drive_config_live.py) |
| 2.3 | Lula IK、RRT／C-space trajectory、non-blocking job、pause/resume、cancel、timeout | `compute_ik`, `plan_joint_trajectory`, `execute_trajectory`, `cancel_motion`, `get_motion_status` | [`MOTION_CONTROL.md`](docs/MOTION_CONTROL.md)／[`verify_motion_control_live.py`](scripts/verify_motion_control_live.py) |
| 2.4 | Explicit profile gripper width/open/close、differential/holonomic base velocity 與 zero-target stop | `list_controller_profiles`, `set_gripper_width`, `open_gripper`, `close_gripper`, `set_mobile_base_velocity`, `stop_mobile_base` | [`CONTROLLER_PROFILES.md`](docs/CONTROLLER_PROFILES.md)／[`verify_controller_profiles_live.py`](scripts/verify_controller_profiles_live.py) |

`effort` 是每個 update 必須重送的 command。連續控制由後續 controller lifecycle 負責；目前 tool 會套用一次並立即 read-back。

2026-08-24 已在 Isaac Sim `6.0.1-rc.7`／PhysX 以 9-DOF Franka scratch fixture 完成 2.1 live 驗證；三種 target、physics update 後 measured state、invalid-name atomicity、Stop-first cleanup、PID/port、GPU、log 與 native dump 檢查均通過。

2026-08-24 已完成 2.2 PhysX live 驗證：`panda_joint1` 的 stiffness、damping、max force、max velocity 與 drive type 寫入/read-back 均符合 float32 容差；負值、未知 joint 與 active timeline 寫入會在 apply 前拒絕。Newton 的 max velocity 明確 unsupported，其餘 drive 欄位等待專用 Newton live run。

2026-08-24 已完成 2.3 PhysX scratch live 驗收：68-command registry、Franka Lula IK position error `7.36e-7 m`、相同 warm start／seed deterministic 解、RRT 限定 scope collision result，以及 paused→running→completed、cancel、1 ms timeout 全數通過。IK 不支援 collision avoidance，且目前 RRT 未納入 USD scene obstacles，response 會明確揭露兩項限制。

2026-08-24 已完成 2.4 PhysX scratch live 驗收：Franka gripper open/set-width/close target、profile mismatch atomicity、Jetbot differential 與 Kaya holonomic wheel target/measured-state read-back，以及兩種 base 的 zero-target stop 全數通過。Kaya 使用 wheeled-robots extension `0.2.11` 的 USD geometry，未在 MCP 層寫死 holonomic geometry。

同日首次 scratch 重跑修正了 verifier target-only atomicity、owned physics cleanup，以及雙 GPU session 中 Warp command arrays 必須跟隨 Articulation physics device 的問題。原本失效 session 的 RTX CUDA external-memory failure、GPU page fault 與 `ERROR_DEVICE_LOST` 僅保留為診斷歷史；最終 2.4→2.3 驗收使用乾淨重啟、active-display physics GPU guard 的新 session，並通過 fixture cleanup、PID/TCP、run log 與 native-dump gate。

## 系統需求

| 項目 | 需求 |
|---|---|
| 作業系統 | Windows 10／11 64-bit |
| Isaac Sim | 6.0.1，預設安裝位置為 `C:\isaacsim` |
| Python | 3.10 以上 |
| MCP 套件 | `mcp[cli]>=1.28.1,<2` |
| 網路連接埠 | TCP `8766` |

Isaac Sim 與 MCP Server 是兩個獨立程序：

```text
AI 助理 / MCP Client
        │ stdio
        ▼
Python MCP Server
        │ TCP 127.0.0.1:8766
        ▼
Isaac Sim MCP Extension
        │
        ▼
Isaac Sim 6.0.1 / USD / PhysX
```

## 安裝

### 1. 下載專案

```powershell
git clone https://github.com/Tim0320/IsaacSim-MCP.git
cd IsaacSim-MCP
```

### 2. 建立 Python 環境

使用 Python 內建工具：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

或使用 `uv`：

```powershell
uv sync
```

### 3. 指定 Isaac Sim 位置

若 Isaac Sim 位於 `C:\isaacsim`，可直接略過這一步。其他位置請在目前 PowerShell session 設定：

```powershell
$env:ISAACSIM_ROOT = "D:\你的\IsaacSim\路徑"
```

## 啟動

### 1. 啟動 Isaac Sim 與 Extension

在第一個 PowerShell 視窗執行：

```powershell
.\scripts\run_isaac_sim.ps1
```

腳本會驗證 Isaac Sim 6.0.1、載入 `isaac.sim.mcp_extension`，並在 `127.0.0.1:8766` 啟動 TCP Server。

> [!WARNING]
> **Isaac Sim 6.0.1 多 GPU / PhysX 防護**：`/physics/cudaDevice=-1` 可能在 Timeline `Stop` 時造成 `PhysXGpu_64.dll` native crash。Windows launcher 會從 `nvidia-smi` 找出當下唯一的 `display_active=Enabled` GPU，並傳入明確 ordinal；它不是永久固定 GPU 0。若無法唯一判定才會警告並 fallback 到 GPU 0。可用 `-PhysicsGpu 1` 或 `$env:ISAAC_PHYSICS_GPU="1"` 覆寫。不要用 renderer multi-GPU 設定代替這項 PhysX 防護；顯式選擇 `-1` 仍會保留，但會顯示高風險警告。

```powershell
# 本次啟動手動選擇 physics GPU 1
.\scripts\run_isaac_sim.ps1 -PhysicsGpu 1

# 跨多次啟動覆寫；移除變數後恢復自動偵測主要顯示 GPU
$env:ISAAC_PHYSICS_GPU = "1"
.\scripts\run_isaac_sim.ps1
```

### 2. 設定 MCP Client

把以下設定加入 MCP Client，並將 `command` 改成這個 repository 的實際絕對路徑：

```json
{
  "mcpServers": {
    "isaac-sim": {
      "command": "D:\\Dev\\IsaacSim-MCP\\.venv\\Scripts\\python.exe",
      "args": ["-m", "isaac_mcp.server"],
      "env": {
        "ISAAC_MCP_HOST": "127.0.0.1",
        "ISAAC_MCP_PORT": "8766"
      }
    }
  }
}
```

也可以在第二個 PowerShell 視窗直接啟動 MCP Server：

```powershell
.\scripts\run_mcp_server.ps1
```

### 3. 確認連線

請 MCP Client 先呼叫 capability discovery，再讀取 Stage：

```text
get_capabilities
get_scene_info
```

`get_capabilities` 會回傳 Isaac Sim 版本、adapter、physics backend、extension states、feature flags 與不支援參數；
`get_scene_info` 會回傳目前 Stage、asset root 與 prim 數量。完整 schema 請見 [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md)。

全部 68 個 tools 都使用固定 response envelope，包含 `status`、`code`、`data`、`command_id`、timing、artifact 與 read-back 欄位。完整契約請見 [`docs/RESPONSE_SCHEMA.md`](docs/RESPONSE_SCHEMA.md)。

`capture_image` 支援 `metadata|artifact|inline`。預設輸出具備 dimensions、dtype、frame/timestamp 與 SHA-256 的受控 PNG artifact；完整契約請見 [`docs/CAMERA_RGB.md`](docs/CAMERA_RGB.md)。

`capture_camera_output` 提供 depth、distance-to-image-plane、semantic/instance/instance-ID segmentation、normals 與 motion vectors；`get_camera_calibration` 回傳 intrinsic/extrinsic、projection、resolution 與 units。完整契約請見 [`docs/CAMERA_OUTPUTS.md`](docs/CAMERA_OUTPUTS.md)。

## MCP Tools

目前共 68 個 tools：

| 類別 | Tools |
|---|---|
| 系統能力 | `get_capabilities` |
| Artifact | `get_artifact_info`, `read_artifact`, `delete_artifact`, `cleanup_artifacts` |
| 場景 | `get_scene_info`, `create_physics_scene`, `clear_scene`, `list_prims`, `get_prim_info`, `list_environments`, `load_environment` |
| 物件 | `create_object`, `delete_object`, `transform_object`, `clone_object` |
| 燈光 | `create_light`, `modify_light` |
| 材質 | `create_material`, `apply_material` |
| 機器人 | `create_robot`, `list_available_robots`, `refresh_robot_library`, `get_robot_info`, `set_joint_positions`, `get_joint_positions`, `get_joint_state`, `set_joint_command`, `set_joint_drive_config` |
| Motion | `compute_ik`, `plan_joint_trajectory`, `execute_trajectory`, `cancel_motion`, `get_motion_status` |
| Controller profiles | `list_controller_profiles`, `set_gripper_width`, `open_gripper`, `close_gripper`, `set_mobile_base_velocity`, `stop_mobile_base` |
| 人物 | `spawn_human` |
| 感測器 | `create_camera`, `capture_image`, `capture_camera_output`, `get_camera_calibration`, `create_lidar`, `get_lidar_config`, `get_lidar_point_cloud`, `delete_sensor` |
| 資產 | `list_nvidia_assets`, `spawn_nvidia_asset`, `import_urdf`, `load_usd`, `search_usd`, `generate_3d` |
| 模擬與診斷 | `play_simulation`, `pause_simulation`, `stop_simulation`, `step_simulation`, `set_physics_params`, `get_isaac_logs`, `get_simulation_state`, `get_physics_state`, `get_joint_config`, `execute_script`, `reload_script` |
| Action Graph | `create_action_graph`, `edit_action_graph` |

## 基本使用範例

### 建立場景與機器人

依序請 MCP Client 執行：

```text
1. 呼叫 create_physics_scene 建立重力與地面。
2. 呼叫 list_available_robots 查詢正確 robot key。
3. 呼叫 create_robot 建立 Franka。
4. 呼叫 get_robot_info 檢查 articulation 與 DOF。
5. 呼叫 set_joint_positions 設定關節。
6. 呼叫 step_simulation 並觀察 robot prim。
```

### 建立 Action Graph

需要反覆修改控制邏輯時，使用本機 script file：

```text
create_action_graph(
  graph_path="/World/RobotController",
  script_file="D:\\Dev\\IsaacSim-MCP\\scripts\\controller.py"
)
```

修改 script 後呼叫：

```text
reload_script(file_path="D:\\Dev\\IsaacSim-MCP\\scripts\\controller.py")
```

`script_file + reload_script` 已在 Isaac Sim 6.0.1 實測通過，適合持續開發。inline ScriptNode 適合短而固定的程式碼。

### 產生 NVIDIA 人物

人物需要可用 NavMesh。以下會建立 NavMesh volume 並產生一位巡遊人物：

```text
spawn_human(
  count=1,
  behavior="wander",
  auto_create_navmesh_volume=true,
  navmesh_volume_center=[0, 0, 1],
  navmesh_volume_size=[32, 32, 4]
)
```

需要自訂人物互動時，將 `behavior` 設為 `manual`，再搭配 `reload_script` 控制 IRA Behavior Agent。

### 建立工廠場景

工廠相關腳本位於 `scripts/`：

| Script | 用途 |
|---|---|
| `create_factory_scene.py` | 建立 32 × 32 公尺、10 個工作區與 3 台 AGV 的基本工廠 |
| `prepare_factory_assets.py` | 準備工廠資產 |
| `configure_factory_assets_mcp.py` | 透過 MCP 配置機器手臂、AGV、輸送帶等資產 |
| `factory_interaction.py` | 工廠互動控制 |
| `nvidia_human_interaction.py` | NVIDIA 人物互動範例 |
| `verify_factory_scene.py` | 驗證工廠數量、配置與 metadata |

生成的 USD 與測試輸出會放在 `test_outputs/`，此資料夾已由 `.gitignore` 排除。

## 選用 API 金鑰

一般場景、機器人、人物、感測器與 Action Graph 不需要 API 金鑰。只有以下外部服務需要：

```powershell
$env:NVIDIA_API_KEY = "你的 NVIDIA API key"
$env:ARK_API_KEY = "你的 Beaver3D API key"
```

- `search_usd` 使用 `NVIDIA_API_KEY`
- `generate_3d` 使用 `ARK_API_KEY`，服務端也可能要求 `BEAVER3D_MODEL`

請勿把金鑰寫進程式碼、README、`.env` 或 commit。

## 操作原則與限制

- `step_simulation` 只能在暫停或停止狀態使用；播放中會明確拒絕。
- Action Graph 使用 `execution` evaluator，只有 timeline 播放時執行。
- Camera 與 LiDAR 建立後需要播放並暖機數個 frame 才會產生資料。
- `create_lidar` 可選 named preset，或直接指定 FOV、角解析度、rotation rate 與 range；`get_lidar_config` 會讀回實際 USD Core schema。兩種模式與限制見 [`docs/LIDAR_CONFIG.md`](docs/LIDAR_CONFIG.md)。
- `get_lidar_point_cloud` 支援 `metadata|artifact|inline`；預設回傳包含 typed `.npy` fields 的 `.npz` artifact。完整契約見 [`docs/LIDAR_POINT_CLOUD.md`](docs/LIDAR_POINT_CLOUD.md)。
- `set_physics_params` 目前直接支援 `gravity`；`time_step` 與 `gpu_enabled` 需使用 `execute_script`。
- `edit_action_graph` 可修改一般 attribute 與新增連線；修改 inline `ScriptNode.inputs:script` 在 6.0.1 仍有限制。
- 載入含 non-manifold collision 的資產可能使 PhysX native plugin 崩潰。先在乾淨 Stage 驗證資產與碰撞設定。
- Isaac Sim 6.0.1 多 GPU 環境必須讓 PhysX 使用明確 GPU ordinal；launcher 會依當下主要顯示 GPU 決定，不可移除這項防護或改回未警告的 `-1`。
- `execute_script` 權限很高，只執行可信任程式碼，並避免在 Action Graph 同時控制相同 articulation 時修改它。

## 測試

安裝開發依賴：

```powershell
uv sync --dev
```

執行不需要 Isaac Sim runtime 的測試：

```powershell
uv run pytest -q --ignore=tests/test_launcher_engine.py --ignore=tests/test_integration.py -k "not test_detect_version_returns_zero_on_failure"
uv run ruff check .
uv run ruff format --check .
```

完整 MCP live test 需要先啟動 Isaac Sim：

```powershell
.\.venv\Scripts\python.exe .\scripts\test_all_tools.py
```

測試結果與限制請見：

- [`docs/ALL_TOOLS_TEST_REPORT.md`](docs/ALL_TOOLS_TEST_REPORT.md)
- [`docs/NVIDIA_ASSET_CATALOG.md`](docs/NVIDIA_ASSET_CATALOG.md)

## 專案備份與還原驗證

修改程式碼前後執行：

```powershell
.\scripts\backup_project.ps1 -Label before-camera-rgb
```

預設備份到 `E:\碩士論文\backups\isaacsim-mcp`。也可用 `-BackupRoot` 指定 repo 外的其他目錄。
每次執行會產生唯一、不覆寫的資料夾，內容包括：

- 完整 Git history bundle 與 SHA-256
- staged、unstaged binary patches
- 通過安全篩選的 untracked files
- Git LFS 狀態與目前 tracked LFS working files
- `manifest.json`、`BACKUP_MANIFEST.md` 與逐檔 SHA-256

腳本會在新的暫存目錄 clone bundle、套用 dirty snapshot，再逐檔比對 SHA-256。驗證失敗時會建立
`BACKUP_FAILED.txt` 並回傳錯誤。credential-like files、Git ignored files、cache/build 目錄及超過
`-MaxUntrackedFileBytes` 的檔案不會被複製；排除原因記錄在 `manifest.json`。腳本不會 commit 或 push。

## 專案結構

```text
IsaacSim-MCP/
├─ .agents/                   專案 skill 與 1.x 後續 agent 閱讀索引
├─ isaac_mcp/                 Python MCP Server 與 68 個 tool 定義
├─ isaac.sim.mcp_extension/   Isaac Sim Extension、handlers 與 V5/V6 adapters
├─ scripts/                   Windows/Linux 啟動、工廠與驗證腳本
├─ demo/                      機器人控制範例
├─ test_assets/               小型測試資產與 Action Graph probe
├─ tests/                     自動測試
├─ docs/                      測試報告與 NVIDIA 資產目錄
├─ media/                     README 與展示媒體
├─ pyproject.toml             Python 套件設定
└─ LICENSE                    MIT License
```

## 上傳 GitHub

確認測試通過後執行：

```powershell
git init -b main
git add .
git status
git commit -m "Initial Isaac Sim MCP release"
git remote add origin https://github.com/Tim0320/IsaacSim-MCP.git
git push -u origin main
```

`git status` 不應出現 `.venv/`、`test_outputs/`、`logs/`、`.env` 或 API 金鑰檔案。

## 授權

本專案使用 [MIT License](LICENSE)。發布修改版時請保留原授權、copyright notice 與來源歸屬。
