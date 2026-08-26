# Job lifecycle、transport limits 與 command diagnostics

Task 5.3/5.4 為 Isaac Sim 6.0.1 live control 提供共用的 bounded job 與診斷契約。此層不取代既有 motion/SDG provider，而是讓 client 使用一致的 status/cancel 入口，並讓 asset/sensor 長操作可先取得 job ID。

## Named tools

- `start_job(command_type, params, deadline_ms)`：允許 `assets.import_urdf`、`assets.load_usd`、`assets.spawn_nvidia`、`sensors.capture_image`、`sensors.capture_camera_output`、`sensors.get_point_cloud`。
- `get_job_status(job_id)`：查詢 managed、`motion-*` 或 `sdg-*` job；只讀 retained result，不重新執行。
- `cancel_job(job_id)`：managed job 使用 asyncio cooperative cancellation；motion/SDG 委派既有 provider 的安全取消點。
- `list_jobs(count, include_terminal)`：最多保留 64 筆 managed jobs；滿額時只驅逐最舊 terminal job，不會驅逐 active job。

Managed lifecycle 為 `queued → running → succeeded|failed|cancelled|timed_out`。回傳包含 progress、created/started/finished/deadline timestamp、remaining time、result 與 artifact handles。`deadline_ms` 為 1..300000；Python awaitable 可被 deadline/cancel 中止，native Kit call 只能在控制權回到 Python 後進入終態，不能宣稱為強制 preemption。

Client 送出 `start_job` 後可立刻斷線；job 由 Kit runtime 持有，重連後用同一 ID 查詢。若 start response 遺失，應以相同 `idempotency_key` 重送，dispatcher replay ledger 會回原結果，不會建立第二個 job。

## Transport bounds

| limit | default | environment override |
|---|---:|---|
| request | 1 MiB | `ISAAC_MCP_MAX_REQUEST_BYTES` |
| response | 16 MiB | `ISAAC_MCP_MAX_RESPONSE_BYTES` |
| socket wait | 300 s | `ISAAC_MCP_TIMEOUT_SECONDS` |

超限 request 回 `REQUEST_TOO_LARGE`；超限 response 會被替換為 bounded `RESPONSE_TOO_LARGE` envelope，client 應縮小 query 或改讀 artifact。Camera/LiDAR 大資料仍優先使用 artifact/chunk transport。

## Structured diagnostics

`get_isaac_logs` 保留既有 `logs` 字串陣列，另新增 bounded `records`：

- `timestamp`, `severity`, `source`, `message`
- `command_id`, `command_type`
- `stage`, `frame`, `backend`, `extension`
- optional bounded/redacted `details`

可用 `filter_command_id`、`severity`、`source` 篩選。每次最多 200 筆、整批最多 256 KiB、單一 message 最多 8 KiB、runtime buffer 最多 1000 筆。dispatcher 記錄 command start/result，並把該 command 執行區間新增的 Kit Warning/Error 關聯到相同 command ID。常見 key/token/password/authorization/bearer 值在寫入 buffer 前遮罩。

不得安裝 Python `carb` log consumer：Isaac Sim physics native worker 在特定 load path 可能因 GIL callback deadlock；Kit warning/error 仍由 session log file 的 bounded command window讀取。

## 驗證

- offline：`tests/test_job_governance.py`、`tests/test_diagnostics.py`、`tests/test_connection.py`、`tests/test_log_buffer.py`
- live：`scripts/verify_job_diagnostics_live.py`
- 不可在 TCP 8766 開啟時用 destructive `tests/test_integration.py` 取代專用 verifier。
