# Isaac Sim MCP Phase D: V6 Adapter Decomposition Task

這是 `IsaacAdapterV6` facade decomposition 的 repository task 與執行紀錄。目標是逐步移動 Isaac Sim 6.x runtime integration，維持所有 MCP-facing contract、handler call shape、stable error、capability、read-back、rollback 與 lifecycle semantics。

## 不變條件

- MCP tool names、tool input schema、extension command names不變。
- Response envelope、stable `status`／error codes、`command_id`、`idempotency_key` 不變。
- Capability/backend matrix、ownership、read-back、rollback、job lifecycle semantics 不變。
- Handler 只依賴 `IsaacAdapterV6` facade，不直接依賴 `v6_runtime` component。
- V5 adapter、TCP framing、typed transport exceptions與新功能不在 Phase D 範圍。
- 一次只移動一個 state owner；每個 extraction slice 都能單獨回復。
- 不建立空的 domain runtime、generic `utils.py`、mixin hierarchy 或 dynamic `__getattr__` delegation。

## D.0 Baseline and extraction map

- [x] 核對 canonical checkout、branch、origin、HEAD 與 clean worktree。
- [x] 建立 verified pre-change backup，包含 restore comparison。
- [x] 記錄 `v6.py` bytes、lines、SHA-256、public/private method surface。
- [x] 確認 source-derived inventory 為 128 tools，tracked inventory未漂移。
- [x] 執行完整 offline suite，結果為 `397 passed / 70 deselected`。
- [x] 保存 exact public adapter method characterization test。
- [x] 依實際 source 建立 domain extraction map，不用目標檔名反推責任。

Baseline checkout：

| Field | Value |
|---|---|
| Git HEAD | `1dfbc6e012f422e90bca71c57cfe1a2eca74a281` |
| Branch / origin | `main` / `https://github.com/Tim0320/IsaacSim-MCP.git` |
| `v6.py` | 3,366 lines / 163,385 bytes |
| `v6.py` SHA-256 | `7D7DF11D7C822A5FCEBAA3B51F0E60C5EDB8ADF63951700ED688A1E8838872CD` |
| Class methods | 85 total / 64 public / 21 private or dunder |
| Source tool inventory | 128 |
| Offline baseline | 397 passed / 70 deselected |
| Current strict live snapshot | 117 pass / 11 blocked / 0 fail; 128 source/runtime tools |
| Pre-change backup | `E:\碩士論文\backups\isaacsim-mcp\20260826-193444-246-pre-phase-d-decomposition` |
| Backup restore | `True`; 264 files compared |

`Current strict live snapshot` 只適用於上述 exact checkout 與當次 Isaac Sim 6.0.1 runtime，不代表 extraction 後仍通過。

### Current method ownership

| Domain | Current line region | Public facade methods | Private helpers / state |
|---|---:|---|---|
| composition/lifecycle | 92–329 | `get_backend_capability_matrix` | `_engine`; version detection; timeline-stop subscription |
| scene/assets | 330–557 | `get_stage`, `get_assets_root_path`, `discover_environments`, `load_environment`, prim/reference/transform/list/info/size methods | no long-lived cache |
| robots | 558–942, 1294–1626 | articulation discovery/create, joint info/state/positions/command/drive/config, holonomic wheel velocities | `_articulations`, `_new_articulation`, `_runtime_articulation`, joint/drive helpers |
| motion | 943–1293 | `compute_ik`, `plan_joint_trajectory`, `execute_trajectory`, `cancel_motion`, `get_motion_status`, `shutdown_motion` | `_motion_trajectories`, `_motion_jobs`, update subscription and callbacks |
| physics | 1627–2272 | world/context/scene/config, body/group/joint/state methods | physics-world/reset helpers plus inherited base physics helpers |
| sensors | 2273–2805 | Camera/LiDAR create/capture/calibration/config/frame methods | Camera/LiDAR caches, metadata, render request, lifecycle coupling to base adapter |
| materials/lighting/assets | 2806–2972 | material create/apply, light create/modify, clone, URDF import | no shared long-lived cache observed |
| simulation/scripts | 2973–3366 | play/pause/stop/step/state, execute/reload script | execution namespace inherited from base; reset/lifecycle coordination |

### Boundary correction from source evidence

`graphs.py`、`ros2.py`、`replicator.py` 與 `humans.py` 目前主要直接使用 USD/Kit/domain APIs；`IsaacAdapterV6` 沒有對應 public domain methods。Phase D 不先建立空的 `GraphRuntime`、`Ros2Runtime`、`ReplicatorRuntime`、`HumanRuntime`。要移動這些 handler-owned APIs，必須先通過 D.8 boundary gate，證明它是 raw runtime integration，並確認不會把 ownership、policy、job orchestration 或 response mapping下沉。

## D.1 RuntimeContext

- [x] 新增 `adapters/v6_runtime/context.py` 與 package export。
- [x] 只集中真實共用 facts：Isaac version、dynamic active backend、dynamic current Stage access。
- [x] 保留 backend 每次讀取 semantics，不在 constructor cache active engine。
- [x] 保留 Stage lookup timing與 exception behavior。
- [x] 保留 `_engine`、`get_stage` public/patch surface，改為 explicit forwarding。
- [x] 不移動 robot、motion、sensor caches；它們仍由各自未抽取的 owner持有。
- [x] 執行 context unit tests、adapter characterization、capability tests與完整 offline suite。
- [x] 因 runtime import/access path改變，執行 guarded read-only/live regression 後才能完成本項。

D.1 execution evidence：

| Item | Result |
|---|---|
| Added | `v6_runtime/__init__.py`, `v6_runtime/context.py`, `test_v6_runtime_context.py` |
| Moved facts | Version probe、dynamic backend probe、dynamic Stage lookup |
| Facade forwarding | `_engine` property與`get_stage()` signatures保留 |
| State not moved | articulation、motion、sensor caches與timeline subscription仍在facade |
| Focused tests | 64 passed |
| Full offline | 404 passed / 70 deselected |
| Tool inventory | 128，`--check` passed |
| Live reload | `hot_reload_extension.py` 成功重新註冊128 handlers |
| Live read-only | `simulation.get_state`: adapter 6 / PhysX / `6.0.1-rc.7`; all-tools 117 pass / 11 blocked / 0 fail |
| TCP health | `127.0.0.1:8766` listening after reload |

`v6.py` 在本 slice 同時由 repository pinned Ruff formatter正規化既有未格式化區塊；這些是 formatting-only diff，RuntimeContext behavior diff仍限於 constructor、`_engine` 與`get_stage`。

## D.2 CapabilityRuntime

- [x] 盤點 `get_backend_capability_matrix` 的 static evidence與 dynamic backend fact。
- [x] 抽出 `CapabilityRuntime`，但保留 facade method與 capability schema exact shape。
- [x] 不把 handler `get_capabilities` response composition移入 runtime。
- [x] 對 PhysX/Newton/unknown backend執行 exact matrix contract tests。
- [x] 驗證 repeated lookup沒有增加，Newton仍 fail closed。

D.2 execution evidence：

| Item | Result |
|---|---|
| Added | `v6_runtime/capabilities.py`, `test_v6_runtime_capabilities.py` |
| Moved method body | `get_backend_capability_matrix`; facade signature與doc contract保留 |
| Dependency | `CapabilityRuntime -> RuntimeContext`; base `_backend_capability` 以explicit callable注入 |
| Handler boundary | `handlers/capabilities.py` 未移動、未import `v6_runtime` |
| Focused tests | 67 passed，包含 PhysX/Newton guard與matrix semantics |
| Full offline | 407 passed / 70 deselected |
| Tool inventory | 128，`--check` passed |
| Live reload | 新 runtime modules依dependency順序 reload，128 handlers重新註冊 |
| Live read-only | all-tools 117 pass / 11 blocked / 0 fail；state/capability backend皆為 PhysX |
| Facade size after D.2 | 3,263 lines / 158,324 bytes；baseline為3,366 / 163,385 |

## D.3 SceneRuntime

- [x] 抽出 Stage/prim/reference/transform/discovery/size methods與單一 domain helpers。
- [x] `SceneRuntime` 只依賴 `RuntimeContext` 與現有明確 USD helper modules。
- [x] Facade 保留 12 個現有 scene/assets public method signatures。
- [x] 執行 scene/object/stage composition/assets/discovery tests。
- [x] 比對 return types、exceptions、side effects與 read-back輸入未變。

D.3 execution evidence：

| Item | Result |
|---|---|
| Added | `v6_runtime/scene.py`, `test_v6_runtime_scene.py` |
| Pre-slice backup | `E:\碩士論文\backups\isaacsim-mcp\20260826-200044-469-pre-phase-d-scene-physics`；restore comparison通過，包含當時dirty/untracked state |
| Moved operations | dynamic Stage、assets root、environment discovery/load、prim create/delete/reference/transform/list/info/size |
| Dependency | `SceneRuntime -> RuntimeContext` 與既有 `adapters/transforms.py`；沒有 Sensor/Physics/handler dependency |
| Cross-domain coordination | `delete_prim` 仍由 facade 先 `release_sensor`，再交由 SceneRuntime 刪除 prim |
| Facade contract | 12 個 public signatures保留；64-method characterization仍通過 |
| Focused tests | 26 passed；environment thumbnail/hidden-folder guards、transform helper與explicit forwarding均通過 |
| Full offline after D.3/D.4 | 437 passed / 70 deselected |
| Live read-back | D.4 scratch流程使用新 SceneRuntime建立、transform/read-back與刪除 `/World/MCP_Task_3_3`；最後 exact path absent |

## D.4 PhysicsRuntime

- [x] 先分類 base shared policy與 V6 API bridge，禁止複製 inherited helper behavior。
- [x] 抽出 PhysicsScene、params、body、collision group、joint與state methods。
- [x] 保留 atomic apply/rollback typed exceptions與 backend guards。
- [x] 執行 physics params/body/joint/material/state/backend tests。
- [x] 執行 guarded physics live verifier，確認 Stage mutation/read-back/cleanup未變。

D.4 execution evidence：

| Item | Result |
|---|---|
| Added | `v6_runtime/physics.py`, `test_v6_runtime_physics.py` |
| Moved operations | SimulationManager warm/reset bridge、world/context、PhysicsScene、atomic params、body、collision group、joint與physics state |
| Shared policy boundary | `PhysicsPolicyBridge` 以weak reference明確呼叫 `IsaacAdapterBase.configure_physics`、backend guard、scene lookup與gravity authoring；沒有複製 inherited behavior或形成 circular import |
| Dependencies | `PhysicsRuntime -> RuntimeContext, SceneRuntime, PhysicsPolicyBridge`；capability/backend policy仍由base bridge提供，handler仍只依賴facade |
| Atomicity | `PhysicsParamsApplyError.rollback_succeeded`、body rollback、invalid joint pre-apply rejection與Newton fail-closed semantics保留 |
| Focused tests | 115 passed；另含新的 facade forwarding與policy bridge tests |
| Full offline | 437 passed / 70 deselected |
| Tool / static gates | 128 tools，inventory `--check`、`ruff check .`、runtime/test targeted format check、verifier `py_compile`與`git diff --check`通過 |
| Live reload | Isaac Sim `6.0.1-rc.7` / PhysX；重新載入新components並註冊128 handlers |
| Physics authoring live | `verify_physics_authoring_live.py`通過body/group/fixed-revolute-prismatic joint、rollback、120 steps與read-back；verifier只清理由本次run產生的ground plane，保留pre-existing path |
| Physics params live | `verify_physics_params_live.py`通過120 Hz、GPU/MBP mapping、invalid/active-timeline atomic rejection、12 steps=`0.1 s`與baseline restore |
| Cleanup / health | scratch root與本次reload產生的`/World/groundPlane`均absent；Stage prim count回到15、timeline stopped、Kit PID 35476 responding、TCP 8766 listening、critical crash log matches 0 |
| Facade size after D.4 | 2,495 lines / 118,207 bytes；baseline為3,366 / 163,385 |

## D.5 SensorRuntime

- [ ] 先解開 `IsaacAdapterBase.release_sensor` 對 facade cache names的隱性依賴。
- [ ] Camera/LiDAR cache、metadata、render request與lifecycle整組搬移。
- [ ] 保留 timeline Stop teardown、sensor warm-up、frame readiness與annotator timing。
- [ ] Facade 保留全部 Camera/LiDAR public signatures與 sentinel behavior。
- [ ] 執行 Camera/LiDAR/artifact/sensor lifecycle offline tests。
- [ ] 執行 guarded sensor live verifier，包含 Stop後 updates、cleanup、TCP/Kit/log/dump evidence。

## D.6 RobotRuntime

- [ ] articulation cache、joint helpers與drive helpers整組搬移。
- [ ] 保留 timeline Stop cache invalidation與 runtime articulation refresh timing。
- [ ] RobotRuntime 不管理 motion trajectory/job state。
- [ ] 執行 robot joint/state/command/drive/controller tests。
- [ ] 執行 guarded robot live verifier與 operation-specific read-back。

## D.7 MotionRuntime

- [ ] planning config、IK、trajectory store、motion jobs與update subscription整組搬移。
- [ ] `MotionRuntime` 可以依賴 `RobotRuntime`，反向依賴禁止。
- [ ] 保留 non-blocking execution、cancel、terminal state與subscription cleanup。
- [ ] 不移入 MCP unified job manager semantics。
- [ ] 執行 motion/IK/trajectory/controller tests與 guarded live verifier。

## D.8 Handler-owned runtime boundary gate

- [ ] 分別盤點 Graph、ROS2、Replicator、Human handler中的 raw Isaac API、MCP policy與job/ownership code。
- [ ] 只有 raw runtime operation可候選移入 adapter component。
- [ ] 若 extraction 需要 handlers直接依賴 component、改 stable errors或同時改 orchestration，記錄並延後到 Phase F。
- [ ] 禁止為滿足目標目錄而建立空 module。
- [ ] 每個通過 gate 的 domain獨立 extraction、test、contract comparison與 live verification。

## D.9 Materials, simulation and final facade cleanup

- [ ] 根據實際 cohesion決定 material/lighting/assets 是否形成具名 runtime，禁止 `IntegrationRuntime` 垃圾桶。
- [ ] 抽出 simulation/script raw runtime時保留 sync/async、Kit scheduling與policy boundary。
- [ ] `v6.py` 最終只保留 composition root、explicit forwarding與真正跨-domain coordination。
- [ ] 禁止 dynamic forwarding；ABC conformance、introspection與 monkeypatch targets 必須保留。
- [ ] 更新 Architecture/Skill reference，只記錄完成後的實際結構。

## 每個 extraction slice 的 gate

1. 記錄 changed files、moved methods、moved state與dependency direction。
2. 執行 domain-specific tests與 public method characterization。
3. 執行完整 offline suite；不得新增 failure或修改 acceptance criteria。
4. 執行 tool inventory `--check`、Ruff、format與`git diff --check`。
5. 比對 MCP tool names/count、request/response schema、stable errors、capability與 lifecycle contracts。
6. runtime import/lifecycle/mutation改變時執行對應 guarded live verifier。
7. 建立 verified backup；commit/push 仍需使用者明確授權。

## Definition of Done

- [ ] `IsaacAdapterV6` 是 explicit facade/composition root，`v6.py` 明顯縮小。
- [ ] Domain components有單一 state owner、單向 dependencies且沒有 circular imports。
- [ ] RuntimeContext沒有 MCP policy；CapabilityRuntime沒有取代 high-level capability response。
- [ ] Handler 不感知 `v6_runtime` internal decomposition。
- [ ] 64 個 baseline public methods保持可用且 signatures/behavior不變。
- [ ] 128 source-derived tools與 generated inventory不變。
- [ ] Request/response/error/capability/idempotency/ownership/read-back/rollback/job semantics不變。
- [ ] Offline、contract、domain-specific、launcher、package與必要 live gates通過。
- [ ] 每個 extraction slice可以獨立 review與回復。
