# MCP response schema

IsaacSim-MCP 的 106 個 named tools 統一回傳 JSON text，解碼後固定包含以下欄位：

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

Camera 與 LiDAR artifact 已使用此欄位。共用 TTL、容量、分塊下載、hash、刪除與 cleanup 契約見 [`ARTIFACT_TRANSPORT.md`](ARTIFACT_TRANSPORT.md)；Camera 契約見 [`CAMERA_RGB.md`](CAMERA_RGB.md) 與 [`CAMERA_OUTPUTS.md`](CAMERA_OUTPUTS.md)；LiDAR `.npz`、typed fields 與 per-field hash 契約見 [`LIDAR_POINT_CLOUD.md`](LIDAR_POINT_CLOUD.md)。

## OmniGraph lifecycle response

12 個 Action Graph tools 使用相同 envelope，詳細資料依操作放在 `data` 或 `readback`：

- query：`list_action_graphs`、`get_action_graph` 與 `get_action_graph_status` 將 graph/node/edge、enabled、compute count、messages 或 evaluation state 放在 `data`。
- preview：新增 write tools 預設 `preview=true`，並在 `data.preview=true` 回傳已驗證的 exact target；未修改 graph。
- apply：connect/disconnect、enabled state、ScriptNode 與 delete 成功後，在 `readback` 回傳實際 connection/state/source hash/prim absence。
- rollback：apply 失敗且還原成功時使用 `status=error`、`code=GRAPH_TRANSACTION_ROLLED_BACK` 及 `readback.rolled_back=true`；還原本身失敗使用 `GRAPH_ROLLBACK_FAILED`。
- evaluation：`evaluate_action_graph` 回傳每個 node 的 `compute_count_before`／`compute_count_after` 和 messages；node error 使用 `GRAPH_EVALUATION_FAILED`，不得改寫成成功。

enabled state 是 runtime-only。相關 response 會明確回傳 `runtime_state_persistent=false`，client 不可據此推論 Stage save/reopen 後仍保持相同狀態。Script source 預設不回傳；只有 `get_action_graph(include_script_source=true)` 才回 inline source，file mode 仍以 path、存在狀態、mtime、bytes 與 SHA-256 描述。

OmniGraph stable errors 包含 `TIMELINE_NOT_STOPPED`、`TIMELINE_STATE_UNAVAILABLE`、`INVALID_GRAPH_PATH`、`GRAPH_NOT_FOUND`、`ATTRIBUTE_NOT_FOUND`、`NODE_NOT_FOUND`、`CONNECTION_ALREADY_EXISTS`、`CONNECTION_NOT_FOUND`、`INVALID_ENABLED_STATE`、`GRAPH_DISABLED`、`GRAPH_NOT_EXPLICITLY_EVALUABLE`、`GRAPH_EVALUATION_FAILED`、`SCRIPT_MODE_CONFLICT`、`SCRIPT_FILE_NOT_FOUND`、`SCRIPT_NODE_REQUIRED`、`GRAPH_TRANSACTION_ROLLED_BACK` 與 `GRAPH_ROLLBACK_FAILED`。完整操作契約見 [`OMNIGRAPH_LIFECYCLE.md`](OMNIGRAPH_LIFECYCLE.md)。
