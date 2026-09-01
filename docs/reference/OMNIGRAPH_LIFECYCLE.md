# OmniGraph lifecycle contract

Task 4.1 在 Isaac Sim 6.0.1 提供 12 個 Action Graph named tools，涵蓋 create、query、edit、connect、runtime control、ScriptNode reload、evaluate 與 delete。程式、offline contract 與專用 scratch live verifier 均已完成。

## Prerequisites

- Isaac Sim `6.0.1` 與 live MCP extension 必須可用。
- `omni.graph.core`、`omni.graph.action`、`omni.graph.scriptnode` 必須 enabled；`get_capabilities.data.feature_flags["omnigraph.lifecycle"]` 會依 extension state 回 `supported`、`unavailable` 或 `unknown`。
- 寫入前必須能讀取 timeline state。除緊急停用外，timeline 必須 stopped。
- graph/node/attribute target 必須使用 exact path，不做跨 graph fallback。

capability flag 同時宣告：

```json
{
  "query_readback": true,
  "preview_default_for_new_writes": true,
  "operation_specific_rollback": true,
  "enabled_state_runtime_only": true,
  "script_modes": ["inline", "file"],
  "graph_scoped_script_reload": true,
  "runtime_error_messages": true
}
```

## Tool inventory

| Tool | 類型 | 契約摘要 |
|---|---|---|
| `create_action_graph` | write | 建立 nodes、connections、values，或用 inline/file shortcut 建立 `OnPlaybackTick → ScriptNode`。既有介面，無 preview 參數。 |
| `edit_action_graph` | write | 原子設定既有 attributes 並新增 connections。既有介面，無 preview 參數。 |
| `list_action_graphs` | read | 列出 `root_path` 下的 graphs；預設包含 disabled graph。 |
| `get_action_graph` | read | 回傳 graph、nodes、edges、attributes；value/source 需明確 opt in。 |
| `delete_action_graph` | write | 預覽或刪除 exact graph，驗證 graph 與 backing prim 都不存在。 |
| `connect_action_graph` | write | 預覽或建立 exact source→target connection。 |
| `disconnect_action_graph` | write | 預覽或移除 exact source→target connection。 |
| `set_action_graph_enabled` | runtime write | 預覽或設定 enabled state；`enabled=false` 可在 playing 時緊急執行。 |
| `get_action_graph_status` | read | 回 graph/node enabled、timeline、compute count、messages 與 evaluation state。 |
| `configure_script_node` | write | 以 explicit inline/file mode 設定 exact ScriptNode。 |
| `reload_script_node` | write | 重新驗證 source 並重新編譯 exact ScriptNode，不做跨 graph fallback。 |
| `evaluate_action_graph` | runtime write | stopped timeline 下 synchronous evaluate，回傳 pre/post compute count 與 messages。 |

## Timeline and preview rules

所有 graph 寫入先驗證 timeline。`create_action_graph`、`edit_action_graph`、delete、connect、disconnect、enable、ScriptNode configure/reload 與 explicit evaluation 都要求 stopped timeline。

唯一例外是：

```text
set_action_graph_enabled(graph_path=..., enabled=false, preview=false)
```

這個操作可在 playing 時緊急停用 runaway graph。`enabled=true` 仍要求 stopped。timeline state 無法確認時回 `TIMELINE_STATE_UNAVAILABLE`；狀態不符回 `TIMELINE_NOT_STOPPED`。

新增的 delete/connect/disconnect/enabled/configure/reload writes 預設 `preview=true`。Preview 只驗證 exact target、source/state 與 prerequisite，成功 response 的 `data.preview=true`；要實際套用必須傳 `preview=false`。既有 create/edit tools 沒有 preview 參數，呼叫即寫入。

## Query and status

`list_action_graphs` 回傳 evaluator、pipeline stage、backing type、enabled、node/connection/ScriptNode counts。`get_action_graph` 再加上完整 nodes、edges 與 attributes。

- `include_values=false` 是預設，避免大量 runtime value。
- `include_script_source=false` 是預設，避免意外回傳大型或敏感 inline source。
- inline source 只有 opt in 時回傳。
- file source 回 canonical path、`file_exists`、mtime、bytes 與 SHA-256，不回檔案內容。

`get_action_graph_status` 回傳：

- graph/node enabled state；
- evaluator 與 pipeline stage；
- timeline state；
- graph/node compute count；
- node messages，含 `severity`、`message`、`node_path`；
- `evaluation_state=disabled|error|never_evaluated|success`；
- ScriptNode mode、source hash/path 與 initialized state。

`enabled` 由 OmniGraph runtime 的 `graph.set_disabled()` 控制。所有相關 response 都回 `runtime_state_persistent=false`；不得推論 USD save/reopen 或 Kit restart 後仍保持相同狀態。

## Connections

source/target 可用 graph-relative attribute path，handler 會解析成 full attribute path，並驗證兩端屬於同一 exact graph。

```text
connect_action_graph(
  graph_path="/World/ControlGraph",
  source_attr="OnPlaybackTick.outputs:tick",
  target_attr="ScriptNode.inputs:execIn",
  preview=false
)
```

建立既有 edge 回 `CONNECTION_ALREADY_EXISTS`；移除不存在 edge 回 `CONNECTION_NOT_FOUND`。Apply 後重新解析 attributes 並讀回 connection state。read-back 不符時執行 inverse edit；成功還原回 `GRAPH_TRANSACTION_ROLLED_BACK`，還原失敗回 `GRAPH_ROLLBACK_FAILED`。

`edit_action_graph` 也可新增 connections，但無 preview。需要 exact lifecycle、preview 或 disconnect 時應使用 dedicated tools。

## ScriptNode configure and reload

`configure_script_node` 用於指定新的 mode/source；`reload_script_node` 可保留 current mode/source，或原子換成新的 source。兩者都要求 exact `graph_path` 和 `node_path`。

`simulation.reload_script` 的 cross-graph file lookup 只檢查 `omni.graph.scriptnode.ScriptNode`。Render、SDG 與其他 OmniGraph nodes 不會被查詢不存在的 `inputs:scriptPath`；單一 malformed ScriptNode 也不會中止同 graph 後續 node 的掃描。

### Inline mode

```text
configure_script_node(
  graph_path="/World/ControlGraph",
  node_path="ScriptNode",
  mode="inline",
  inline_script="def compute(db):\n    return True",
  preview=false
)
```

Inline mode 要求 non-empty `inline_script`，禁止 `script_file`。

### File mode

```text
reload_script_node(
  graph_path="/World/ControlGraph",
  node_path="ScriptNode",
  mode="file",
  script_file="D:\\Dev\\IsaacSim-MCP\\scripts\\controller.py",
  preview=false
)
```

File mode 禁止 `inline_script`，只接受 resolve 成既有 regular file 的 `.py`。reload 時省略 `mode` 和 source，表示保留並重新驗證目前 node 的 mode/source。

Apply 流程：

1. snapshot `inputs:usePath`、`inputs:script`、`inputs:scriptPath`、`state:omni_initialized` 與 graph/node disabled state。
2. 暫時停用 graph。
3. 設定 exact mode/source。
4. 清除 `OgnScriptNodeDatabase` cache，並將 `state:omni_initialized=false`。
5. 讀回 mode 與 source path/hash，最後還原 graph enabled state。

成功 response 回 `compile_state=pending_evaluation`。這表示 source 已設定並要求 recompile；只有後續 evaluation/status 沒有 error message，才能宣稱 runtime compile/compute 成功。

## Explicit evaluation

`evaluate_action_graph` 只接受 enabled graph 與可 explicit evaluate 的 pipeline stage。它呼叫 `og.Controller.evaluate_sync(graph_path)`，並回傳每個 node 的 `compute_count_before`、`compute_count_after` 和 messages。

- disabled graph：`GRAPH_DISABLED`。
- prerender/postrender graph：`GRAPH_NOT_EXPLICITLY_EVALUABLE`，必須交由 render pipeline。
- node error message 或 evaluation exception：`GRAPH_EVALUATION_FAILED`，並保留 read-back messages。

一次 evaluate 成功只證明該次同步求值沒有回報 node error；不等於長時間 playback controller 已通過穩定性驗收。

## Delete and rollback

Delete 在 apply 前讀取 graph/node 狀態，暫時停用 graph，清除 ScriptNode compile cache，再執行：

```python
DeletePrimsCommand(paths=[graph_path], destructive=False, stage=stage)
```

一個 awaited Kit update 後必須同時確認 OmniGraph registry 與 backing USD prim 都不存在。Handler 執行於 Kit asyncio dispatcher 時只能 `await next_update_async()`，禁止同步呼叫 `app.update()` 重新進入 event loop。若刪除或 read-back 失敗，handler 呼叫同一 command 的 `undo()`、await 下一次 Kit update、重新取得 graph，還原原 enabled state並比較 node count。ROS 2 workflow create rollback與delete沿用同一 async lifecycle。

成功 response 的 `readback` 包含：

```json
{
  "graph_present": false,
  "prim_present": false
}
```

`DeletePrimsCommand` 的 undo 是 operation rollback，不是永久備份。Live verifier 仍必須使用 owned scratch namespace，並在 finally gate 確認 fixture absence。

## Response and stable errors

所有 tools 使用 schema `1.0` envelope。Write success 將目標放在 `data`，將 postcondition 放在 `readback`。Operation 失敗並完成還原時：

```json
{
  "status": "error",
  "code": "GRAPH_TRANSACTION_ROLLED_BACK",
  "readback": {"rolled_back": true}
}
```

rollback 本身失敗時使用 `GRAPH_ROLLBACK_FAILED` 與 `readback.rolled_back=false`，client 必須停止後續 mutation 並回報 graph 可能處於未知狀態。

| Code | 語意 |
|---|---|
| `TIMELINE_STATE_UNAVAILABLE` | 無法確認 timeline，拒絕寫入。 |
| `TIMELINE_NOT_STOPPED` | operation 要求 stopped timeline。 |
| `INVALID_GRAPH_PATH` | graph/node target 不是合法 exact USD prim path/scope。 |
| `GRAPH_ALREADY_EXISTS` / `GRAPH_NOT_FOUND` | create target 已存在，或 query/mutation target 不存在。 |
| `ATTRIBUTE_NOT_FOUND` / `NODE_NOT_FOUND` | exact attribute/node 不存在。 |
| `INVALID_CONNECTION` | edge 格式或 graph scope 無效。 |
| `CONNECTION_ALREADY_EXISTS` / `CONNECTION_NOT_FOUND` | edge precondition 不符。 |
| `INVALID_ENABLED_STATE` | enabled 不是 JSON boolean。 |
| `SCRIPT_MODE_CONFLICT` | inline/file mode 或 source 組合衝突。 |
| `SCRIPT_FILE_NOT_FOUND` | file mode path 無法解析為既有 `.py`。 |
| `SCRIPT_NODE_REQUIRED` | exact node 不是完整的 Isaac Sim 6.0.1 ScriptNode。 |
| `GRAPH_DISABLED` | disabled graph 不可 explicit evaluate。 |
| `GRAPH_NOT_EXPLICITLY_EVALUABLE` | graph 必須由 render pipeline evaluate。 |
| `GRAPH_EVALUATION_FAILED` | evaluate exception 或 node error message。 |
| `GRAPH_TRANSACTION_ROLLED_BACK` | apply/read-back 失敗，已完成 operation rollback。 |
| `GRAPH_ROLLBACK_FAILED` | apply 與 rollback 都失敗，state 可能未知。 |

## Verification status

Offline 已完成 tool registration、98-name inventory、capability flag、schema/forwarding、preview default、timeline guard、mode validation 與 rollback structure tests；排除 Windows launcher 與 destructive live integration 的完整 safe suite 為 `322 passed`，Ruff lint 與 `git diff --check` 通過。

2026-08-25 使用 [`verify_omnigraph_lifecycle_live.py`](../../scripts/verify_omnigraph_lifecycle_live.py) 完成專用 scratch live 驗收：

1. registry 為 98 commands；owned graph `/World/MCP_Task_4_1` 建立 3 nodes 與 1 條初始 edge。
2. list/get 與 exact connect/disconnect read-back 通過；duplicate edge 回 `CONNECTION_ALREADY_EXISTS`。
3. 短 Play/Stop 驗證 inline source `A→B→RECOVERED` 與 file source `C→D`。
4. stopped explicit evaluation 只增加 OnTick compute count，ScriptNode 維持 `0`。這符合 OnPlaybackTick 未觸發的語意，不會誤報 downstream ScriptNode 已執行。
5. disabled graph 的 compute count 固定為 `27`；runtime exception 可由 status 讀回 `evaluation_state=error`。
6. Delete 後 graph 與 backing prim 都不存在；最後 graph list 還原且 timeline stopped。

不可在 live `8766` 開啟時將 `tests/test_integration.py` 混入離線 regression suite。該 suite 會累積未 teardown Camera/LiDAR/robots，歷史上曾在後續 simulation play 進入 Replicator `reset_scenario()` 時造成 native crash。4.1 必須使用專用、具 ownership、teardown 與 health gate 的 verifier；offline tests、static inspection、documentation MCP `9904` 都不能替代 live stage 證據。
