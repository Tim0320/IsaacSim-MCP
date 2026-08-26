# `get_capabilities` schema 1.1

`get_capabilities` 是 read-only named tool，用來確認目前 MCP server 與 live Isaac Sim extension 真正能做什麼。
它不需要 USD stage 已完成建立，因此可作為 MCP 工作流程的第一個呼叫。

## 回傳區段

| 欄位 | 用途 |
|---|---|
| outer `schema_version` | 共用 response envelope 版本，目前為 `1.0` |
| `capability_schema_version` | capability data 版本，目前為 `1.1` |
| `mcp_server` | MCP package 版本、`stdio_to_tcp` transport 與 live control port |
| `runtime` | Isaac Sim 版本、adapter、adapter generation、active physics backend、stage 是否存在 |
| `extension` | `isaac.sim.mcp_extension` 版本與目前 command names/count |
| `extensions` | Camera、RTX LiDAR、Replicator、IRA、ROS 2、motion generation、Newton 等 extension 的 enabled state |
| `backend_matrix` | adapter-owned PhysX/Newton 逐功能支援、驗證與 fail-closed 狀態 |
| `feature_flags` | named MCP 能力的實際支援狀態與限制原因 |
| `unsupported_arguments` | schema 已接受，但目前 handler/adapter 無法套用的參數 |
| `sensor_warmup` | Camera/LiDAR 是否需要暖機、cached sensor 數量與目前可判定狀態 |

## 狀態值

| 狀態 | 意義 |
|---|---|
| `supported` | 已有 named tool 與實作路徑 |
| `partial` | 僅完成部分 lifecycle 或操作 |
| `unsupported` | 目前沒有正式 named MCP 支援 |
| `untested` | 有共用或候選路徑，但目前 backend 尚未通過 live matrix；不得自動執行 |
| `accepted_not_applied` | 參數可送入 schema，但目前 adapter 不會套用 |
| `verified` | 已在目前 backend 完成既有實測 |
| `unverified` | 有程式路徑，但尚無目前 backend 的完整 live matrix |
| `enabled` / `disabled` | Kit extension manager 可確認的 runtime 狀態 |
| `unknown` | Kit extension manager 或 runtime 資訊尚不可讀；不得當成 enabled |

## 目前 6.0.1 必須注意的限制

- **多 GPU / PhysX 重點限制**：`/physics/cudaDevice=-1` 已在 Timeline `Stop` 重現 `PhysXGpu_64.dll` native crash。Windows launcher 會偵測當下唯一的 `display_active=Enabled` GPU 並解析成明確 ordinal；判定失敗才警告並 fallback 到 GPU 0。可由 `-PhysicsGpu` 或 `ISAAC_PHYSICS_GPU` 覆寫。此防護只針對 PhysX，renderer multi-GPU 設定不能替代它；Newton 尚未宣稱適用。
- managed artifact 共用 `artifact://managed/<opaque-id>` 契約與四個 named tools，預設 TTL 1 小時、單檔 256 MiB、總容量 512 MiB、單次 chunk 1 MiB；可用環境變數覆寫。契約見 [`ARTIFACT_TRANSPORT.md`](../concepts/ARTIFACT_TRANSPORT.md)。
- `capture_image` 支援 `metadata|artifact|inline`；預設回受控 PNG artifact，inline 有 1 MiB 預設與 4 MiB hard cap。契約見 [`CAMERA_RGB.md`](CAMERA_RGB.md)。
- `capture_camera_output` 在 V6 支援七種 typed RTX output，預設回受控 `.npy` artifact；inline 傳 raw little-endian bytes，具有相同 1 MiB 預設與 4 MiB hard cap。契約見 [`CAMERA_OUTPUTS.md`](CAMERA_OUTPUTS.md)。
- `get_lidar_point_cloud` 支援 `metadata|artifact|inline`；預設回受控 `.npz` artifact。V6 必有 Cartesian `points`、range、azimuth、elevation，可用時另含 intensity 與 128-bit object ID；semantic ID 目前明確列為 unavailable。契約見 [`LIDAR_POINT_CLOUD.md`](LIDAR_POINT_CLOUD.md)。
- V6 `create_lidar` 支援 named preset，或以 FOV、角解析度、rotation rate 與 range 建立 generic RTX LiDAR；兩種模式不可混用。`get_lidar_config` 會從 USD Core schema 讀回有效值與 raw attributes。契約見 [`LIDAR_CONFIG.md`](LIDAR_CONFIG.md)。
- `delete_sensor` 會完整 teardown Camera/LiDAR runtime，刪除 prim，等待 Kit updates，再驗證 prim、RenderProduct、cache 與 LiDAR metadata 均不存在。timeline 必須處於 Pause 或 Stop；`delete_object` 遇到 managed sensor 會走相同流程。契約見 [`SENSOR_LIFECYCLE.md`](SENSOR_LIFECYCLE.md)。
- V6 PhysX `set_physics_params` 支援 `gravity`、整數 steps/sec 對應的 `time_step`，以及 GPU dynamics + GPU/MBP broadphase mapping。timeline 必須 stopped，成功需 USD、runtime wrapper、SimulationManager、Stage time codes 與 min-frame-rate read-back 一致；V5/Newton 仍明確 unsupported。契約見 [`PHYSICS_PARAMS.md`](PHYSICS_PARAMS.md)。
- Stage composition 提供 12 個 named tools。Lifecycle 預設 preview 並受 scratch root 防護；subLayer、reference/payload、variant、`UsdSemantics.LabelsAPI`、typed attribute 與最多 100 項 batch 都要求 stopped timeline、read-back 及 rollback。契約見 [`STAGE_COMPOSITION.md`](STAGE_COMPOSITION.md)。
- OmniGraph lifecycle 提供 12 個 named tools：create/edit/list/get/delete、connect/disconnect、runtime-only enabled state、runtime status、exact ScriptNode configure/reload 與 explicit evaluation。新增寫入預設 preview；所有 graph 寫入要求 stopped timeline，只有 `set_action_graph_enabled(enabled=false)` 可在 playing 時緊急停用。各操作具有 read-back 與 operation-specific rollback，刪除使用可 undo 的 `DeletePrimsCommand`。專用 live verifier 已通過，契約見 [`OMNIGRAPH_LIFECYCLE.md`](OMNIGRAPH_LIFECYCLE.md)。
- Isaac Sim 6.x Robot named tools 可讀 position、velocity、projected effort 與三種 target，並以 name/index subset 原子套用 position、velocity 或 effort；effort 必須每個 update 重送。Drive config 可在 stopped timeline 原子寫入 gains、max force/velocity 與 force/acceleration type，並 rollback 失敗寫入。V5 不支援 typed drive setter；Newton 的 max velocity 明確不支援，其餘 drive 欄位維持 unverified。契約見 [`ROBOT_JOINT_CONTROL.md`](ROBOT_JOINT_CONTROL.md) 與 [`ROBOT_JOINT_DRIVE_CONFIG.md`](ROBOT_JOINT_DRIVE_CONFIG.md)。
- V6 motion tools 依賴 `isaacsim.robot_motion.motion_generation`。Lula IK 不做 collision avoidance；只有 `planner=rrt` 可回報 Lula world view 的 collision result，`planner=cspace` 會明確標示 unchecked。execution 走 Kit update callback，不阻塞 MCP worker，並具有 pause/resume、cancel、deadline timeout。契約見 [`MOTION_CONTROL.md`](MOTION_CONTROL.md)。
- V6 gripper/mobile-base tools 必須使用 explicit controller profile，並以 exact joint name/type fail closed。Jetbot differential 使用明確 wheel geometry；Kaya holonomic geometry 從 USD 讀取，且依賴 `isaacsim.robot.experimental.wheeled_robots`。非零 base command 要求 timeline playing，target 會持續到 `stop_mobile_base` 或其他 controller 覆寫。契約見 [`CONTROLLER_PROFILES.md`](CONTROLLER_PROFILES.md)。
- ROS 2 已有 8 個 guarded named workflows；完整 Replicator SDG 尚無 named tools。
- PhysX/Newton 分流、`null`/`false` 支援語意與 21 項 matrix 見 [`BACKEND_CAPABILITY_MATRIX.md`](BACKEND_CAPABILITY_MATRIX.md)。Newton 只有實際通過 live matrix 的項目才能標為 `supported/verified`。

## 呼叫範例

```text
get_capabilities()
```

client 應先檢查 outer `schema_version` 與 `capability_schema_version`，再依 `runtime.physics_backend`、`backend_matrix`、`extensions` 與 `feature_flags` 決定後續操作。
遇到 `unknown`、`untested`、`unsupported`、`accepted_not_applied` 或 `unverified` 時，應停止自動寫入並回報限制。


> Dated live acceptance records are preserved in [Capability verification history](../research/CAPABILITY_HISTORY.md). They are not current runtime authority.
