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
- V6 PhysX `set_physics_params` 支援 `gravity`、整數 steps/sec 對應的 `time_step`，以及 GPU dynamics + GPU/MBP broadphase mapping。timeline 必須 stopped，成功需 USD、runtime wrapper、SimulationManager、Stage time codes 與 min-frame-rate read-back 一致；V5/Newton 仍明確 unsupported。契約見 [`PHYSICS_PARAMS.md`](PHYSICS_PARAMS.md)。
- Isaac Sim 6.x Robot named tools 可讀 position、velocity、projected effort 與三種 target，並以 name/index subset 原子套用 position、velocity 或 effort；effort 必須每個 update 重送。Drive config 可在 stopped timeline 原子寫入 gains、max force/velocity 與 force/acceleration type，並 rollback 失敗寫入。V5 不支援 typed drive setter；Newton 的 max velocity 明確不支援，其餘 drive 欄位維持 unverified。契約見 [`ROBOT_JOINT_CONTROL.md`](ROBOT_JOINT_CONTROL.md) 與 [`ROBOT_JOINT_DRIVE_CONFIG.md`](ROBOT_JOINT_DRIVE_CONFIG.md)。
- V6 motion tools 依賴 `isaacsim.robot_motion.motion_generation`。Lula IK 不做 collision avoidance；只有 `planner=rrt` 可回報 Lula world view 的 collision result，`planner=cspace` 會明確標示 unchecked。execution 走 Kit update callback，不阻塞 MCP worker，並具有 pause/resume、cancel、deadline timeout。契約見 [`MOTION_CONTROL.md`](MOTION_CONTROL.md)。
- V6 gripper/mobile-base tools 必須使用 explicit controller profile，並以 exact joint name/type fail closed。Jetbot differential 使用明確 wheel geometry；Kaya holonomic geometry 從 USD 讀取，且依賴 `isaacsim.robot.experimental.wheeled_robots`。非零 base command 要求 timeline playing，target 會持續到 `stop_mobile_base` 或其他 controller 覆寫。契約見 [`CONTROLLER_PROFILES.md`](CONTROLLER_PROFILES.md)。
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

2026-08-24 完成 Robot joint drive config live 驗證：

- registry：57 extension commands；`set_joint_drive_config` 已註冊，PhysX 五個欄位均為 supported/verified
- fixture：`/World/MCP_Task_2_2_Robot` Franka，9 DOF；選定 `panda_joint1` 以 name subset 寫入
- read-back：stiffness `20626.48047`、damping `4125.29639`、max force `78.300003`、max velocity `1.5`、drive type `acceleration`，與 requested 值符合 float32 容差
- atomicity：負值、未知 joint、active timeline 均回穩定拒絕且 `applied=false`，五欄 snapshot 不變
- backend：`max_velocity` 透過 `PhysxJointAPI`，Newton 明確 unsupported；Newton 其餘 USD DriveAPI 欄位維持 unverified
- lifecycle：timeline stopped、scratch prim absent、Kit PID/TCP `8766` 存活、GPU 0 為唯一 active display GPU、error-like log `0`、新增 native dump `0`

2026-08-24 完成 Motion control scratch live 驗收：

- registry：68 extension commands；motion generation `8.2.9` enabled，五個 motion commands 已註冊
- fixture：`/World/MCP_Task_2_3_Robot` Franka，explicit seven-joint planning start；scratch guard 在任何寫入前通過，最後只清除 verifier 自建 robot 與 physics fixtures
- IK：position error `7.363885225415161e-7 m`；warm start 與 seed `17` 的兩次結果完全相同；collision 明確 unchecked
- RRT：path found、collision checked/path_valid；目前 scene obstacle count 0、`scene_obstacles_included=false`，不得宣稱整個 Stage collision-free
- lifecycle：queued/paused → running → completed，另通過 cancel 與 `timeout_ms=1` terminal timeout；execute 立即回 `non_blocking=true`
- lifecycle gate：timeline stopped，2.3/2.4 robot 與 `/World/groundPlane`、`/World/PhysicsScene` 全 absent；Kit PID `29916`／TCP `8766` 存活，當次啟動 log 關鍵錯誤 `0`，新增 native dump `0`

2026-08-24 完成 Controller profiles scratch live 驗收：

- registry：68 extension commands；六個 controller named tools 已註冊
- extension：`isaacsim.robot.experimental.wheeled_robots` enabled，version `0.2.11`
- profiles：Franka parallel gripper、NVIDIA Jetbot differential、NVIDIA Kaya holonomic 三組 explicit profiles 可讀回
- gripper：Franka total width `0.08/0.03/0.0 m` 的 finger targets 分別為 `[0.04,0.04]`、`[0.015,0.015]`、`[0,0]`；錯誤 profile 回 `CONTROLLER_PROFILE_MISMATCH` 且 command targets 不變
- mobile base：Jetbot targets `[2.9583333,3.7083333]`、Kaya targets `[-9.304024,-6.6114283,-9.497344] rad/s`，兩者 measured velocities 均為有限值；stop 後全部 profiled wheel targets 讀回零
- lifecycle：clean restart 後依序完成 2.4、2.3；scratch fixtures/physics prim 全 absent、timeline stopped、Kit PID/TCP 存活、當次 log 無 GPU/device-lost/PhysX crash signature、新增 native dump `0`
- 歷史警示：舊長時間 session 曾因錯誤 device allocation 後出現 RTX CUDA external-memory failures、GPU page fault 與 `ERROR_DEVICE_LOST`，該 session 未納入驗收；Warp arrays 現在固定跟隨 Articulation physics device

2026-08-24 完成 Physics parameters scratch live 驗收：

- runtime：Isaac Sim `6.0.1-rc.7`、V6 PhysX、68 commands；launcher `/physics/cudaDevice=0` 對應唯一 display-active GPU
- mapping：gravity `[0,0,-3.72]`；120 Hz time step；GPU dynamics + GPU broadphase，以及 GPU dynamics off + MBP broadphase均由 USD/runtime 讀回
- timing：初始化 warm-up 後，12 個 stopped physics steps 的 clock 精確增加 `0.1 s`
- atomicity：`0.007 s` 無法對應整數 steps/sec 時回 `INVALID_PHYSICS_PARAMS`；playing timeline 回 `TIMELINE_NOT_STOPPED`；兩者完整 snapshot 不變
- lifecycle：修正 `_ensure_physics_world()` 原本固定重設 60 Hz；verifier 以 timeline state postcondition 等待 queued Stop，最後還原 PhysicsScene attrs、Stage `60 Hz`、min-frame-rate `30` 與 default scene `None`
- health：Kit PID `38160`／TCP `8766` 存活，新增 native dump `0`；Stop 造成四筆已知 tensor SimulationView invalidation warning，沒有 CUDA/device-lost/native crash signature

2026-08-23 完成多 GPU Timeline Stop 防護驗證：

- launcher 依當下主要顯示 GPU 選為 `/physics/cudaDevice=0`，來源明確回報為 `active display GPU`
- MCP Camera scratch 流程完成 Play、RGB capture 與 Stop
- Stop 後 Kit 內部完成 240 次 update，程序仍存活
- 新增 native dump：0；既有 crash signature：0
