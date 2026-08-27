# Authority and Generated Metadata

本專案分開管理 source authority、runtime authority、compatibility contract 與 historical evidence。較低層的資料不能覆蓋同一 claim 的較高層權威。

| Claim | 權威來源 | 衍生或驗證 artifacts |
|---|---|---|
| Public tool names 與 count | `isaac_mcp/tools/*.py` 內的 `@mcp.tool(<name>)` decorators | `isaac_mcp/tool_inventory.py`、`docs/reference/TOOL_INVENTORY.md`、registration tests |
| Package release version | `isaac_mcp.__version__` | dynamic `pyproject.toml` version、extension version 與 manifest parity tests |
| 目前 runtime version、backend、extensions、command registry、feature flags | Active extension 的 `get_capabilities` | capability schema 與 backend matrix contracts |
| Response 與 migration semantics | versioned contract documents 與 tests | `RESPONSE_SCHEMA.md`、protocol migration、contract tests |
| Live success | 具有 read-back 與 cleanup evidence 的 guarded verifier | `docs/research/` 內有日期的 reports |

## Tool inventory

從 source 產生 tracked reference：

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_tool_inventory.py
```

只檢查、不寫檔：

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_tool_inventory.py --check
```

禁止在 package metadata 或手工維護的 README 內新增固定 tool count。All-tools evidence generator 同樣使用 `isaac_mcp.tool_inventory`；搭配 `--live` 時，active extension command count 必須等於 source inventory 的 Extension-routed subset。`MCP_LOCAL_TOOL_NAMES` 明確列出不依賴 Extension 的 server-local tools，目前包含 `get_runtime_status`。

## Versions

`pyproject.toml` 從 `isaac_mcp/__init__.py` 動態讀取 package version。Isaac Sim extension 的 Python package 與 `config/extension.toml` 必須使用相同 release version；tests 與 release gate 會拒絕 mismatch。

Response、capability 與 backend-matrix schema versions 與 package version 分開演進。相容規則見 [Protocol versions 與 migration](../concepts/PROTOCOL_VERSIONING_AND_MIGRATION.md)。

## Capabilities

Static documentation 定義欄位與語意。只有 active extension 能回報目前 backend、extension availability、tool registration 與 support state。`null`、`false`、`blocked`、`unsupported` 與 `fail` 必須分開處理。

## Evidence

`docs/research/` 內的檔案是 timestamped snapshots，保存指定 checkout 與 runtime 的 evidence；它們不能證明較新的 checkout 或目前 running Isaac Sim 仍具有相同狀態。
