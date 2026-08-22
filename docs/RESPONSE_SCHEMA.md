# MCP response schema

IsaacSim-MCP 的 46 個 named tools 統一回傳 JSON text，解碼後固定包含以下欄位：

```json
{
  "schema_version": "1.0",
  "status": "success",
  "code": "OK",
  "message": "Command completed",
  "data": {},
  "warnings": [],
  "command_id": "7d8f4c32-1ea8-48b0-854d-8c9ed62ffed1",
  "timing": {
    "extension_ms": 1.234,
    "mcp_tool_ms": 2.345
  },
  "artifacts": [],
  "readback": null
}
```

## 欄位契約

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | string | 目前固定為 `1.0`。 |
| `status` | enum | `success`、`error`、`partial`、`unsupported`、`timeout`、`cancelled`。 |
| `code` | string | 穩定、可供程式判斷的結果碼，例如 `OK`、`STAGE_NOT_READY`。 |
| `message` | string | 給人閱讀的摘要，不應作為唯一的程式判斷依據。 |
| `data` | object/any | command 的主要結果。舊 handler 的非控制欄位會搬入此處。 |
| `warnings` | array | 不影響主要結果的警告。 |
| `command_id` | string | MCP Server 到 Isaac Sim extension 的 correlation ID。 |
| `timing` | object | extension 與 MCP tool 層量測到的毫秒時間。 |
| `artifacts` | array | 後續大型影像、點雲與檔案傳輸使用的 artifact metadata。 |
| `readback` | any/null | 寫入命令的驗證結果；尚未提供時為 `null`。 |

## 狀態語意

| `status` | 預設 `code` | 語意 |
|---|---|---|
| `success` | `OK` | 完整完成。 |
| `error` | `COMMAND_FAILED` | 命令未完成。router 會使用更精確的 code。 |
| `partial` | `PARTIAL_SUCCESS` | 部分套用，`data` 必須指出已套用與未支援項目。 |
| `unsupported` | `UNSUPPORTED` | runtime 或 adapter 不支援該操作或參數。 |
| `timeout` | `TIMEOUT` | 等候 runtime 或 transport 超時。 |
| `cancelled` | `CANCELLED` | 工作已取消。 |

`partial`、`unsupported`、`timeout`、`cancelled` 都是獨立狀態，禁止改寫成 `success`。

## Router codes

- `STAGE_NOT_READY`：Isaac Sim 已啟動 extension，但 USD stage 尚未可用，可用相同參數重試。
- `UNKNOWN_COMMAND`：extension registry 沒有該 command。
- `INTERNAL_ERROR`：handler 拋出未處理例外。
- `SOCKET_DISPATCH_ERROR`：socket dispatch 層無法完成 response。

rolling upgrade 期間，MCP Server 仍可接收舊 extension 的 `{status, result}` response，並在回給 client 前轉成 schema 1.0。
