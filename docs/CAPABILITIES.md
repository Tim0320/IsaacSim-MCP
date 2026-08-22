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

- `capture_image` 支援 `metadata|artifact|inline`；預設回受控 PNG artifact，inline 有 1 MiB 預設與 4 MiB hard cap。契約見 [`CAMERA_RGB.md`](CAMERA_RGB.md)。
- `get_lidar_point_cloud` 目前只回 `point_count`，尚未傳回 decoded XYZ points。
- V6 `create_lidar(config=...)` 接受參數，但尚未 author 對應 RTX LiDAR schema attributes。
- `set_physics_params` 支援 `gravity`；`time_step` 與 `gpu_enabled` 會明確拒絕。
- Robot named tools 支援 joint position；velocity、effort、IK 與 trajectory 尚未支援。
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
