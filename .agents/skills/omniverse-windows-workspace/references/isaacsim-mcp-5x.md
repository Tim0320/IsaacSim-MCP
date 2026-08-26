# IsaacSim-MCP 安全、可靠性與可觀測性 5.x

本 reference 對應 `docs/research/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md` 已完成的 Phase 5。它是後續 agent 的 retrieval 與安全索引；修改行為或宣稱目前 live support 前，仍須完整閱讀對應契約、測試與專用 verifier。

## 讀取流程

1. 先用下表把需求對應到 5.1～5.4。
2. 完整閱讀對應契約，確認 policy、schema、上限、terminal state、redaction 與已知邊界。
3. 修改前檢查 public tool、client connection、extension dispatcher、handler、focused tests 與 live verifier。
4. 重新查詢目前 `get_capabilities`。下列 command count、PID 與 live 結果皆為歷史證據。
5. 發布前後記錄 canonical checkout、remote、branch、HEAD、status，並建立通過 restore validation 的 credential-free backup。

## 編號與程式位置

| 研究項目 | Task item | 能力 | Named tools／介面 | 契約 | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 5.1 | Phase 5 item 20 | 限縮 `execute_script`／`reload_script` escape hatch | `execute_script`, `reload_script`, `get_script_policy`, `get_script_audit_log` | `docs/concepts/COMMAND_GOVERNANCE.md` | `scripts/verify_command_governance_live.py` |
| 5.2 | Phase 5 item 21 | command ID、idempotency、write lifecycle、read-back 與有限 transaction | 所有 named tools 的 `command_id`／`idempotency_key`；`apply_stage_batch` | `docs/concepts/COMMAND_GOVERNANCE.md`、`docs/reference/RESPONSE_SCHEMA.md` | `scripts/verify_command_governance_live.py` |
| 5.3 | Phase 5 item 22 | 共用 job lifecycle、deadline、取消與 transport limits | `start_job`, `get_job_status`, `cancel_job`, `list_jobs` | `docs/concepts/JOB_DIAGNOSTICS.md` | `scripts/verify_job_diagnostics_live.py` |
| 5.4 | Phase 5 item 23 | command-correlated、bounded、redacted diagnostics | `get_isaac_logs` structured records 與 legacy logs | `docs/concepts/JOB_DIAGNOSTICS.md` | `scripts/verify_job_diagnostics_live.py` |

主要實作位置：

- client metadata／transport：`isaac_mcp/command_context.py`、`isaac_mcp/connection.py`、`isaac_mcp/tools/__init__.py`
- dispatcher governance：`isaac.sim.mcp_extension/isaac_sim_mcp_extension/command_governance.py`、`extension.py`
- script policy：`execution_guard.py`、`script_policy.py`、`handlers/simulation.py`
- jobs／diagnostics／socket limits：`handlers/jobs.py`、`diagnostics.py`、`socket_server.py`

## 共同不變條件

- 所有 source-registered named tools 都使用 response schema `1.0`，並接受 optional caller `command_id`／`idempotency_key`。不要新增繞過 shared wrapper 或 dispatcher metadata 的 public tool。
- Idempotency ledger 只存在目前 Kit runtime，最多 256 entries、TTL 600 秒。相同 key 與相同 payload 必須 replay 原 response；相同 key 配不同 payload 必須在 handler 前回 `IDEMPOTENCY_KEY_CONFLICT`。
- `apply_stage_batch` 的 atomic rollback 只涵蓋可完整 snapshot/restore 的 Stage composition writes。Sensor、ROS 2、Replicator、motion、filesystem 與跨 subsystem batch 不得宣稱原子交易。
- Script timeout 與 job cancellation 都是 cooperative。Python bytecode／awaitable 可在 safe point 結束；native Kit call 只能在控制權回到 Python 後觀察 deadline 或 cancellation。不要宣稱 hostile-code sandbox 或強制 native preemption。
- 大資料優先走 managed artifact/chunk transport。Request/response 超限必須 fail closed，不能靜默截斷成看似成功的 payload。
- Diagnostics 必須在進 buffer 前遮罩 sensitive values，structured records 與 legacy `logs` 都適用。不得安裝 Python `carb` log consumer；physics native worker callback 可能因 GIL 造成 deadlock。
- Live verifier 只使用 owned scratch namespace，結束時確認 fixture absent、timeline stopped、job/writer/render product/trigger cleanup、Kit responding、TCP `8766` 與新增 native dump。
- TCP `8766` 開啟時，不把 destructive `tests/test_integration.py` 納入 offline suite。

## 5.1 Script policy

- Policy 控制 enabled state、allowed roots、source bytes、cooperative timeout、per-stream output bytes 與 background opt-in。
- 預設拒絕 thread、process、subprocess 與 async background scheduling。只對可信任程式碼開放，並優先使用 named tools。
- Audit 只保存 command ID、operation、target SHA-256、outcome、elapsed 與 bounded metadata，不保存 source 或 credential。
- `cwd`／file path 必須 canonicalize 並留在 allowed roots；越界、禁用、timeout 與 output overflow 都 fail closed。

2026-08-25 歷史驗收使用 124-command registry：cwd/background/output/timeout 四種拒絕、timeout 後 target prim absent、5 筆 hash-only audit record、scratch cleanup、stopped timeline、Kit/TCP 存活與新增 dump 0。

## 5.2 Command governance

- Dispatcher 驗證 printable ASCII `command_id` 與 bounded idempotency key，並以 command type + normalized params 建立 request fingerprint。
- 每個 response 的 `data.command` 描述 read/write、apply state、readback state、idempotency key、replayed 與 optional original command ID。
- Write classification 採保守策略。新增 read command 時要更新分類，避免 read 被錯標 applied；新增 write command 不可被命名規則誤判成 read。
- Replay 必須回新 caller command ID，同時保留 `original_command_id`；不得再次執行 handler。

2026-08-25 歷史驗收證明同 key/payload create 只套用一次、different payload collision 在 apply 前拒絕、錯誤 Stage batch 回 `BATCH_ROLLED_BACK` 且 probe attribute absent。當次 safe suite 為 374 passed。

## 5.3 Job 與 transport

- Managed lifecycle 為 `queued → running → succeeded|failed|cancelled|timed_out`，保留 progress、timestamps、deadline、error、result 與 artifact handles。
- Asset/Sensor allowlist 目前包含 URDF/USD/NVIDIA asset load 與 Camera/LiDAR capture；max retained jobs 64，deadline 1..300000 ms。滿額時只驅逐最舊 terminal job，不驅逐 active job。
- `motion-*` 與 `sdg-*` job ID 由共用 status/cancel tools 委派原 provider。不要複製或偽造第二份 provider lifecycle。
- Client disconnect 不刪除 Kit-owned job。Start response 遺失時使用原 idempotency key 重送，取得同一 job ID；status requery 只能讀 retained result，不能重新執行。
- 預設 transport limits：request 1 MiB、response 16 MiB、socket wait 300 秒。Override 為 `ISAAC_MCP_MAX_REQUEST_BYTES`、`ISAAC_MCP_MAX_RESPONSE_BYTES`、`ISAAC_MCP_TIMEOUT_SECONDS`。

2026-08-25 final live 驗收使用 128-command registry：Camera metadata job 在 client disconnect 後由新 connection 查得 `succeeded`，重查 result 相同；100-frame SDG 在第 3 frame 由共用 cancel 進入 `cancelled`，writer/render product/trigger cleanup 全 true。

## 5.4 Diagnostics

- Structured record 欄位為 timestamp、severity、source、message、command ID/type、stage、frame、backend、extension 與 optional details。
- Dispatcher 記錄 command start/result，並以 command 開始時的 Kit log offset 擷取該 window 新增的 Warning/Error，關聯同一 command ID。
- Limits：runtime buffer 1000 records、query 200 records/256 KiB、message 8 KiB。Filter 使用 `filter_command_id`、severity、source。
- 常見 API key、token、password、authorization、credential 與 bearer 值必須先 redaction。測試 raw secret absence時要檢查完整 `get_isaac_logs` data，不能只檢查 structured records。

2026-08-25 final live 驗收以 intentional `carb.log_warn` 與 captured stdout 取得 dispatcher、Kit、stdout 三種 source；structured/legacy log 都只保留 `[REDACTED]`，raw synthetic token absent。Scratch root absent、timeline stopped、TCP `8766` PID 31576 Responding、新增 dump 0。PID 與 record count 屬單次歷史數值。

## 驗證與發布

Offline safe suite：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_integration.py --ignore=tests/test_launcher_engine.py -k "not test_detect_version_returns_zero_on_failure"
.\.venv\Scripts\python.exe -m ruff check isaac_mcp isaac.sim.mcp_extension/isaac_sim_mcp_extension tests
git diff --check
uv build
```

5.3/5.4 完成時的歷史結果為 `384 passed, 1 deselected`；focused lifecycle/transport/log/schema contracts 為 `46 passed`。

發布前後都要：

1. 核對 repository root、`origin` URL、branch、local HEAD、remote ref 與 worktree。
2. 執行 `scripts/backup_project.ps1`，確認 `RestoreValidated=True` 且沒有 credential-like untracked files。
3. 做 sensitive filename/pattern review；README placeholder 不能誤報成真實 key，也不能因此略過其他命中。
4. Push 後用 `git ls-remote origin refs/heads/main` 比對 local HEAD，確認 worktree clean，再建立 post-push backup。

## Current-claim checklist

1. 重新記錄 canonical checkout、remote、branch、HEAD、status 與 verified backup。
2. 確認 Isaac Sim 6.0.1、source inventory 與 runtime command registry 一致、capability flags、TCP `8766`、Kit PID/response 與 physics GPU policy。
3. 只執行對應專用 verifier，並使用每次 run 唯一 idempotency key，避免歷史 replay 被誤判為新執行。
4. Camera live job 先完成 Play 與 bounded warmup；SDG cancel 等待至少一個 completed-frame safe point。
5. 捕捉 terminal state、repeat-query equality、redaction、cleanup、timeline、port、logs 與 dumps。沒有重跑 verifier 時，所有數值都標記為 historical。
