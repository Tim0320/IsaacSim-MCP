# Protocol、版本與 migration

IsaacSim-MCP 同時有 package、response、capability 與部分子契約版本。client 必須分開判斷，不能只看 package `0.6.0` 就假設所有 runtime 能力可用。

## 版本層級

| 層級 | 目前版本 | 來源 | client 行為 |
|---|---:|---|---|
| MCP Server package | `0.6.0` | `isaac_mcp.__version__` | 與 extension manifest version 必須一致。 |
| Isaac Sim extension | `0.6.0` | `extension.toml` / `get_capabilities` | Server/extension rolling mismatch 時只允許 discovery/read-only 診斷。 |
| Response envelope | `1.0` | 每個 named tool 的 outer `schema_version` | 未知 major 應停止 write；同 major 新欄位必須忽略並保留。 |
| Capability data | `1.1` | `get_capabilities.data.capability_schema_version` | client 依 feature flags、extensions 與 backend matrix 選路。 |
| Backend matrix | `1.0` | `get_capabilities.data.backend_matrix.schema_version` | `null` 是 untested；`false` 是 unsupported；兩者都 fail closed。 |
| Artifact metadata | 目前契約 `1.x` | managed artifact metadata | 以 handle、size、MIME、SHA-256、TTL 與 chunk bounds 驗證。 |

版本改動規則：

- major 改變代表既有 parser 或 write semantics 可能不相容。
- minor 改變只能新增 optional 欄位、status/code 或能力描述；client 應忽略未知欄位。
- `status`、`code`、units、apply/read-back state 或安全預設的語意改變，必須記錄 migration，不能只改文字說明。
- package 與 extension version 必須同步；測試會檢查兩者及 manifest。

## 0.6.0 client 必須遵守的 response 契約

所有 128 個 named tools 回 JSON text。解析後 outer object 固定含：

```json
{
  "schema_version": "1.0",
  "status": "success",
  "code": "OK",
  "message": "Command completed",
  "data": {},
  "warnings": [],
  "command_id": "client-or-generated-id",
  "timing": {},
  "artifacts": [],
  "readback": null
}
```

client 必須以 `status` 與 `code` 判斷結果。`message` 只供人閱讀。`success` 且 `readback=null` 或 `data.command.readback_state=not_reported` 不能宣稱 write postcondition 已驗證。

## 從舊 42-tool client 升級

1. 啟動後先呼叫 `get_capabilities`，不要使用硬編碼 tool count 或 Isaac Sim major 推測能力。
2. 將舊 `{status, result}` parser 改成讀 outer schema `1.0` 的 `data`。Server 在 rolling upgrade 期間仍會正規化 legacy extension response，但 client 不應長期依賴此轉換。
3. 把 `partial`、`unsupported`、`timeout`、`cancelled` 當成獨立 non-success state。
4. 大型 Camera/LiDAR 資料改走 managed artifact。驗證 metadata、size、SHA-256，並用 bounded chunks 下載。`inline` 受硬上限保護。
5. Camera `capture_image` 預設回 artifact/metadata；不能再假設只有 output path 或 shape。
6. LiDAR point cloud 使用 typed NPZ fields、units 與 per-field hash；不能把任意 list 當成完整點雲契約。
7. write retry 傳相同 `idempotency_key`。相同 key 配不同 payload 會回 `IDEMPOTENCY_KEY_CONFLICT`。
8. long-running asset/sensor、Motion、SDG 工作改用 `start_job`、`get_job_status`、`cancel_job` 或對應 provider lifecycle；禁止無限等待 MCP worker。
9. 新增的 Stage/ROS 2/Replicator/Human/Graph writes 多數預設 `preview=true`。client 必須明確 `preview=false` 才 apply，並讀回 exact postcondition。
10. `execute_script` 與 `reload_script` 受 allowed roots、timeout、output/source bytes 與 background policy 限制。named tools 優先。

## Server 與 extension rolling upgrade

建議順序：

1. 停止 write traffic，等 active jobs 進入 terminal state。
2. 記錄 `get_capabilities`、package/extension version、backend、command count 與 Stage 狀態。
3. 更新同一 checkout 的 MCP Server 與 Isaac Sim extension。
4. 重新啟動 Isaac Sim，避免 hot reload 留下舊 registry、sensor wrapper、job 或 replay ledger。
5. 先做 `get_capabilities` 與 `get_scene_info` read-only 驗證。
6. 在 exact scratch stage 執行專用 verifier；確認 cleanup、Kit/TCP、log 與 native dump。

不要在 Server 與 extension version 不一致時執行 write。Idempotency ledger、runtime-only graph enabled state、job registry 與 script audit 都不會跨 Kit restart 保存。

## Isaac Sim / backend 相容性

| Runtime | 支援狀態 | 邊界 |
|---|---|---|
| Isaac Sim `6.0.1` + PhysX | 主要、live-verified | 仍需逐功能 prerequisites、scratch 與 read-back。 |
| Isaac Sim `6.0.1` + Newton | fail-closed matrix | 目前沒有 Newton row 宣稱 live supported；`untested` 與 `unsupported` 分開。 |
| Isaac Sim `5.1.x` | legacy adapter、非目前 release gate | 部分基本 API 可載入；128-tool 6.0.1 live 報告不適用。 |
| 其他 6.x / 未知版本 | 未驗證 | 不可因 adapter major=6 就沿用 6.0.1 live 結論。 |

完整逐功能狀態讀 [`CAPABILITIES.md`](CAPABILITIES.md) 與 [`BACKEND_CAPABILITY_MATRIX.md`](BACKEND_CAPABILITY_MATRIX.md)。

## Breaking-change checklist

任何 release 若改動以下項目，必須更新 package/extension version、Changelog、README、response/schema 文件、128-tool artifact 與 migration：

- tool name、required parameter、default、units 或 return shape；
- outer response field/status/code；
- artifact format、hash、TTL/chunk/capacity；
- preview/apply、idempotency、rollback 或 read-back semantics；
- backend/extension prerequisite；
- script/job/diagnostic security bounds。
