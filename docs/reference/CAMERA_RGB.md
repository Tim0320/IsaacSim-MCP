# Camera RGB response contract

`capture_image` 在 Isaac Sim 6.0.1 提供三種 Extension 傳輸模式，MCP wrapper 另提供 opt-in `image` mode。MCP input schema 將 `return_mode` 宣告為 `metadata | artifact | inline | image` enum。

## 參數

| 參數 | 預設 | 說明 |
|---|---:|---|
| `prim_path` | `/World/Camera` | Camera prim path。 |
| `return_mode` | `artifact` | `metadata`、`artifact`、`inline` 或 MCP-only `image`。 |
| `output_path` | `null` | 只允許搭配 `artifact`，且必須以 `.png` 結尾。未指定時寫入受控 artifact root。 |
| `inline_max_bytes` | `1048576` | inline PNG 上限。可設定範圍 1 byte 到 4 MiB。 |

預設 artifact root 是 `%TEMP%\isaacsim-mcp\artifacts`。可在啟動 Isaac Sim 前設定 `ISAAC_MCP_ARTIFACT_ROOT`，指定另一個專用目錄；TTL、容量與分塊讀取設定見 [`ARTIFACT_TRANSPORT.md`](../concepts/ARTIFACT_TRANSPORT.md)。

## 共用影像 metadata

三種模式都會在 response `data.image` 提供：

- `camera_prim`
- `dtype`，RGB 固定為 `uint8`
- `shape`、`width`、`height`、`channels`
- `color_space`，值為 `RGB` 或 `RGBA`
- `raw_size_bytes` 與 `pixel_sha256`
- `captured_at`、`timestamp_ns`
- `frame`、`timeline_time_seconds`、`time_codes_per_second`

`pixel_sha256` 對應未壓縮、C-contiguous pixel bytes。PNG artifact 與 inline payload 另有自己的 `sha256`。

## `metadata`

只回影像描述與 pixel hash，不寫檔，也不傳輸 pixels：

```text
capture_image(prim_path="/World/Camera", return_mode="metadata")
```

## `artifact`

預設模式。PNG 先寫入同目錄的 temporary file，再以 atomic replace 完成，避免 client 讀到半個檔案。

response envelope 的 `artifacts[0]` 包含：

- 不可預測的 `id` 與 `artifact://managed/<opaque-id>` handle
- resolved local `path`
- `format=png`、`mime_type=image/png`
- `size_bytes`、PNG `sha256`
- dimensions、dtype、color space、camera prim、frame 與 timestamp
- `created_at`、`expires_at` 與 `ttl_seconds`
- `managed=true` 表示 MCP 選擇受控路徑；明確傳入 `output_path` 時為 `false` 且 `handle=null`

## `inline`

把 PNG bytes 用 base64 放在 `data.inline.data`：

```text
capture_image(
  prim_path="/World/Camera",
  return_mode="inline",
  inline_max_bytes=1048576
)
```

先 base64 decode，再以 `data.inline.sha256` 驗證 PNG bytes。若 PNG 超過限制，回 `status=error` 與 `code=INLINE_SIZE_LIMIT_EXCEEDED`，不會傳回截斷資料。

managed artifact 可用 `get_artifact_info`、`read_artifact`、`delete_artifact` 與 `cleanup_artifacts` 管理；完整契約見 [`ARTIFACT_TRANSPORT.md`](../concepts/ARTIFACT_TRANSPORT.md)。

## `image`

直接回傳 MCP-native image content，供支援 MCP `ImageContent` 的 client 顯示或交給 vision model：

```text
capture_image(
  prim_path="/World/Camera",
  return_mode="image"
)
```

MCP Server 會把 `image` 轉為 Extension 的 bounded `inline` capture，驗證 `image/png`、base64、byte size 與 SHA-256，再回傳：

- `TextContent`：schema 1.0 metadata；`data.inline` 保留 format、size 與 hash，但移除 base64 `data`。
- `ImageContent`：`mimeType=image/png` 與 PNG base64。
- `structuredContent.result`：與既有 `{result: string}` output schema 相容的 schema 1.0 JSON text。

預設仍是 `artifact`。`image` 不支援 `output_path`，也受 `inline_max_bytes` 的 1 MiB 預設與 4 MiB hard cap 約束。MCP Client 能收到 image content 不代表其 UI 一定會顯示；client 必須實作 image rendering 或 vision forwarding。

## Render warm-up

Camera 新建或解析度變更後，第一個 RTX read 可能只排入 render request 並回 `CAMERA_FRAME_NOT_READY`。MCP Server 會等待 500 ms，接著在同一個 tool call 內自動重試一次：

```text
capture_camera_output(return_mode="image")
  → first read
  → CAMERA_FRAME_NOT_READY
  → bounded render wait
  → one retry
  → TextContent + ImageContent
```

Camera capture 是 time-dependent observation，這兩個內部 read 不使用 Extension idempotency cache，外層 MCP command context 會在完成後還原。發生 retry 時，response `data.camera_warmup` 會記錄 `attempted=true`、`capture_attempts=2` 與 `delay_ms=500`。第二次仍未取得 frame 時，Server 會回傳該錯誤，不會無限等待或重試。Extension handler 只負責排入 asynchronous render request，不會同步 pump Kit event loop。

`scripts/verify_native_image_content_live.py` 會在唯一 scratch namespace 建立 Cube、DistantLight 與 Camera，執行 `160×90 → 640×360` resolution transition，接著以單次 MCP tool call 驗證 bounded warm-up、`TextContent`、`ImageContent`、PNG decode、size/SHA-256、非黑 RGB pixels、metadata 無重複 base64，最後釋放 Camera、刪除 scratch root 並還原 timeline state。預設測 stdio；設定 `ISAAC_MCP_VERIFIER_URL=http://127.0.0.1:8000/mcp` 時改測已啟動的 Streamable HTTP endpoint。
