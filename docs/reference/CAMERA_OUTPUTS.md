# Camera RTX outputs and calibration

Isaac Sim 6.0.1 的 typed camera output 由 `capture_camera_output` 提供；相機模型由 `get_camera_calibration` 讀回。兩者皆經 `127.0.0.1:8766` 控制 live stage，與 `9904` documentation MCP 無關。

## 支援的 output

| `output_type` | Isaac annotator | dtype | shape | units |
|---|---|---|---|---|
| `depth` | `distance_to_camera` | `float32` | `[height,width,1]` | meters，camera radial distance |
| `distance_to_image_plane` | `distance_to_image_plane` | `float32` | `[height,width,1]` | meters |
| `semantic_segmentation` | `semantic_segmentation` | `uint32` | `[height,width,1]` | semantic ID |
| `instance_segmentation` | `instance_segmentation` | `uint32` | `[height,width,1]` | instance ID |
| `instance_id_segmentation` | `instance_id_segmentation` | `uint32` | `[height,width,1]` | instance prim ID |
| `normals` | `normals` | `float32` | `[height,width,3]` | unitless |
| `motion_vectors` | `motion_vectors` | `float32` | `[height,width,2]` | pixels per frame |

`annotator_info` 會轉為 JSON-safe 結構。`instance_segmentation` 提供 semantic instance 對照；需要 ID 到 prim path 的映射時使用 `instance_id_segmentation`。

## 回傳模式

- `metadata`：只回 metadata，不傳輸 array bytes。
- `artifact`：預設模式，寫入共用 managed store 的 `.npy` v1 artifact；可用 `output_path` 指定不受管理的 `.npy` 路徑。TTL、分塊下載、hash 與清理見 [`ARTIFACT_TRANSPORT.md`](../concepts/ARTIFACT_TRANSPORT.md)。
- `inline`：回傳 base64 raw little-endian array bytes，不含 `.npy` header。預設上限 1 MiB，hard cap 4 MiB。

`capture_camera_output(output_type="rgb", return_mode="image")` 會轉送 RGB capture 並回傳 MCP-native `ImageContent`；完整契約見 [`CAMERA_RGB.md`](CAMERA_RGB.md)。Depth、normals、segmentation 與 motion vectors 是 typed arrays，`return_mode="image"` 會回 `CAMERA_IMAGE_CONTENT_UNSUPPORTED`，避免把未定義的色彩映射冒充成可視影像。

Metadata 包含 `output_type`、`annotator`、`dtype`、`shape`、`width`、`height`、`channels`、`units`、`coordinate_space`、`raw_size_bytes`、`raw_sha256`、frame/timestamp 與 `annotator_info`。

```text
capture_camera_output(
  prim_path="/World/Camera",
  output_type="depth",
  return_mode="artifact"
)
```

MCP schema 將 `return_mode` 公開為 `metadata | artifact | inline | image` enum。收到 `CAMERA_FRAME_NOT_READY` 時，MCP Server 會保留同一 camera prim、等待 500 ms，並在同一個 tool call 內自動重試一次。第二次仍未準備時才把錯誤回給 caller，不會無限重試。V5 或缺少 annotator 的 runtime 回 `CAMERA_OUTPUT_UNSUPPORTED`。

## Calibration

```text
get_camera_calibration(prim_path="/World/Camera")
```

回傳 resolution、pinhole `intrinsic_matrix`、`camera_to_world`、`world_to_camera`、projection、focal length、apertures/offsets、clipping range、`meters_per_unit`、depth units 與 matrix conventions。USD extrinsic 使用 row-vector matrix；camera local view direction 是 `-Z`，`+Y` 向上。Intrinsic 使用 pixel 座標、左上原點、x 向右、y 向下。

## Live 驗證

`scripts/verify_camera_outputs_live.py` 會建立專用 scratch camera、cube 與 light，驗證七種輸出的 dtype/shape/units、raw/artifact SHA-256、已知幾何非零資料、semantic label、instance prim path 與 calibration，最後只刪除該腳本建立的 scratch prim。
