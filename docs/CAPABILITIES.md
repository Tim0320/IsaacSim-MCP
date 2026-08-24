# `get_capabilities` schema 1.0

`get_capabilities` 是 read-only named tool，用來確認目前 MCP server 與 live Isaac Sim extension 真正能做什麼。
它不需要 USD stage 已完成建立，因此可作為 MCP 工作流程的第一個呼叫。

## 回傳區段

| 欄位 | 用途 |
|---|---|
| `schema_version` | capability response 的版本，目前為 `1.0` |
| `mcp_server` | MCP package 版本、`stdio_to_tcp` transport 與 live control port |
| `runtime` | Isaac Sim 版本、adapter、adapter generation、active physics backend、stage 是否存在 |
| `extension` | `isaac.sim.mcp_extension` 版本與目前 command names/count |
| `extensions` | Camera、RTX LiDAR、Replicator、IRA、ROS 2、motion generation、Newton 等 extension 的 enabled state |
| `feature_flags` | named MCP 能力的實際支援狀態與限制原因 |
| `unsupported_arguments` | schema 已接受，但目前 handler/adapter 無法套用的參數 |
| `sensor_warmup` | Camera/LiDAR 是否需要暖機、cached sensor 數量與目前可判定狀態 |

## 狀態值

| 狀態 | 意義 |
|---|---|
| `supported` | 已有 named tool 與實作路徑 |
| `partial` | 僅完成部分 lifecycle 或操作 |
| `unsupported` | 目前沒有正式 named MCP 支援 |
| `accepted_not_applied` | 參數可送入 schema，但目前 adapter 不會套用 |
| `verified` | 已在目前 backend 完成既有實測 |
| `unverified` | 有程式路徑，但尚無目前 backend 的完整 live matrix |
| `enabled` / `disabled` | Kit extension manager 可確認的 runtime 狀態 |
| `unknown` | Kit extension manager 或 runtime 資訊尚不可讀；不得當成 enabled |

## 目前 6.0.1 必須注意的限制

- **多 GPU / PhysX 重點限制**：`/physics/cudaDevice=-1` 已在 Timeline `Stop` 重現 `PhysXGpu_64.dll` native crash。Windows launcher 會偵測當下唯一的 `display_active=Enabled` GPU 並解析成明確 ordinal；判定失敗才警告並 fallback 到 GPU 0。可由 `-PhysicsGpu` 或 `ISAAC_PHYSICS_GPU` 覆寫。此防護只針對 PhysX，renderer multi-GPU 設定不能替代它；Newton 尚未宣稱適用。
- managed artifact 共用 `artifact://managed/<opaque-id>` 契約與四個 named tools，預設 TTL 1 小時、單檔 256 MiB、總容量 512 MiB、單次 chunk 1 MiB；可用環境變數覆寫。契約見 [`ARTIFACT_TRANSPORT.md`](ARTIFACT_TRANSPORT.md)。
- `capture_image` 支援 `metadata|artifact|inline`；預設回受控 PNG artifact，inline 有 1 MiB 預設與 4 MiB hard cap。契約見 [`CAMERA_RGB.md`](CAMERA_RGB.md)。
- `capture_camera_output` 在 V6 支援七種 typed RTX output，預設回受控 `.npy` artifact；inline 傳 raw little-endian bytes，具有相同 1 MiB 預設與 4 MiB hard cap。契約見 [`CAMERA_OUTPUTS.md`](CAMERA_OUTPUTS.md)。
- `get_lidar_point_cloud` 支援 `metadata|artifact|inline`；預設回受控 `.npz` artifact。V6 必有 Cartesian `points`、range、azimuth、elevation，可用時另含 intensity 與 128-bit object ID；semantic ID 目前明確列為 unavailable。契約見 [`LIDAR_POINT_CLOUD.md`](LIDAR_POINT_CLOUD.md)。
- V6 `create_lidar` 支援 named preset，或以 FOV、角解析度、rotation rate 與 range 建立 generic RTX LiDAR；兩種模式不可混用。`get_lidar_config` 會從 USD Core schema 讀回有效值與 raw attributes。契約見 [`LIDAR_CONFIG.md`](LIDAR_CONFIG.md)。
- `delete_sensor` 會完整 teardown Camera/LiDAR runtime，刪除 prim，等待 Kit updates，再驗證 prim、RenderProduct、cache 與 LiDAR metadata 均不存在。timeline 必須處於 Pause 或 Stop；`delete_object` 遇到 managed sensor 會走相同流程。契約見 [`SENSOR_LIFECYCLE.md`](SENSOR_LIFECYCLE.md)。
- `set_physics_params` 支援 `gravity`；`time_step` 與 `gpu_enabled` 會明確拒絕。
- Isaac Sim 6.x Robot named tools 可讀 position、velocity、projected effort 與三種 target，並以 name/index subset 原子套用 position、velocity 或 effort；effort 必須每個 update 重送。V5 僅保留 position，IK 與 trajectory 尚未支援。契約見 [`ROBOT_JOINT_CONTROL.md`](ROBOT_JOINT_CONTROL.md)。
- ROS 2、完整 Replicator SDG 與完整 Action Graph lifecycle 尚無 named tools。
- Newton 只有實際通過 live matrix 的項目才能標為 verified。

## 呼叫範例

```text
get_capabilities()
```

client 應先檢查 `schema_version`，再依 `runtime.physics_backend`、`extensions` 與 `feature_flags` 決定後續操作。
遇到 `unknown`、`unsupported`、`accepted_not_applied` 或 `unverified` 時，應停止自動寫入並回報限制。

## Isaac Sim 6.0.1 live 驗證

2026-08-22 使用 `D:\Dev\isaacsim-mcp` extension 與 TCP `8766` 完成 read-only 驗證：

- stage 建立前：`get_capabilities` 成功，`stage_available=false`
- stage 建立後：`get_capabilities` 成功，`stage_available=true`
- runtime：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX
- command registry：46 commands，包含 `system.get_capabilities`
- enabled：MCP extension、core simulation manager、RTX sensors、Replicator Core、IRA Core、motion generation
- disabled：ROS 2 bridge、Newton
- sensor：Camera/LiDAR 尚未建立，因此 warm-up state 為 `not_created`
- 場景影響：沒有建立、修改或刪除 prim，沒有播放或 step simulation

2026-08-23 完成 Camera RGB live 驗證：

- scratch camera：`/World/MCP_Task_1_1_Camera`，read-back 成功
- runtime：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX
- frame：RGB `[48,64,3]`、`uint8`、timeline frame 91
- artifact：managed PNG path/handle、PNG SHA-256 與解碼後 pixel SHA-256 驗證一致
- inline：base64 PNG 可解碼，dimensions、dtype 與 hashes 一致
- limit：1-byte 上限回 `INLINE_SIZE_LIMIT_EXCEEDED`

2026-08-23 完成 Camera annotator 與 calibration live 驗證：

- scratch camera/target：`/World/MCP_Task_1_2_Camera`、`/World/MCP_Task_1_2_Target`
- runtime：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX
- outputs：depth、distance-to-image-plane、semantic/instance/instance-ID segmentation、normals、motion vectors 全數取得 frame
- contract：七種輸出的 `dtype`、`shape`、`units`、raw SHA-256 與 `.npy` artifact SHA-256 驗證通過
- read-back：已知 cube 的非零 depth/normals、semantic label 與 instance prim path 可在 annotator data/info 讀回
- calibration：`64x48` resolution、pinhole intrinsic、camera-to-world/world-to-camera、projection 與 units 驗證通過
- lifecycle：Play transition 明確 commit；Play 中不排程會觸發 Stop 的 fallback render；scratch prim 已清除

2026-08-23 完成 LiDAR point cloud live 驗證：

- scratch LiDAR/targets：`/World/MCP_Task_1_3_Lidar` 與四個 cardinal-direction cube，建立與 transform read-back 成功
- runtime：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX
- frame：134,880 points；Cartesian XYZ、range、azimuth、elevation、intensity、object-ID high/low 全數 row count 一致
- contract：dtype、shape、units、每個 raw field SHA-256 與 `.npz` artifact SHA-256 驗證通過
- coordinates：原始 spherical GMO 正確轉 Cartesian meters；frame=`sensor`、sensor timestamp/frame 與 pose `[0,0,1]` 可讀回
- object read-back：stable ID 成功解析至 `/World/MCP_Task_1_3_Target_YN`；semantic ID 目前明確 unavailable
- lifecycle：Play 暖機、capture、Stop 後 Kit/8766 仍存活；沒有新增 native dump；scratch prim 全數清除

2026-08-23 完成 LiDAR config live 驗證：

- generic A：horizontal/vertical FOV `120/20` 度、resolution `1/2` 度、`10 Hz`、`0.5–40 m`；read-back 一致，取得 33 points
- generic B：horizontal/vertical FOV `180/30` 度、resolution `0.5/5` 度、`20 Hz`、`1–80 m`；read-back 一致，取得 262 points
- validation：`100° / 3°` 無法整除時回 `LIDAR_HORIZONTAL_RESOLUTION_NOT_DIVISIBLE`，且沒有建立 prim
- runtime：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX；partial-FOV 使用 per-tick output，Play/Stop 與 scratch cleanup 通過

2026-08-23 完成共用 artifact transport live 驗證：

- registry：當次 53 extension commands；`get_artifact_info`、`read_artifact`、`delete_artifact`、`cleanup_artifacts` 均已註冊
- Camera：PNG 1,087 bytes；LiDAR：NPZ 1,248 bytes；兩者以 512-byte chunks 重組後，完整 SHA-256 與 producer metadata 一致
- guard：traversal handle 回 `INVALID_ARTIFACT_HANDLE`；1,025-byte request 在 1,024-byte 上限下回 `ARTIFACT_CHUNK_LIMIT_EXCEEDED`
- lifecycle：explicit delete、15 秒 TTL access expiry、expired cleanup、artifact root 與 scratch prim cleanup 全數通過

2026-08-23 完成 Sensor lifecycle live 驗證：

- registry：54 extension commands；`delete_sensor` 已註冊，`delete_object` 已具 sensor-aware routing
- 兩輪流程：相同 Camera/LiDAR prim path 依序 create、typed read、delete、再 create；Camera RGB `[48,64,3]`，LiDAR point count `2`
- teardown：每個 sensor 在刪除前各有一個 RenderProduct；runtime 使用 `_invalidate_sensor()`，annotator/writer/Hydra texture 全部釋放
- read-back：每次刪除等待 32 Kit updates；prim、LiDAR actual prim、RenderProduct、Camera/LiDAR cache 與 LiDAR authoring metadata 全部 absent
- recreate：第二輪建立成功，沒有重複 pipeline，`duplicate_pipeline_detected=false`
- runtime：PID 與 TCP `8766` 持續存活；log 無 teardown failure、invalid-prim access、`EXCEPTION_ACCESS_VIOLATION` 或 `PhysXGpu_64.dll` crash signature；scratch cleanup 通過

2026-08-24 完成 Robot joint state／command mode live 驗證：

- registry：56 extension commands；`get_joint_state`、`set_joint_command` 已註冊且 capability 為 supported
- fixture：`/World/MCP_Task_2_1_Robot` Franka，9 DOF；選定 `panda_joint1` 以 name subset 控制
- modes：position、velocity、effort requested target 都由 immediate read-back 在浮點容差內確認；physics updates 後 measured position、velocity、projected effort 均為有限值
- atomicity：不存在的 joint name 回 `JOINT_NOT_FOUND`、`applied=false`，命令前後三種 targets 完全一致
- lifecycle：Play 前 stale tensor wrapper 會重綁目前 SimulationView；cleanup 先 Stop 再刪 articulation，scratch prim read-back absent
- runtime：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX；Kit PID/TCP `8766` 存活，fixed physics GPU 對應 active display GPU，run-scoped log 無 warning/error，新增 native dump `0`

2026-08-23 完成多 GPU Timeline Stop 防護驗證：

- launcher 依當下主要顯示 GPU 選為 `/physics/cudaDevice=0`，來源明確回報為 `active display GPU`
- MCP Camera scratch 流程完成 Play、RGB capture 與 Stop
- Stop 後 Kit 內部完成 240 次 update，程序仍存活
- 新增 native dump：0；既有 crash signature：0
