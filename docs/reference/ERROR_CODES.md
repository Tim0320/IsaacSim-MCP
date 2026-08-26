# Error Codes and Agent Recovery

這份文件集中定義 Agent 收到 non-success response 後可以採取的恢復動作。`status` 表示結果類別，`code` 才是程式分支依據；不得用 `message` 字串判斷控制流程。

## 恢復規則

1. 保留原始 `command_id`、`code`、`status`、`readback`、`artifacts` 與 warnings。
2. 先判斷 operation 是 read 或 write。Read 可以 bounded retry；write 只有在 response 明確表示尚未 apply，或使用相同 `idempotency_key` 且 contract 允許 replay 時才能重送。
3. `timeout`、connection loss、oversized response 與 internal failure 都可能發生在 apply 之後。這些情況先 read-back，不得用新的 idempotency key 盲目重送 write。
4. `unsupported` 與 capability mismatch 先呼叫 `get_capabilities`。Capability 未明確回 `supported` 時 fail closed。
5. ownership、policy 與 timeline guard 不得由 `execute_script` 繞過。

## Action matrix

`Retry` 指原封不動重送同一 request；`Do not replay` 指 Agent 不可在沒有 read-back 或 idempotency 保護下自動重送 write。

| Code 或 family | 意義 | Retry | Reconnect | Query capability | Fix request/state | Do not replay write |
|---|---|---:|---:|---:|---:|---:|
| `STAGE_NOT_READY` | Extension 已啟動，但 USD Stage 尚未可用；handler 尚未 apply。 | bounded | 否 | 可選 | 等待 Stage | 否 |
| `TIMELINE_NOT_STOPPED` | operation 要求 stopped timeline。 | 否 | 否 | 否 | Stop 並確認 state | 是 |
| `TIMELINE_STATE_UNAVAILABLE` | 無法證明 timeline state，已 fail closed。 | bounded read | 可選 | 否 | 恢復 runtime state | 是 |
| `*_UNSUPPORTED`、status `unsupported` | 目前 adapter、backend、extension 或 argument 不支援。 | 否 | 否 | 是 | 改 backend/tool/request | 是 |
| `*_NOT_OWNED`、`*_OWNERSHIP_MISMATCH` | 目標不屬於 MCP-owned namespace，或 marker 不一致。 | 否 | 否 | 可選 | 改用 owned resource | 是 |
| `IDEMPOTENCY_KEY_CONFLICT` | 相同 key 已綁定不同 command type 或 canonical params；本次未 apply。 | 否 | 否 | 否 | 查原 command/read-back；新操作使用新 key | 是 |
| `REQUEST_TOO_LARGE` | Request 超過 transport 上限，extension 不派送。 | 否 | 否 | 否 | 縮小 request 或改 artifact/chunk | 否 |
| `RESPONSE_TOO_LARGE` | 原始 response 超限並被 bounded envelope 取代；operation 可能已 apply。 | 否 | 否 | 可選 | 改 bounded query/artifact | 是 |
| `INLINE_SIZE_LIMIT_EXCEEDED` | Camera/LiDAR inline payload 超過 caller limit。 | 否 | 否 | 可選 | 改 `artifact` 或 `chunk` mode | 否 |
| `*_FRAME_NOT_READY` | Sensor 已存在，但本 frame 尚無有效資料。 | bounded | 否 | 可選 | render/update 後再讀 | 不適用 |
| `INVALID_*`、`*_REQUIRED` | Input schema、path、metadata 或參數無效。 | 否 | 否 | 可選 | 修正 request | 是 |
| `*_NOT_FOUND` | 目標不存在，或 runtime view 尚未建立。 | 否 | 否 | 可選 | 重新 discover/list，修正 path | 是 |
| `UNKNOWN_COMMAND` | Active extension 沒有該 command；常見於 client/extension version drift。 | 否 | 可選 | 是 | 對齊版本或選現有 tool | 是 |
| `TIMEOUT`、`*_TIMEOUT` | Deadline 到期；native Kit call 可能已 apply 後才返回。 | read only | 可選 | 可選 | 查 job/status/read-back | 是 |
| `CANCELLED`、`*_CANCELLED` | Cancel 已接受或工作已進 terminal state。 | 否 | 否 | 否 | 查 terminal status/read-back | 是 |
| `*_ROLLED_BACK` | Apply 失敗但 rollback read-back 成功。 | 否 | 否 | 可選 | 修正 root cause | 是 |
| `*_ROLLBACK_FAILED` | Apply 與 rollback 都未能完成，state 不可信。 | 否 | 可選 | 可選 | 停止自動操作並要求人工檢查 | 是 |
| `INTERNAL_ERROR`、`SOCKET_DISPATCH_ERROR`、`MCP_TOOL_ERROR` | 未分類的 server/runtime failure。 | read only | 是 | 可選 | 收集 diagnostics 與 read-back | 是 |

## 提案名稱與目前 contract 的差異

- Timeline guard 的實際 stable code 是 `TIMELINE_NOT_STOPPED`；目前沒有 `TIMELINE_MUST_BE_STOPPED`。
- Backend support 由 `get_capabilities.backend_matrix` 與各 domain 的 `*_UNSUPPORTED` code 表達；目前沒有通用 `BACKEND_UNSUPPORTED`。
- Ownership 使用 `HUMAN_NOT_OWNED`、`ROS2_WORKFLOW_NOT_OWNED` 等 domain-specific code；目前沒有通用 `RESOURCE_NOT_OWNED`。
- `CONNECTION_LOST` 目前是 MCP client transport condition，尚未保證出現在 response envelope。連線中斷時可 reconnect，但 read 才能直接重送；write 必須先 read-back，或以原本相同的 `idempotency_key` 重送。

Agent 不得把尚未存在的 umbrella name 當成 wire contract。未識別的 code 一律保留原 response、fail closed，並依 `status` 採最保守的 read-back／diagnostics 路徑。

## 建議決策順序

```text
non-success response
├─ invalid / required / not found → 修正 request 或重新 discover
├─ stage / timeline prerequisite → 修正 runtime state，再建立新 attempt
├─ unsupported → get_capabilities，選 supported route
├─ ownership / policy denied → 停止，不繞過 guard
├─ frame not ready → bounded read retry
├─ timeout / connection / internal / oversized response
│  └─ write: read-back 或查 job；read: reconnect 後 bounded retry
└─ rollback failed / unknown code → 停止自動 write，保留 evidence
```

## Authority

- Envelope 欄位與 `status` 定義：[Response schema](RESPONSE_SCHEMA.md)
- Runtime/backend support：[Capabilities](CAPABILITIES.md) 與 [Backend capability matrix](BACKEND_CAPABILITY_MATRIX.md)
- Request/response limits：[Jobs and diagnostics](../concepts/JOB_DIAGNOSTICS.md)
- Idempotency 與 replay：[Command governance](../concepts/COMMAND_GOVERNANCE.md)

Exact code 仍由 active source 與 contract tests 決定。新增或重新命名 stable code 時，必須同步 handler/transport tests 與本頁；historical research report 不能覆蓋目前 source。
