# Camera RGB response contract

`capture_image` 在 Isaac Sim 6.0.1 提供三種回傳模式。Camera 建立後必須先播放 timeline 並暖機，RTX/Replicator 才會產生 frame。

## 參數

| 參數 | 預設 | 說明 |
|---|---:|---|
| `prim_path` | `/World/Camera` | Camera prim path。 |
| `return_mode` | `artifact` | `metadata`、`artifact` 或 `inline`。 |
| `output_path` | `null` | 只允許搭配 `artifact`，且必須以 `.png` 結尾。未指定時寫入受控 artifact root。 |
| `inline_max_bytes` | `1048576` | inline PNG 上限。可設定範圍 1 byte 到 4 MiB。 |

預設 artifact root 是 `%TEMP%\isaacsim-mcp\artifacts`。可在啟動 Isaac Sim 前設定 `ISAAC_MCP_ARTIFACT_ROOT`，指定另一個專用目錄。

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

- 不可預測的 `id` 與 `artifact://camera/<id>` handle
- resolved local `path`
- `format=png`、`mime_type=image/png`
- `size_bytes`、PNG `sha256`
- dimensions、dtype、color space、camera prim、frame 與 timestamp
- `managed=true` 表示 MCP 選擇受控路徑；明確傳入 `output_path` 時為 `false`

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

完整的大型 artifact resource provider、TTL、分塊讀取與清理屬於 Phase 1 item 5；目前 1.1 提供受控本機檔案、handle、path 與 hash。
