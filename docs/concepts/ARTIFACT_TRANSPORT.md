# 共用 artifact 傳輸契約

Camera RGB、Camera RTX outputs 與 LiDAR point cloud 共用同一個 managed artifact store。大型資料不必放入單一 MCP JSON response；client 可先取得 metadata，再用 opaque handle 分塊下載、驗證 SHA-256，最後刪除或等待 TTL 清理。

## Named tools

| Tool | 用途 |
|---|---|
| `get_artifact_info(handle)` | 讀取 MIME、format、dtype/shape、大小、SHA-256、建立與到期時間及 producer metadata |
| `read_artifact(handle, offset, length)` | 讀取一段 base64 bytes，回傳 `next_offset`、`eof` 與 chunk SHA-256 |
| `delete_artifact(handle)` | 刪除指定 artifact 的 data 與 metadata sidecar |
| `cleanup_artifacts()` | 刪除所有已到期 artifact，回傳 ID、數量與釋放 bytes |

managed handle 固定為 `artifact://managed/<opaque-id>`。ID 使用不可預測的 192-bit random value；handler 只接受完整格式，不將 handle 轉成任意檔案路徑。sidecar 的 `storage_name` 也會解析並確認仍位於受控 root，阻擋 `..` 與 traversal。

## 設定與預設限制

這些環境變數必須在啟動 Isaac Sim 前設定：

| 環境變數 | 預設值 | 說明 |
|---|---:|---|
| `ISAAC_MCP_ARTIFACT_ROOT` | `%TEMP%\isaacsim-mcp\artifacts` | managed data 與 JSON sidecar 的專用根目錄 |
| `ISAAC_MCP_ARTIFACT_TTL_SECONDS` | `3600` | artifact 保存秒數 |
| `ISAAC_MCP_ARTIFACT_MAX_TOTAL_BYTES` | `536870912` | root 內 data 總容量，512 MiB |
| `ISAAC_MCP_ARTIFACT_MAX_FILE_BYTES` | `268435456` | 單一 artifact 上限，256 MiB |
| `ISAAC_MCP_ARTIFACT_MAX_CHUNK_BYTES` | `1048576` | 單次 read 上限，1 MiB |

所有限制都必須是正整數，單檔上限不得大於總容量。寫入前會清理已到期項目，再檢查單檔與總容量；失敗時不留下 partial data。data 與 sidecar 均以 temporary file 加 atomic replace 寫入。

## 下載流程

1. 從 producer response 的 `artifacts[0]` 取得 `handle`、`size_bytes` 與 `sha256`。
2. 呼叫 `get_artifact_info`，確認 MIME、大小、hash 與 `expires_at`。
3. 從 `offset=0` 開始重複呼叫 `read_artifact`，每次使用 `next_offset`，直到 `eof=true`。
4. base64 decode 並串接 chunks，確認總長度與完整 payload SHA-256。
5. 完成後呼叫 `delete_artifact`；若保留，過期後由存取或 `cleanup_artifacts` 安全移除。

常用穩定錯誤碼：`INVALID_ARTIFACT_HANDLE`、`ARTIFACT_NOT_FOUND`、`ARTIFACT_EXPIRED`、`ARTIFACT_TOO_LARGE`、`ARTIFACT_CAPACITY_EXCEEDED`、`ARTIFACT_CHUNK_LIMIT_EXCEEDED`、`INVALID_ARTIFACT_RANGE`、`ARTIFACT_INTEGRITY_ERROR`。

明確傳入 producer 的 `output_path` 仍保留相容性，但該檔案回 `managed=false`、`handle=null`，不受 TTL、容量、分塊讀取或 cleanup 管理。

## Isaac Sim 6.0.1 驗證

`scripts/verify_artifact_transport_live.py` 會在 scratch stage 建立 Camera、LiDAR、cube 與 light，透過 named tools 對 PNG 與 NPZ 執行 metadata read-back、512-byte chunk 重組與 SHA-256 驗證，並測試 traversal、chunk limit、delete、TTL expiry、cleanup 與 prim cleanup。
