# IsaacSim-MCP 測試、migration 與 release 6.x

本 reference 對應 `docs/research/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md` 已完成的 Phase 6。它提供後續 agent 的閱讀路由與發布安全邊界。實作細節以連結的文件、測試與 scripts 為準。

## 讀取流程

1. 先用下表把需求對應到 6.1～6.3。
2. 測試或 live 驗收先讀 `docs/development/LIVE_TEST_HARNESS.md`，確認 marker、scratch 身分與 cleanup 證據。
3. 能力報告先讀 tracked JSON 與產生器；逐 tool 的 pass 必須追到實際 verifier。
4. 安裝、client migration 或 release 分別讀 `docs/getting-started/INSTALLATION_WINDOWS.md`、`docs/concepts/PROTOCOL_VERSIONING_AND_MIGRATION.md`、`docs/development/RELEASE_GATE.md`。
5. 發布前重驗 canonical root、origin、branch、HEAD、worktree、Isaac Sim runtime、TCP 8766 與 remote ref。歷史數值不能當成目前狀態。

## 編號與程式位置

| 研究項目 | Task item | 能力 | 主要檔案 |
|---|---|---|---|
| 6.1 | Phase 6 item 24 | pytest test pyramid、Windows/Unix launcher CI、exact scratch-stage guard、unique namespace cleanup | `pyproject.toml`、`tests/conftest.py`、`isaac_mcp/live_testing.py`、`docs/development/LIVE_TEST_HARNESS.md` |
| 6.2 | Phase 6 item 25 | source-derived named-tool inventory、逐項 evidence/status、read-only live snapshot、tracked JSON | `isaac_mcp/tool_inventory.py`、`scripts/generate_tool_inventory.py`、`scripts/generate_all_tools_report.py`、`docs/reference/TOOL_INVENTORY.md`、`docs/research/ALL_TOOLS_TEST_RESULTS.json` |
| 6.3 | Phase 6 item 26 | secret-free install、protocol/version migration、wheel/fresh-venv/repository release gate | `docs/getting-started/INSTALLATION_WINDOWS.md`、`docs/concepts/PROTOCOL_VERSIONING_AND_MIGRATION.md`、`docs/development/RELEASE_GATE.md`、`scripts/release_gate.ps1` |

## 6.1 測試與 scratch-stage 不變條件

- Pytest layers 是 `unit`、`contract`、`offline_adapter`、`live`、`destructive`、`windows_launcher`、`unix_launcher`。Offline suite 排除 live 與兩種 platform launcher；PowerShell/Bash launcher 由各自 OS job 執行。
- `tests/test_integration.py` 含歷史 `clear_scene` 路徑，預設 skip。只有完整 `ISAAC_MCP_ALLOW_LEGACY_CLEAR_SCENE` confirmation、exact `ISAAC_MCP_SCRATCH_STAGE_PATH`、包含它的 `ISAAC_MCP_SCRATCH_ROOT` 與 stopped timeline 同時成立才允許進入。
- 新 live run 使用 `/World/MCP_Live_<32 lowercase hex>`。驗證前該 namespace 必須 exact absent；cleanup 只刪除該 root。
- 只有 `COMMAND_FAILED|PRIM_NOT_FOUND` 且 message exact 指向目標 prim 的 read-back 才算 absent。Connection、timeout 或 handler error 不得誤判為清理成功。
- 匿名或看似空白的 Stage 沒有 disposable 身分。Harness 會拒絕 `stage_path=""`，不因 prim count 少而放行。

## 6.2 evidence taxonomy

- `pass`：guarded live invocation 有成功 postcondition/read-back。
- `partial`：支援路徑通過，但宣告輸出或 postcondition 尚未完整驗證。
- `blocked`：明確外部或 runtime prerequisite 缺少，尚未進入實作；必須提供 blocker type。
- `unsupported`：active runtime/backend 明確拒絕能力。
- `fail`：已進入實作並暴露 code/contract defect。

`isaac_mcp.tool_inventory` 從 tool decorators 推導唯一 names 與 count。`scripts/generate_tool_inventory.py` 產生 reference inventory；`scripts/generate_all_tools_report.py --live` 只做 bounded read-only runtime/catalog snapshot，並在 source/runtime count 不一致時 fail closed。新增、刪除或改名 tool 時，不得新增另一個手工數字來源。

2026-08-26 歷史聚合是 `117 pass / 11 blocked / 0 fail`。8 個 ROS 2 tools 因當時 extensions disabled blocked；`search_usd`／`generate_3d` 缺外部 provider 設定；`spawn_nvidia_asset` 缺 preserved dedicated scratch live postcondition。這些狀態會隨 runtime 改變，宣稱目前結果前必須重跑 `--live --check`。

## 6.3 protocol 與 release gate

分開處理版本：package/extension `0.6.0`、outer response `1.0`、capability `1.1`、backend matrix `1.0`。未知 major 停止 write；同 major additive 欄位由 client 忽略。Server/extension version mismatch 時只做 discovery/read-only 診斷，更新後重新啟動 Kit，再執行 scratch verifier。

`scripts/release_gate.ps1` strict mode 要求 clean worktree，並檢查：

1. exact repository root/origin/branch/HEAD；
2. Isaac Sim 6.0.1 與 package/extension/schema versions；
3. tracked 與 untracked publish candidates 的 credential-like filename/value；
4. verified backup 與 restore comparison；
5. offline pyramid、Windows launcher、Ruff、publish-candidate format 與 diff integrity；
6. TCP 8766 read-only source-complete matrix，且 runtime command count 等於 source inventory；
7. wheel build與全新 temporary venv install/import；
8. worktree fingerprint 前後一致。

`-AllowDirty` 只供 commit 前開發驗證。`-SkipBackup`、`-SkipLive`、`-SkipPackage` 的 run 是診斷結果，不能當作 release pass。

## GitHub 發布順序

1. 修改前與發布前建立 verified、credential-free backup，保留 dirty/untracked。
2. 執行 `release_gate.ps1 -AllowDirty`，review exact diff 與 secret scan。
3. 確認 local HEAD 目前基底與 `refs/heads/main` remote ref 沒有未知分歧。
4. Commit 後 worktree 必須 clean，再執行 strict `release_gate.ps1`。
5. 只有使用者明確授權才 push。禁止由相似 repository 名稱推測 target。
6. Push 後以 `git ls-remote origin refs/heads/main` 比對 local HEAD；status 必須 clean。
7. 建立 post-push verified backup並回報 exact commit、remote ref、backup path、SHA-256 與 restore result。

Release gate、backup 或 tests pass 都不授權 push/merge/tag。Isaac Lab MCP 仍是獨立延後範圍，不因 Phase 6 完成自動開始。
