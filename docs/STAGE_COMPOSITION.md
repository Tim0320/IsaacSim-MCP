# Stage、layer、USD composition 與語意資料契約

本契約對應 implementation task item 15。Isaac Sim 6.0.1 MCP 提供 12 個 named tools，處理 Stage lifecycle、layer stack、reference/payload、variant、`UsdSemantics.LabelsAPI`、typed attribute 與 atomic batch。

## Named tools

| Tool | 寫入 | 主要契約 |
|---|---:|---|
| `new_stage` | 是 | 預設只 preview；實際建立要求 `scratch_stage=true`、`scratch_root`、timeline stopped。 |
| `open_stage` | 是 | 只接受 `scratch_root` 內的本機 USD；預設只 preview；失敗時還原原 Stage layer snapshot。 |
| `save_stage_as` | 是 | 只寫入 `scratch_root`；禁止覆寫目前來源；既有 target 預設拒絕；先輸出同資料夾暫存檔、重開驗證，再 atomic replace。 |
| `get_stage_composition` | 否 | 回 root layer、完整 layer stack、composition arcs、variant、semantics、metadata 與 scoped prim count。可用 `root_path` 限制 prim traversal。 |
| `edit_sublayer` | 是 | `add|remove`；add 要求可讀 USD layer；寫入後比對 `subLayerPaths`，失敗還原 root layer。 |
| `edit_composition_arc` | 是 | `reference|payload` 的 `add|clear`；payload 另有 `load|unload`；保存 layer 與 load rules 供 rollback。 |
| `set_variant_selection` | 是 | 先驗證 variant set 與 selection 名稱；寫入後讀回；失敗還原原 selection。 |
| `get_semantic_labels` | 否 | 讀取 6.0.1 `SemanticsLabelsAPI:<taxonomy>`，也辨識 legacy `SemanticsAPI`。 |
| `set_semantic_labels` | 是 | 以 taxonomy 加入或覆寫唯一、非空字串 labels；使用 `UsdSemantics.LabelsAPI` 並精確讀回。 |
| `get_typed_attribute` | 否 | 回 type、JSON-safe value 與 authored state。 |
| `set_typed_attribute` | 是 | explicit type、有限數值、預設禁止覆寫；既有 attribute 不可改 type；失敗還原 layer snapshot。 |
| `apply_stage_batch` | 是 | 最多 100 個 layer/arc/variant/semantic/attribute operations；預設只 preview；任一步失敗時整批還原 root、session layer 與 payload load rules。 |

全部寫入都要求 timeline stopped。`new_stage`、`open_stage` 與 `save_stage_as` 還要求 explicit scratch guard。這些限制不接受以 `execute_script` 成功、文件 MCP `9904` 回應或 preview 成功取代 live read-back。

## Preview 與 scratch guard

Lifecycle tools 的 `preview` 預設為 `true`。Preview 只驗證 guard、路徑、來源存在性、target collision 與 operation shape，不修改 Stage 或檔案。

實際執行 `new_stage`、`open_stage`、`save_stage_as` 時必須同時設定：

```json
{
  "scratch_stage": true,
  "scratch_root": "C:\\Temp\\isaacsim-mcp-task-3-5",
  "preview": false
}
```

`scratch_root` 必須是已存在的本機資料夾；`path` 經 canonical resolve 後必須仍位於該資料夾。`open_stage` 與 `save_stage_as` 只接受 `.usd`、`.usda`、`.usdc`。目前來源檔永遠不能成為 save-as target，即使 `overwrite=true`。未授權覆寫時以同資料夾 hard-link 安裝暫存檔，若 target 在檢查後才出現仍會 fail closed；明確 `overwrite=true` 才使用 atomic replace。

`readback_root_path` 可縮小 `open_stage`、`save_stage_as` 與 batch 的回傳範圍。這只限制 prim traversal，不省略 root layer、layer stack 或 Stage metadata。

## Typed attribute

支援 scalar/tuple：

`bool`、`int`、`int64`、`float`、`double`、`string`、`token`、`asset`、`float2`、`float3`、`double2`、`double3`、`color3f`、`quatf`、`matrix4d`。

支援 array：

`bool[]`、`int[]`、`int64[]`、`float[]`、`double[]`、`string[]`、`token[]`、`asset[]`。

浮點輸入必須有限。Tuple 長度固定；`quatf` 使用 `[real, i, j, k]`；`matrix4d` 使用 row-major 16 個數值。回傳會轉成 JSON number/string/array，不回傳不可序列化的 `Gf` 或 `Sdf` object。

## Batch transaction

`apply_stage_batch.operations[*].operation` 只接受：

- `edit_sublayer`
- `edit_composition_arc`
- `set_variant`
- `set_semantics`
- `set_attribute`

Stage lifecycle 與檔案輸出不允許放進 batch。它們會改變 Stage identity 或產生外部 side effect，無法由單一 layer transaction 完整復原。

`preview=true` 逐項驗證目前 Stage 狀態。`preview=false` 在第一個 apply 前保存 root layer、session layer 與 payload load rules。任一步失敗回 `BATCH_ROLLED_BACK`，`readback.rolled_back=true`，且先前 operation 的 authored value 必須不存在或回到原值。

## Stable error codes

| Code | 意義 |
|---|---|
| `SCRATCH_STAGE_REQUIRED` / `SCRATCH_ROOT_REQUIRED` | Lifecycle 寫入缺少 explicit scratch guard。 |
| `INVALID_SCRATCH_ROOT` / `SCRATCH_ROOT_NOT_FOUND` | scratch root 無法解析或不是既有資料夾。 |
| `PATH_OUTSIDE_SCRATCH_ROOT` | canonical path 逃出允許資料夾。 |
| `STAGE_FILE_NOT_FOUND` / `INVALID_STAGE_EXTENSION` | open/save 路徑無效。 |
| `SOURCE_OVERWRITE_FORBIDDEN` / `TARGET_EXISTS` | 來源覆寫或未授權 target 覆寫。 |
| `TIMELINE_NOT_STOPPED` | active timeline 下拒絕 composition 寫入。 |
| `SUBLAYER_NOT_FOUND` / `SUBLAYER_ALREADY_PRESENT` | subLayer 前置條件不符。 |
| `INVALID_ARC_TYPE` / `INVALID_ARC_ACTION` | composition arc contract 無效。 |
| `VARIANT_SET_NOT_FOUND` / `VARIANT_SELECTION_NOT_FOUND` | variant 不存在。 |
| `INVALID_SEMANTIC_LABEL` | taxonomy/labels shape 無效。 |
| `ATTRIBUTE_EXISTS` / `ATTRIBUTE_TYPE_MISMATCH` / `UNSUPPORTED_ATTRIBUTE_TYPE` | typed attribute 前置條件不符。 |
| `INVALID_BATCH` / `BATCH_TOO_LARGE` / `INVALID_BATCH_OPERATION` | batch shape 或 scope 無效。 |
| `BATCH_PREVIEW_FAILED` / `BATCH_ROLLED_BACK` | preview 拒絕，或 apply 已完整 rollback。 |

## Live acceptance

執行：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_stage_composition_live.py
```

Verifier 只在 temporary scratch files 與 `/World/MCP_Task_3_5` 操作。它會先保存目前 root/session layer，建立新 scratch Stage，驗證 subLayer、reference、payload load/unload、variant、LabelsAPI、scalar/array typed attribute、成功 batch 與失敗 batch rollback，再 save-as 並 reopen，比對 layer stack、composition arcs、variant、metadata、semantic labels與 prim count。最後復原原 root/session layer，核對 prim count、timeline、Kit process 與 TCP `8766`。

離線 regression suite 要明確排除 `tests/test_integration.py`。該檔案會在偵測到 live `8766` 時直接建立 Camera、LiDAR、robots 並播放 simulation，屬於 destructive live integration。它不能與一般 unit suite 混跑，也不能替代本 verifier 的 scratch snapshot/restore、read-back 與 health gate。
