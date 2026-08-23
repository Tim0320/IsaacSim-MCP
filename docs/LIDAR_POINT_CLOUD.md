# LiDAR point cloud 傳輸契約

`get_lidar_point_cloud` 將 Isaac Sim RTX LiDAR frame 回傳為 metadata、受控 `.npz` artifact，或有大小上限的 inline `.npz`。預設為 `artifact`，避免把大型點雲直接塞入 JSON。

## 輸入

| 欄位 | 預設 | 說明 |
|---|---:|---|
| `prim_path` | `/World/Lidar` | LiDAR prim path |
| `return_mode` | `artifact` | `metadata`、`artifact` 或 `inline` |
| `output_path` | 無 | artifact mode 可指定的既有父目錄下 `.npz` 路徑 |
| `inline_max_bytes` | 1 MiB | inline encoded NPZ 上限，hard cap 4 MiB |

LiDAR 建立後必須播放 timeline 暖機。尚無 frame 時回 `LIDAR_FRAME_NOT_READY`，不會把零筆資料誤報為成功。

## Metadata

成功回應的 `data.lidar_point_cloud` 包含：

- `point_count`
- `fields.<name>.dtype|shape|units|size_bytes|sha256`
- `coordinate_type`：GMO 原始座標型態，V6 通常為 `spherical`
- `coordinate_frame`：GMO frame of reference
- `sensor_timestamp_ns`、`sensor_frame_id`
- `sensor_pose`：透過 USD prim read-back 取得的位置、旋轉與 scale
- `object_id_map`：128-bit stable object ID 的 32 位 hex key 對應 prim path
- `unavailable_fields`：本 frame 或 runtime 無法提供的欄位
- MCP capture timestamp 與 timeline frame/time/state

## NPZ fields

每個 field 都是 standard NumPy v1 `.npy` member，row count 必須等於 `point_count`。

| Field | dtype / shape | units | 狀態 |
|---|---|---|---|
| `points` | `float32 [N,3]` | meters | 必有，Cartesian XYZ |
| `range` | `float32 [N]` | meters | V6 必有 |
| `azimuth` | `float32 [N]` | degrees | V6 必有 |
| `elevation` | `float32 [N]` | degrees | V6 必有 |
| `intensity` | `float32 [N]` | normalized return strength | GMO 有 scalar 時提供 |
| `object_id_low` | `uint64 [N]` | stable object ID low 64 bits | GMO FULL aux 可用時提供 |
| `object_id_high` | `uint64 [N]` | stable object ID high 64 bits | GMO FULL aux 可用時提供 |

完整 object ID 為 `(object_id_high << 64) | object_id_low`。`semantic_id` 目前沒有可驗證的 GMO direct field，因此列在 `unavailable_fields`，不從 object ID 猜測語意 ID。

## V6 座標轉換

Isaac Sim 6 `generic-model-output` 在 spherical mode 的 `x/y/z` 分別是 azimuth degrees、elevation degrees、range meters。MCP 依 RTX LiDAR reference conversion 產生 Cartesian `points`：

```text
rxy = range * cos(elevation)
x = rxy * cos(azimuth)
y = rxy * sin(azimuth)
z = range * sin(elevation)
```

原始 spherical components 仍分別保存在 `azimuth`、`elevation`、`range` fields。
