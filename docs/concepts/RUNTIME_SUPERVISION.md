# Isaac Sim runtime supervision 與 crash recovery

這份文件定義 Isaac Sim 程序、MCP Server 與 Extension socket 的 ownership。目標是在保留既有 stdio／Streamable HTTP transport 的前提下，讓異常退出可以 bounded restart，並讓 Agent 在 TCP `8766` 不可用時取得可判斷的錯誤資訊。

## 程序架構

```text
Codex / Claude / ChatGPT
        ↓ stdio 或 Streamable HTTP
Python MCP Server
        ↓ JSON over TCP 127.0.0.1:8766
Isaac Sim Extension
        ↓
Isaac Sim

run_isaac_sim_supervised.ps1
        ↓ owns / monitors
Isaac Sim process
        ↓ atomic state
runtime-state.json
        ↑ read-only
Python MCP Server / get_runtime_status
```

MCP Server 不擁有 Isaac Sim 程序。MCP client 可以同時存在多個 stdio／HTTP server process；只有一個 supervisor 可以擁有指定 port 的 Isaac Sim。Supervisor 啟動前會送出 `system.get_capabilities` health probe。健康 runtime 或已開啟但無回應的 port 都會阻止第二次 launch。

## 啟動

```powershell
# Terminal 1：啟動並監控 Isaac Sim 6.0.1
$env:ISAACSIM_ROOT = "C:\isaacsim"
.\scripts\run_isaac_sim_supervised.ps1

# Terminal 2：原本 stdio MCP 使用方式保持不變
.\.venv\Scripts\python.exe -m isaac_mcp.server
```

One-shot launcher 仍可使用：

```powershell
.\scripts\run_isaac_sim.ps1
```

One-shot 模式不建立 process ownership，也不保證 crash 後自動重啟。MCP Server 會在外部重新啟動 Isaac Sim 且 Extension 恢復後重新連線。

## Restart policy

| 條件 | 預設行為 |
|---|---|
| exit code `0` | 正常關閉，supervisor 結束，不重啟。 |
| 非零 exit code | 視為異常退出，進入 exponential backoff。 |
| restart budget | 300 秒內最多 3 次 restart。 |
| backoff | 從 2 秒開始倍增，單次最多 60 秒。 |
| 程序仍存活但 protocol health 失敗 | 回報 `unresponsive`，不 kill、不啟動第二份 runtime。 |
| 啟動前 port 已被占用 | 回報 external runtime 狀態並拒絕 launch。 |
| Ctrl+C 中斷 supervisor | 回報 `supervisor_interrupted`；不宣稱仍持有 runtime。 |

可調整 launcher 參數：

```powershell
.\scripts\run_isaac_sim_supervised.ps1 `
    -MaxRestarts 5 `
    -RestartWindowSeconds 600 `
    -BackoffSeconds 3 `
    -PhysicsGpu 0
```

`run_isaac_sim.ps1` 的 Isaac Sim 6.0.1 version gate、Extension arguments 與 explicit Physics GPU crash guard 全部保留。

## Shared runtime state

預設狀態檔：

```text
%LOCALAPPDATA%\IsaacSim-MCP\runtime-state.json
```

寫入採用 temporary file 加 atomic replace。檔案最大讀取限制為 64 KiB，只保存 bounded lifecycle evidence：

- `state`、`supervised`、`supervisor_pid`、`runtime_pid`
- `attempt`、`restart_count`、`max_restarts`、`next_restart_at`
- `last_crash.occurred_at`、`exit_code`、`launch_error`、`was_ready`
- protocol health 的 `responding`、`port_open`、`checked_at`、bounded `error`
- `availability_code` 與 `recommended_actions`

狀態檔不保存 environment、MCP request params、script source、API key 或任意 Kit log body。需要自訂位置時，supervisor 與 MCP Server 必須使用相同設定：

```powershell
$env:ISAAC_MCP_RUNTIME_STATE_FILE = "D:\runtime\isaacsim-mcp-state.json"
```

## MCP diagnostic contract

`get_runtime_status` 是 MCP-local read-only tool，不需要 Extension socket。它會合併 atomic supervisor state 與即時 `system.get_capabilities` protocol probe：

| `availability_code` | 意義 | Agent 行動 |
|---|---|---|
| `ISAAC_RUNTIME_READY` | Protocol health 成功。 | 先讀目前 Stage/runtime state，再繼續操作。 |
| `ISAAC_RUNTIME_RECOVERING` | Supervisor 正在 starting、backoff 或 restarting。 | Bounded wait，重查 `get_runtime_status`；只允許 read retry。 |
| `ISAAC_RUNTIME_CRASHED` | 異常退出且 restart budget 已用盡。 | 讀取 `last_crash`，修復原因後重新啟動 supervisor。 |
| `ISAAC_RUNTIME_UNAVAILABLE` | Runtime 未啟動，或程序／port 無法通過 protocol health。 | 依 `state` 決定啟動 supervisor或檢查既有無回應程序。 |

所有 Extension-backed tools 都保留相同 crash envelope。舊 tool 內部的 generic exception handler 不會再把這些資訊降級為 `COMMAND_FAILED`。

## Command delivery 與 no-replay

Supervisor 只恢復程序，不重送造成 crash 或 connection loss 的 command。

- 在 send 前無法連線：command 尚未送到 Extension。
- 在 send 後 connection loss：`data.runtime.command_delivery=unknown`。
- Read 可以在 runtime ready 後 bounded retry。
- Write 必須先做 operation-specific read-back。
- 只有 contract 明確允許時，才能使用原本相同的 `idempotency_key` 重送。
- 不可改用新的 idempotency key 猜測重送；可能造成重複建立、刪除或控制。

Stage 的未儲存狀態由 Isaac Sim process 持有。程序重啟不會自動還原 anonymous／未儲存 Stage；場景復原需要另外使用已儲存 USD 或明確 checkpoint policy。

## 驗證邊界

- Offline contracts：`tests/test_runtime_status.py`、`tests/test_runtime_supervisor.py`、`tests/test_connection.py`。
- Windows launcher integration：`tests/test_run_isaac_sim_supervised_windows.py`。
- Health readiness 使用 protocol response；port-open 只代表 socket 已被占用。
- 測試不會故意 crash 使用者的 Isaac Sim，也不會 kill alive-but-unresponsive Kit。
- 真實 native crash root cause 仍需結合 Isaac Sim console、run-scoped Kit log 與 native dump；runtime state 只提供 bounded process／transport evidence。

錯誤分支與 Agent recovery matrix 見 [Error Codes and Agent Recovery](../reference/ERROR_CODES.md)，response 欄位見 [MCP response schema](../reference/RESPONSE_SCHEMA.md)。
