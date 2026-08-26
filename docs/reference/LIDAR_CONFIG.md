# RTX LiDAR configuration contract

Isaac Sim 6.0.1 的 `create_lidar` 提供兩種互斥模式，建立後可用
`get_lidar_config(prim_path)` 讀回實際 USD schema 值。

## Named preset

```text
create_lidar(
  prim_path="/World/Lidar",
  config="Example_Rotary",
  variant=null
)
```

`config` 交由 Isaac Sim 6 的 `Lidar.create` preset registry 處理；`variant`
只能搭配 `config`。Named preset 不可再混用 generic 欄位，否則回
`LIDAR_PRESET_CUSTOM_CONFIG_CONFLICT`。

## Generic configuration

```text
create_lidar(
  prim_path="/World/Lidar",
  horizontal_fov_deg=120,
  vertical_fov_deg=20,
  horizontal_resolution_deg=1,
  vertical_resolution_deg=2,
  rotation_rate_hz=10,
  min_range_m=0.5,
  max_range_m=40
)
```

| 欄位 | 預設值 | 限制 |
|---|---:|---|
| `horizontal_fov_deg` | 360 | `(0, 360]` |
| `vertical_fov_deg` | 30 | `[0, 180]` |
| `horizontal_resolution_deg` | 1 | 大於 0，且 FOV 必須可整除 |
| `vertical_resolution_deg` | 1 | 大於 0；非零 FOV 必須可整除 |
| `rotation_rate_hz` | 10 | 1–100 的整數 |
| `min_range_m` | 0.3 | `0 <= min < max` |
| `max_range_m` | 200 | `max > min` |

另外限制 horizontal samples 最多 65,536、vertical channels 最多 1,024、
每次 scan 最多 2,000,000 points。驗證失敗時不建立 prim，response `code`
會指出 FOV、resolution、range、rate、整除或 budget 的具體原因。

## Isaac Sim 6.0.1 mapping

Generic 模式會 author `OmniSensorGenericLidarCoreAPI` 的：

- valid/start azimuth、scan rate、tick rate、pattern firing rate
- near/far range、channel/emitter count
- emitter azimuth/elevation、1-based channel ID 與 fire time arrays

Partial-FOV sensor 使用 `accumulate_outputs=False` 逐 tick 發布資料，避免等待
完整 360 度 accumulation。讀回的 `effective` 包含原始輸入與推導出的
`horizontal_samples`、`vertical_channels`；`schema_attributes` 提供實際 USD
值，便於呼叫端核對設定沒有被靜默忽略。

## Live evidence

`scripts/verify_lidar_config_live.py` 會在 scratch stage 驗證兩組不同設定、
有效值 read-back、非零點雲、無效設定拒絕與所有 scratch prim 清理。
