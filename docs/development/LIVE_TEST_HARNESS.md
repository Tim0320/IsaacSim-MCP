# Isaac Sim live test harness

Phase 6.1 將測試分成 `unit`、`contract`、`offline_adapter`、`live/destructive`、`windows_launcher` 與 `unix_launcher`。CI 的 offline matrix 同時跑 Windows 與 Ubuntu；PowerShell 與 Bash launcher 分開驗證。

## 預設安全行為

- `tests/test_integration.py` 屬於 legacy destructive suite，預設 skip。
- 只因為 Stage 是匿名、空白或 prim 很少，不代表可以清除。
- destructive run 必須提供已開啟的 scratch USD exact path、其允許根目錄，以及完整 confirmation token。
- 新 live test 每次使用 `/World/MCP_Live_<32 hex>` 唯一 namespace；teardown 只刪除此 root，最後以 `scene.get_prim_info` 證明 absent。
- harness 不會自行建立、開啟或替換 Stage，避免測試指令在錯誤視窗上覆蓋使用者工作。

## 離線測試金字塔

```powershell
uv run pytest -q -m "unit or contract or offline_adapter"
uv run pytest -q -m "not live and not windows_launcher and not unix_launcher" -k "not test_detect_version_returns_zero_on_failure"
uv run pytest -q tests\test_run_isaac_sim_windows.py
```

Unix Bash launcher：

```bash
pytest -q tests/test_launcher_engine.py
```

## Legacy destructive suite

先在 Isaac Sim 明確建立並開啟 repo 外的專用 scratch USD，確認 timeline stopped，再由同一 shell 設定：

```powershell
$env:ISAAC_MCP_ALLOW_LEGACY_CLEAR_SCENE = "I_UNDERSTAND_THIS_CLEARS_THE_STAGE"
$env:ISAAC_MCP_SCRATCH_ROOT = "D:\IsaacSimScratch"
$env:ISAAC_MCP_SCRATCH_STAGE_PATH = "D:\IsaacSimScratch\legacy-integration.usda"
uv run pytest -q tests\test_integration.py
```

任何一項缺少、stage path 不一致、stage 在 scratch root 外、timeline 非 stopped 或 namespace 已存在，都會在第一個 write 前拒絕。

## Source-complete tools 報告

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_all_tools_report.py --live
.\.venv\Scripts\python.exe -m pytest -q tests\test_all_tools_report.py
```

產生器只執行 `scene.get_info`、`simulation.get_state`、`system.get_capabilities` 與 bounded `assets.list_nvidia` read-only commands。每個 write tool 的 pass 仍引用其專用 guarded verifier，不會把 registry presence 當成 live pass。
