# Transport and V6 Adapter Refactor Research

Status：design research only。這份文件記錄目前 source 的拆分邊界與驗證門檻；尚未改變 MCP tool、TCP wire format、response schema 或 Isaac adapter public methods。

## Measured baseline

| Target | Current size | Observation |
|---|---:|---|
| `isaac_mcp/connection.py` | 253 lines / 10,727 bytes | Persistent TCP、JSON completion detection、limits、reconnect 與 exception mapping 集中在同一 class。 |
| `adapters/v6.py` | 3,366 lines / 163,385 bytes | `IsaacAdapterV6` 有 85 個 methods，涵蓋 backend、scene、robot/motion、physics、sensor、material、simulation 與 script。 |
| `handlers/graphs.py` | 1,187 lines / 52,033 bytes | graph CRUD、ScriptNode、transaction、evaluation 與 diagnostics 混合。 |
| `handlers/sensors.py` | 1,033 lines / 42,656 bytes | lifecycle、Camera、LiDAR、inline/artifact/chunk serialization 混合。 |
| `handlers/stage_composition.py` | 950 lines / 39,018 bytes | composition、snapshot/rollback、metadata 與 attribute authoring 混合。 |
| `handlers/humans.py` | 944 lines / 41,261 bytes | ownership、spawn、behavior、navigation 與 lifecycle 混合。 |
| `handlers/capabilities.py` | 890 lines / 36,606 bytes | runtime detection、backend matrix projection 與 feature declaration混合。 |

Size 本身不是 bug；拆分理由必須是 ownership、state lifecycle、failure boundary 或測試隔離更清楚，而不是只追求較短檔案。

## 1. TCP framing and connection findings

目前 request 與 response 都沒有 length prefix 或 delimiter。兩端持續累積 bytes，直到 `json.loads` 成功才視為一個完整 message。現有 client 以一次一個 request、等待 response 後才送下一個 request，避免正常流程中的 message coalescing；但 wire protocol 本身無法安全分割連續的 `{...}{...}`。

`receive_full_response` 另有三個需要先處理的問題：

- 每次 `recv` 都重新 `sum(chunks)`、`b"".join(chunks)`、UTF-8 decode 與 JSON parse，大 response 會重複複製與解析。
- Client 收到超過上限的 response 時先丟 `ValueError`，之後被 generic `Communication error` 包裝；Agent 看不到穩定的 `RESPONSE_TOO_LARGE` transport classification。
- FIN/reset、invalid JSON 與其他 protocol failure最後都被轉成 generic `Exception`；無法可靠區分 reconnect、fix request 或禁止 replay。

### Recommended transport sequence

1. 先加入 fragmentation、truncation、timeout、FIN-after-send、non-ASCII、request/response limit 與兩個 JSON object coalescing tests。
2. 以 `bytearray` 與 running byte count 取代 chunks 的重複 sum/join；不改 wire contract。
3. 加入 typed transport exceptions，至少攜帶 `code`、`phase`（`connect` / `send` / `receive` / `decode`）、`request_sent` 與 `retry_safe`。Outer MCP layer 再轉 stable envelope。
4. 若要採 length-prefixed framing，先增加 protocol version/negotiation 與 rolling-upgrade tests；client 與 extension 必須同時支援舊 JSON-completion framing。不得在 V6 adapter refactor 中順便切換 framing。

Write 在 `sendall` 開始後發生 timeout 或 connection loss，application state 都是 unknown。Typed exception 不得宣稱 automatic retry safe；只能依相同 idempotency key、job status 或 operation-specific read-back 恢復。

## 2. V6Adapter decomposition boundary

`IsaacAdapterV6` 必須繼續作為 `IsaacAdapterBase` 的 concrete facade。Handlers 目前直接呼叫 adapter public methods，tests 也直接建構、patch 與檢查 `IsaacAdapterV6`；因此不能靠動態 `__getattr__` delegation 隱藏 contract。

建議內部結構：

```text
IsaacAdapterV6 facade
├─ V6RuntimeContext       shared engine getter, stage/timeline lifecycle
├─ BackendRuntime         capability matrix and backend guards
├─ SceneRuntime           stage, prim, transform, discovery, asset reference
├─ RobotRuntime           articulation cache, joint state/command/drive
├─ MotionRuntime          IK, trajectory store, update subscription, cancel
├─ PhysicsRuntime         scene, params, body, group, joint, state
├─ SensorRuntime          camera/lidar caches, render request, lifecycle
├─ MaterialRuntime        visual/physics material and binding
└─ SimulationRuntime      play/pause/stop/step/state and governed scripts
```

Facade 保留每個 explicit method，內容只委派到 runtime component。這可維持 ABC conformance、handler call sites、type hints、monkeypatch targets 與 public MCP contract。

### 與原提案七個 Runtime 的差異

- `GraphRuntime` 目前不在 `v6.py`；OmniGraph 邏輯在 `handlers/graphs.py` 並直接使用 `omni.graph`/USD。硬塞進 adapter 會創造新的 layer coupling。
- `HumanRuntime` 同樣主要在 `handlers/humans.py`，不應先建立空的 adapter component。
- `IntegrationRuntime` 範圍過大。ROS 2、Replicator 與 human workflow 都已有 domain handler；adapter 內實際可獨立的是 material、asset import、lighting 與 governed script/runtime primitives。

Graph/Human 可以在 handler refactor 時建立 domain service，但不是第一輪 V6 facade extraction 的目標。

### Shared-state hazards

- Timeline Stop 同時清除 articulation cache 與 sensor wrappers；subscription ownership 必須集中在 context/facade，不能讓兩個 component 各自重複訂閱。
- Motion jobs 持有 update subscription 與 trajectory state；必須整組搬移，不能把 planning 與 execution 的 state 拆散。
- Sensor lifecycle 的一部分實作在 `IsaacAdapterBase.release_sensor` / `release_all_sensors`，目前直接依賴 V6 sensor caches。抽取前要先用 component protocol 或 facade properties 解除此隱性 coupling。
- Physics helpers 同時存在 base 與 V6。先決定哪些是跨版本 policy、哪些是 6.x API bridge，避免把相同行為複製到 component。

### Safe extraction order

1. 建立 characterization tests：列出 facade public callable set，並對 handler 常用 methods 驗證 delegated result/exception 不變。
2. 抽出無長期 mutable state 的 `SceneRuntime`，facade explicit delegation；offline suite 全綠。
3. 抽 `MaterialRuntime`，再抽 `PhysicsRuntime`；保留 base shared policy。
4. 先建立 shared lifecycle context，再整組抽 `SensorRuntime`。
5. 整組抽 `RobotRuntime` 與 `MotionRuntime`，驗證 timeline stop cache reset、job cancellation 與 subscription cleanup。
6. 最後抽 `SimulationRuntime` 與 `BackendRuntime`；執行 Isaac Sim 6.0.1 guarded live regression。

每一步只搬一個 state owner，禁止同時重新命名 public methods、改 response payload 或改 handler semantics。

## 3. Oversized handler boundaries

| Handler | First internal extraction | Public boundary retained |
|---|---|---|
| `graphs.py` | ScriptNode source/recompile；graph snapshot/rollback；runtime diagnostics | 現有 command handler functions |
| `sensors.py` | payload encoder/artifact/chunk policy；Camera service；LiDAR service | 現有 sensor handlers 與 error codes |
| `stage_composition.py` | stage snapshot/restore；composition query；metadata/attribute authoring | 現有 stage composition handlers |
| `humans.py` | ownership registry；spawn/nav validation；behavior lifecycle | 現有 human handlers |
| `capabilities.py` | declarative feature records與 runtime probe projection | `get_capabilities` schema |

先抽 pure helper/service，之後才調整 dispatcher registration。這樣 failure envelope、ownership guard 與 read-back 留在原 handler 邊界，降低 contract drift。

## 4. Verification gates

每個 refactor slice 必須通過：

- public tool inventory `--check` 無變化；
- adapter abstract-method conformance 與 handler structure tests；
- Python 3.10/3.11/3.12 offline suite；
- Windows/Linux launcher tests；
- response/error code contract tests；
- package wheel clean smoke install；
- 最終合併前才執行 Isaac Sim 6.0.1 guarded live suite，包含 operation read-back、cleanup、TCP health、Kit process/log/dump evidence。

此研究不授權啟動 Isaac Lab MCP；Isaac Lab 仍是獨立後續階段。
