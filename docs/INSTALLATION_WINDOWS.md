# Windows / Isaac Sim 6.0.1 安裝與啟動

這份流程適用於全新 checkout，預設不需要任何 API key。`search_usd` 與 `generate_3d` 是選用外部服務；其餘本機場景、Robot、Sensor、Physics、Action Graph、Replicator 與 Human 功能不依賴外部金鑰。

## 需求

- Windows 10/11、Git、PowerShell 5.1 或 7。
- NVIDIA Isaac Sim `6.0.1`，預設安裝於 `C:\isaacsim`。
- Python `3.10+`。建議使用 `uv`，也可用 Python 內建 `venv`。
- NVIDIA driver 與 GPU 必須符合 Isaac Sim 6.0.1 需求。

先確認 runtime：

```powershell
Get-Content C:\isaacsim\VERSION
Test-Path C:\isaacsim\python.bat
```

`VERSION` 必須以 `6.0.1` 開頭。其他 Isaac Sim 版本不能拿來替代 6.0.1 live 驗收。

## 1. 全新 checkout

```powershell
git clone https://github.com/Tim0320/IsaacSim-MCP.git D:\Dev\IsaacSim-MCP
Set-Location D:\Dev\IsaacSim-MCP
git remote get-url origin
git status --short
```

預期 remote 為 `https://github.com/Tim0320/IsaacSim-MCP.git`，新 checkout 的 status 為空。

## 2. 建立 secret-free Python 環境

使用 `uv`：

```powershell
uv sync --dev
```

或使用標準 Python：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e . pytest ruff==0.16.1
```

不要建立或提交 `.env`。基本安裝不需要 `NVIDIA_API_KEY`、`NGC_API_KEY`、`ARK_API_KEY` 或其他 credential。

## 3. 啟動 Isaac Sim live extension

```powershell
.\scripts\run_isaac_sim.ps1
```

launcher 會：

- 驗證 Isaac Sim 路徑與 `6.0.1` 版本。
- 加入目前 checkout 作為 extension folder。
- 啟用 `isaac.sim.mcp_extension`。
- 讓 extension 在 `127.0.0.1:8766` 監聽。
- 依目前唯一 `display_active=Enabled` GPU 選擇明確 PhysX GPU ordinal。

不要把 `/physics/cudaDevice=-1` 當成一般預設。雙 GPU normal Kit host loop 已知可能在 Timeline Stop 後於 `PhysXGpu_64.dll` crash。需要 override 時使用：

```powershell
.\scripts\run_isaac_sim.ps1 -PhysicsGpu 1
```

## 4. 確認 8766 live route

```powershell
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8766 -State Listen
.\.venv\Scripts\python.exe -c "from isaac_mcp.connection import IsaacConnection; print(IsaacConnection(port=8766).send_command('system.get_capabilities'))"
```

預期 capabilities 顯示：

- `runtime.isaac_sim_version` 以 `6.0.1` 開頭。
- `runtime.adapter=IsaacAdapterV6`。
- `extension.command_count=128`。
- `runtime.physics_backend` 與 backend matrix 一致。

`8766` 是 live-control TCP socket。`9904` 是文件查詢 MCP，不能用來證明 Stage 已改變。

## 5. 設定 MCP client

把 command 改成 checkout 的實際絕對路徑：

```json
{
  "mcpServers": {
    "isaac-sim-live": {
      "command": "D:\\Dev\\IsaacSim-MCP\\.venv\\Scripts\\python.exe",
      "args": ["-m", "isaac_mcp.server"],
      "env": {
        "ISAAC_MCP_HOST": "127.0.0.1",
        "ISAAC_MCP_PORT": "8766"
      }
    }
  }
}
```

client 啟動後先呼叫 `get_capabilities`，再呼叫 `get_scene_info`。不要先執行 write，也不要把 documentation route 命名成 `isaac-sim-live`。

## 6. 離線與 read-only 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not live and not windows_launcher and not unix_launcher" -k "not test_detect_version_returns_zero_on_failure"
.\.venv\Scripts\python.exe -m pytest -q tests\test_run_isaac_sim_windows.py
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe .\scripts\generate_all_tools_report.py --live --check
```

`generate_all_tools_report.py --live --check` 只做 read-only inventory/runtime 查詢，不重寫 tracked report，也不清除 Stage。

## 選用外部服務

- `search_usd`：需要 `NVIDIA_API_KEY`。
- `generate_3d`：需要 `ARK_API_KEY`，provider 也可能要求 `BEAVER3D_MODEL`。

只在啟動 Isaac Sim 的 PowerShell session 設定值。release report、Git、MCP JSON、skill 與 log 都不能保存 key。

## 問題定位

| 現象 | 檢查 |
|---|---|
| 8766 沒有 listener | 查看 Isaac Sim console 是否載入 `isaac.sim.mcp_extension`，確認 checkout 與 launcher path。 |
| MCP client 能列 tools，但操作回連線錯誤 | stdio server 已啟動，但 Isaac Sim extension/8766 尚未 ready。 |
| 9904 可用，Stage 沒變 | 9904 是 documentation route；改用 `isaac-sim-live`/8766。 |
| `STAGE_NOT_READY` | Stage 尚未建立完成；以相同 read-only request bounded retry。 |
| ROS 2 tools blocked | 先讀 `get_ros2_status`；bridge/core/nodes 必須啟用，且 external subscriber 才能證明 publish。 |
| Newton 顯示 untested/unsupported | 依 backend matrix fail closed；V6 import 或共用程式碼不構成 Newton live evidence。 |
