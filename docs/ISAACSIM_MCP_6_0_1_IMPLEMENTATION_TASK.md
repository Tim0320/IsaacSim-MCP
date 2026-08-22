# Isaac Sim 6.0.1 MCP 深度實作 Task

> 本文件是 `D:\Dev\isaacsim-mcp` 的單一實作清單。先完成 Isaac Sim MCP，再另案處理 Isaac Lab MCP。

## 專案基準

- 專案目錄：`D:\Dev\isaacsim-mcp`
- GitHub origin：`https://github.com/Tim0320/IsaacSim-MCP.git`
- 建立 task 時基準：`main` / `092456e4fffba0096846ab384bf4a99026e03a2d`
- 固定執行環境：`C:\isaacsim`，Isaac Sim `6.0.1-rc.7+release.42383.32955d8d.gl`
- Live 控制路由：Isaac Sim extension TCP `8766`
- `isaac-sim-mcp` 的 `9904` 僅供文件查詢，不視為 live stage 控制驗證
- 目前 MCP 共註冊 45 個 named tools；既有 42-tool 歷史報告為參考，新增工具仍需統一重跑
- 建立本文件時 `8766` 未啟動，因此本次只整理程式碼與既有測試證據，沒有修改 live stage
- 備份根目錄：`E:\碩士論文\backups\isaacsim-mcp`

## 狀態與證據標記

- `[x]`：已完成，而且有可讀回證據
- `[~]`：實作或驗證進行中
- `[ ]`：尚未實作或尚未完成驗證
- `已確認`：可由目前程式碼、測試或既有 live 報告直接證明
- `待 live 驗證`：只能在 Isaac Sim 6.0.1 的拋棄式測試 stage 證明

## 全域完成條件

每個功能只有同時符合以下條件才可改成 `[x]`：

1. 核心能力有具名、typed MCP tool；不得只靠 `execute_script` 宣稱支援。
2. MCP tool schema、extension handler、V6 adapter、錯誤格式與文件一致。
3. 具備 unit test、schema contract test，以及必要的 Isaac Sim 6.0.1 live integration test。
4. 會修改場景的測試只能在新建的 scratch stage 執行，寫入後必須 read-back；不得對使用者目前場景執行 `clear_scene`。
5. 大型感測資料使用檔案或 resource handle 傳輸，不把無上限 pixels/point cloud 塞入單一 JSON response。
6. 不在 Git、log、task、測試輸出或備份內保存 API key、token 或其他 credential。
7. 每輪變更前後都要備份、產生 manifest、驗證 hash，並記錄 Git HEAD 與 dirty/untracked 狀態。
8. PhysX 必須完成驗證；Newton 未實測的功能要回傳明確 capability 狀態，不得默認等同 PhysX。

## Phase 0：保存、能力盤點與共同契約

- [x] 0.1 建立目前 GitHub 專案的可還原基準
  > 現況：`main` 與 `origin/main` 均位於 `092456e4fffba0096846ab384bf4a99026e03a2d`，建立備份時 worktree 乾淨。
  > 備份：`E:\碩士論文\backups\isaacsim-mcp\20260822-220737-pre-task\isaacsim-mcp-all.bundle`
  > 驗證：`git bundle verify` 成功；SHA-256 為 `04AD09555ADC105791A53E64256CAF68FF13B2DF7F2C9D2AC72F5B7EF04E5B33`。
  > 完成定義：保留 manifest、hash 與安全還原指令，不覆寫目前工作目錄。

- [x] 0.2 建立可重複使用的專案備份流程
  > 完成：新增 `scripts/backup_project.ps1`，記錄 remote、branch、HEAD、submodule、Git LFS、dirty status；提交歷史使用完整 bundle，staged/unstaged 使用 binary patch，安全的 untracked files 使用獨立快照。
  > 安全限制：備份根目錄必須位於 repo 外；credential-like、Git ignored、cache/build 與超過限制的 untracked files 不複製；每次使用唯一目錄，不 commit、不 push、不覆寫舊備份。
  > 還原驗證：在新的系統暫存目錄 clone bundle、依序套用 staged/unstaged patch、還原 untracked/LFS/line-ending overrides，再逐檔比對 SHA-256；失敗會保留 `BACKUP_FAILED.txt` 並回傳非零狀態。
  > 測試證據：`tests/test_backup_project_script.py` 驗證 clean repo、同時含 staged/unstaged/untracked 的 dirty repo、credential/cache/oversized 排除，以及 repo 內備份路徑拒絕；專案離線測試為 `145 passed, 1 deselected`，Ruff 全部通過。

- [ ] 0.3 新增 `get_capabilities` 與版本相容矩陣
  > 現況：tool 可被列出，但 client 無法可靠得知 Isaac 版本、active physics backend、必要 extension、支援參數與已知限制。
  > 缺漏位置：`isaac_mcp/tools/`、extension command registry、`adapters/base.py`、`adapters/v6.py`。
  > 實作：回傳 server/extension 版本、Isaac Sim 版本、adapter、PhysX/Newton、啟用 extension、tool feature flags、unsupported arguments 與 sensor warm-up 狀態。
  > 驗收：schema contract 固定；缺 extension 或不支援功能時回傳 machine-readable reason，不以成功訊息掩蓋 ignored parameter。

- [ ] 0.4 統一 MCP response 與 error schema
  > 現況：多數 tool 回傳 JSON 字串，各 handler 的 `status`、`message`、資料欄位與錯誤細節不完全一致。
  > 缺漏位置：`isaac_mcp/tools/*.py`、`isaac.sim.mcp_extension/.../handlers/*.py`、connection protocol。
  > 實作：定義 `status`、`code`、`message`、`data`、`warnings`、`command_id`、`timing`、`artifacts`、`readback`。
  > 驗收：所有 named tools 通過共同 schema test；partial/unsupported/timeout/cancelled 不得回報為普通 success。

## Phase 1：Camera、LiDAR 與感測資料

- [ ] 1. Camera RGB 資料回傳
  > 現況（已確認）：`capture_image` 有 `output_path` 時存檔；未指定時只回傳 `shape`，沒有 RGB pixels 或可讀取的 artifact handle。
  > 缺漏位置：`isaac_mcp/tools/sensors.py:66`、`isaac.sim.mcp_extension/isaac_sim_mcp_extension/handlers/sensors.py:57`，目前資料在 handler 被縮減。
  > 實作：增加 `return_mode=metadata|artifact|inline`；預設回傳 artifact，包含格式、dtype、shape、width、height、channels、frame/timestamp、camera prim 與校驗 hash。
  > 傳輸限制：`inline` 設大小上限；完整 RGB/RGBA 優先存 PNG 或 `.npy`，由受控 resource handle 取回。
  > 驗收：在 Isaac Sim 6.0.1 建立 scratch camera，play/warm-up 後取得非空影像；解碼後 dimensions、dtype、hash 與本機檔案一致。

- [ ] 2. Camera depth、segmentation、normals 與 calibration
  > 現況：typed MCP 只涵蓋基本 camera 建立與 RGB capture，缺少常用 annotator 與完整相機模型。
  > 缺漏位置：`tools/sensors.py`、`handlers/sensors.py`、V6 camera/Replicator annotator lifecycle。
  > 實作：新增 depth、distance-to-image-plane、semantic/instance segmentation、normals、motion vectors；提供 intrinsic/extrinsic、projection、resolution 與 units。
  > 驗收：每種輸出都有明確 dtype/shape/units，並以已知幾何與 prim ID 做 read-back；缺 annotator 時回傳 capability error。

- [ ] 3. LiDAR point cloud 資料回傳
  > 現況（已確認）：V6 adapter 已能取得 point cloud，但 handler 最後只回傳 `point_count`，XYZ points 被丟棄。
  > 缺漏位置：`handlers/sensors.py:126-146`、`adapters/v6.py` 的 RTX LiDAR 讀取路徑、`tools/sensors.py` response schema。
  > 實作：輸出 XYZ，並在可用時加入 intensity、range、azimuth、elevation、object/semantic ID；大型資料存 `.npy`、`.npz` 或 PCD artifact。
  > 驗收：warm-up 後 point count 大於 0；artifact row count 等於 `point_count`，座標系、units、timestamp、sensor pose 可讀回。

- [ ] 4. LiDAR `config` 真正套用到 Isaac Sim 6.0.1
  > 現況（已確認）：建立 LiDAR 時接受 `config`，V6 路徑目前主要以 `Lidar(path=prim_path)` 建立，輸入設定沒有完整映射與 read-back。
  > 缺漏位置：`adapters/v6.py` 約 `1016-1026`、LiDAR tool/handler schema。
  > 實作：把支援設定映射到 Isaac Sim 6.0.1 RTX LiDAR schema；不支援欄位明確拒絕，禁止靜默忽略。
  > 驗收：使用至少兩組不同 horizontal/vertical FOV、resolution/rate/range 設定建立感測器，read-back 值與輸入一致。

- [ ] 5. 共用 artifact 資料傳輸層
  > 現況：影像與 point cloud 沒有統一的大型資料 transport、保存期限、清理與 hash 契約。
  > 缺漏位置：MCP server resource/provider、extension 暫存區、tools response schema。
  > 實作：受控 artifact 根目錄、不可猜測 ID、MIME/dtype/shape/size/hash、TTL、分塊讀取、刪除與容量上限；路徑必須防止 traversal。
  > 驗收：影像與 LiDAR 共用同一契約；超過限制會回明確錯誤；artifact 可下載、驗 hash、過期並安全清理。

- [ ] 6. Sensor lifecycle 與刪除一致性
  > 現況：Camera/LiDAR wrapper、render product、annotator 與 USD prim 的生命週期可能不同；刪除 prim 後仍可能被持有的 wrapper 在後續 tick 重建或殘留資源。
  > 缺漏位置：`handlers/objects.py` 的 delete flow、V6 adapter camera/LiDAR cache、Replicator detach/destroy。
  > 實作：新增 typed `delete_sensor` 或在 `delete_object` 偵測 sensor，先 detach annotator、destroy render product、移除 cache，再刪 prim。
  > 驗收：刪除後連續 step 多次，prim、render product、annotator、adapter cache 均不存在；重建同一路徑成功且不重複 callback。

## Phase 2：Robot 控制

- [ ] 7. 完整 joint state 與 command mode
  > 現況：named tools 主要提供 joint position target 與基本 read-back，缺 velocity、effort、measured state 與 command mode。
  > 缺漏位置：`tools/robots.py`、`handlers/robots.py`、V6 articulation adapter。
  > 實作：提供 joint names/index mapping、position/velocity/effort state，以及 position/velocity/effort target；支援 subset 與明確 units。
  > 驗收：每種 mode 在 scratch articulation 執行，step 後讀回 target 與 measured state；錯誤 joint name 不得部分套用。

- [ ] 8. Drive gains、limits 與控制器參數寫入
  > 現況：joint/drive 設定讀取能力高於寫入能力，缺 stiffness、damping、max force、velocity、drive type 的 typed setter。
  > 缺漏位置：robot tool/handler、USD drive schema adapter。
  > 實作：新增 `set_joint_drive_config`，支援 atomic validate-then-apply 與完整 read-back。
  > 驗收：修改前後讀回一致；輸入超出限制時不留下半套用狀態；PhysX/Newton 支援差異要出現在 capability。

- [ ] 9. IK、trajectory、motion planning 與 controller lifecycle
  > 現況：沒有 named tool 可建立/選擇 controller、求 IK、產生 trajectory、執行、暫停、取消與查詢 job。
  > 缺漏位置：目前 `isaac_mcp/tools/` 沒有 motion/controller 模組。
  > 實作：先建立最小 `compute_ik`、`plan_joint_trajectory`、`execute_trajectory`、`cancel_motion`、`get_motion_status`；依 capabilities 掛接 Isaac Sim 可用 motion generation stack。
  > 驗收：對固定 robot fixture 驗證 end-effector 誤差、collision result、timeout/cancel 與 deterministic seed；禁止阻塞 MCP worker 無限等待。

- [ ] 10. Gripper 與 mobile base 常用操作
  > 現況：可透過底層 joints 或 `execute_script` 組合，但缺少穩定、高階 named tools。
  > 缺漏位置：robot tool registry、controller presets、fixture tests。
  > 實作：新增 open/close/set width，以及 differential/holonomic velocity command；所有 preset 都要顯式綁定 robot profile。
  > 驗收：未匹配 profile 時拒絕執行；有 profile 時讀回 joint/base 狀態與停止 postcondition。

## Phase 3：Physics、材料與 USD stage

- [ ] 11. 完成 `set_physics_params`
  > 現況（已確認）：gravity 可套用；`time_step` 與 `gpu_enabled` 雖出現在 tool signature，handler 明確列為 unsupported/ignored。
  > 缺漏位置：`tools/simulation.py:113-130`、`handlers/simulation.py:106-140`、V6 physics scene adapter。
  > 實作：對 Isaac Sim 6.0.1 寫入 simulation/physics time step 與 GPU dynamics/broadphase 相關設定；先驗證 stage state，必要時 stop 後再改。
  > 驗收：設定後由 physics scene 與 runtime API 雙重 read-back；實際 step timing 符合設定；不能套用時回 unsupported，不得回 success。

- [ ] 12. PhysX 與 Newton 能力分流
  > 現況：adapter 介面宣稱 backend-neutral，但 reset/step、articulation、sensor 等路徑尚無完整 Newton live matrix。
  > 缺漏位置：`adapters/base.py`、`adapters/v6.py`、simulation/robot integration tests。
  > 實作：每項功能標示 `physx_supported`、`newton_supported`、`untested`；backend-specific code 由 adapter 封裝。
  > 驗收：PhysX 全矩陣通過；Newton 只把真正 live 通過的項目標成 supported，其餘保持明確 untested/unsupported。

- [ ] 13. Rigid body、collider、mass 與 joint authoring
  > 現況：基礎物件操作可建立 prim，但完整 physics schema authoring 仍常需 `execute_script`。
  > 缺漏位置：objects/simulation tools、handlers 與 adapter physics authoring API。
  > 實作：typed tools 支援 rigid/static body、collider approximation、mass/density、collision group，以及 fixed/revolute/prismatic joint 建立與查詢。
  > 驗收：輸入 schema、units、axis、limits 可讀回；step 後以可預期的運動/約束結果驗證。

- [ ] 14. 補齊 physics material MCP schema
  > 現況（已確認）：handler/adapter 已接受 `static_friction`、`dynamic_friction`、`restitution`，MCP tool 介面沒有完整暴露這些參數。
  > 缺漏位置：`isaac_mcp/tools/materials.py:35`、`handlers/materials.py:45-58`、V6 adapter material API。
  > 實作：在 named tool schema 暴露參數、範圍與 units；增加 material query/read-back。
  > 驗收：建立兩組不同材料並綁定物件，USD attr read-back 一致，再用簡單滑動/彈跳 fixture 驗證行為差異。

- [ ] 15. Stage、layer、USD composition 與語意資料
  > 現況：scene tools 著重列舉、查詢、export/clear 等基本操作，缺少完整 open/new/save、layer、reference/payload、variant、semantic label 與 arbitrary attr 契約。
  > 缺漏位置：`tools/scene.py`、scene handler、V6 stage/USD adapter。
  > 實作：分批加入 new/open/save-as、subLayer、reference/payload load/unload、variant selection、semantic labels、typed attr get/set、batch transaction。
  > 安全限制：任何 destructive stage 操作需要 scratch-stage guard、預覽與 read-back；不得默認覆寫來源 USD。
  > 驗收：另存新檔後重開，比對 layer stack、composition arcs、variant、metadata 與 prim count。

## Phase 4：OmniGraph、ROS 2、Replicator 與 Humans

- [ ] 16. OmniGraph 完整 lifecycle
  > 現況：已有 create/edit Action Graph；缺 query、delete、connect/disconnect、enable/disable、runtime status 與穩定的 ScriptNode reload 契約。
  > 缺漏位置：`tools/graphs.py`、`handlers/graphs.py`、graph adapter 與 live tests。
  > 實作：新增 list/get/delete graph、node/edge query、connect/disconnect、enabled state、evaluation error；ScriptNode inline/file 模式分開定義。
  > 驗收：建立、修改、執行、停用、刪除全流程 read-back；既有 inline ScriptNode edit 必須在目前 commit 重跑，不沿用舊 partial 結果。

- [ ] 17. ROS 2 named workflows
  > 現況：沒有 ROS 2 專用 named tools，現有能力需手動 graph 或 script 組裝。
  > 缺漏位置：tool registry 尚無 `ros2.py`，缺 extension/capability check 與 domain/QoS schema。
  > 實作：先提供 extension/domain 狀態、clock、TF、joint state、camera/LiDAR publisher 建立與刪除；QoS 使用明確 profile。
  > 驗收：無 ROS 2 環境時安全回報 prerequisite；有環境時用外部 subscriber 驗證 topic、frame_id、frequency 與 message schema。

- [ ] 18. Replicator 與 synthetic data generation
  > 現況：除基本 camera capture 與 `spawn_human` 外，缺 randomizer、writer、trigger、annotation export 與 job lifecycle 的 typed 控制。
  > 缺漏位置：tool registry 尚無完整 replicator/SDG 模組。
  > 實作：新增 writer 設定、frame count、trigger、randomization graph、start/cancel/status、輸出 manifest；沿用共用 artifact 契約。
  > 驗收：固定 seed 可重現；輸出 frame、annotation、metadata 數量一致；取消後不殘留 writer/trigger。

- [ ] 19. Human lifecycle 與 runtime 行為控制
  > 現況：已有 `spawn_human`；移動、朝向、idle、刪除、行為更新與 NavMesh status 仍依賴 `reload_script`/`execute_script`。
  > 缺漏位置：`tools/humans.py`、`handlers/humans.py`、IRA/People/NavMesh integration。
  > 實作：新增 list/get/delete human、set target/look/idle/behavior、NavMesh bake/status；把 external prerequisites 放入 capability。
  > 驗收：spawn 後能查詢與控制，刪除後相關 prim/graph/script state 均清除；缺 extension 或資產時回可行動的 prerequisite error。

## Phase 5：安全性、可靠性與可觀測性

- [ ] 20. 限縮 `execute_script` escape hatch
  > 現況：`execute_script` 與 `reload_script` 可補足 named tools 缺口，也能任意改動 live stage、檔案與執行環境。
  > 缺漏位置：`tools/simulation.py:219`、`handlers/simulation.py:145`、V6 adapter execution path。
  > 實作：增加 capability/政策開關、允許的 cwd roots、timeout、輸出上限、command ID、audit log；預設提示先使用 named tools。
  > 驗收：超時、超量輸出、越界 cwd 與禁用狀態均 fail closed；停止或取消後不繼續背景修改 stage。

- [ ] 21. Command ID、idempotency、transaction 與 read-back
  > 現況：連線可發 command，但 destructive/retry 操作缺一致的去重、原子性與 postcondition 契約。
  > 缺漏位置：client connection、extension server/dispatcher、所有 write handlers。
  > 實作：每次寫入有 `command_id`；支援 idempotency key、validate/apply/read-back、batch transaction 與 partial rollback 報告。
  > 驗收：重送相同 request 不重複建立 prim；錯誤 batch 可證明哪些步驟未套用、已回復或需人工處理。

- [ ] 22. Timeout、取消、job status 與 response limits
  > 現況：長時間 motion、SDG、資產載入與 sensor capture 缺一致的非同步 job 與取消模型。
  > 缺漏位置：protocol、server dispatcher、long-running handlers。
  > 實作：`start/get_status/cancel` 契約、deadline、progress、result artifact；限制 request/response/log 大小。
  > 驗收：client 斷線或取消後工作能進入可預期終態；同一 job 可重查且結果不重複執行。

- [ ] 23. Log correlation 與診斷資訊
  > 現況：已有 Kit log/print 擷取，但尚未對所有 tool 統一關聯 command、stage、frame、backend 與 extension 狀態。
  > 缺漏位置：simulation log buffer、dispatcher、tool response metadata。
  > 實作：每筆 log 帶 command ID、timestamp、severity、source；提供 bounded query，敏感值遮罩。
  > 驗收：故意觸發錯誤時，可由 MCP response 追到對應 Kit warning/error；log 不包含 credential 或無上限 stdout。

## Phase 6：測試、報告與發布

- [ ] 24. 建立完整測試金字塔與 scratch-stage harness
  > 現況：已有 unit/structure/integration tests；既有 integration 會連 `8766` 並含 `clear_scene`，不能直接對使用者 live stage 執行。
  > 缺漏位置：`tests/test_integration.py`、fixture/launcher、CI Windows matrix。
  > 實作：拆成純 unit、schema contract、offline adapter mock、destructive scratch-stage live tests；每次 live run 建立唯一 stage/prim namespace，結束後 read-back 清理。
  > 驗收：unit/contract 可離線重跑；live harness 拒絕非 scratch stage；Windows launcher 測試與 Unix Bash 測試分平台執行。

- [ ] 25. 目前 45 個 tools 的統一 Isaac Sim 6.0.1 live 報告
  > 現況：歷史 42-tool 報告為 38 passed、2 partial、2 external-config blocked；目前新增的 NVIDIA asset/human 工具未納入同一輪 45-tool live matrix。
  > 缺漏位置：`docs/ALL_TOOLS_TEST_REPORT.md` 與新的 machine-readable result artifact。
  > 實作：每個 tool 記錄用途、前置條件、input、read-back、結果、限制、Kit log、artifact/hash；外部 API key 阻塞與程式缺陷分開。
  > 驗收：45 個現有 tools 加上本 task 新增 tools 全部有逐項證據；pass/partial/blocked/unsupported 定義固定，禁止只有總數。

- [ ] 26. 文件、相容性、migration 與 release gate
  > 現況：已有 README 與部分測試報告，但新增 response/artifact/capability 契約會影響 client。
  > 缺漏位置：README、tool docs、protocol/version 文件、changelog。
  > 實作：補 Isaac Sim 6.0.1 安裝、8766 啟動、tool inventory、限制、schema 範例、migration、備份/還原、PhysX/Newton matrix。
  > 驗收：全新 checkout 可依文件完成 secret-free setup；release 前執行 backup、tests、live matrix、Git diff review，未經使用者授權不 push/merge/tag。

## 延後範圍：Isaac Lab MCP

- [ ] D1. Isaac Lab MCP 獨立研究與實作
  > 狀態：明確延後，現在不新增 Isaac Lab tools，也不把 Isaac Lab API 混入 Isaac Sim live MCP。
  > 啟動條件：Isaac Sim MCP 的必要 named tools、共同 schema、artifact transport、備份流程與 6.0.1 live matrix 完成並經使用者確認。
  > 後續方向：另建 Isaac Lab capability/task，涵蓋 environment、manager、training、policy、checkpoint、evaluation 與 job lifecycle；沿用本文件已穩定的 protocol，而不是共用不明確的 tool 名稱。

## 每次工作紀錄模板

```text
[日期時間]
Task：
變更前 Git HEAD / status：
變更前備份路徑 / SHA-256 / verify：
修改檔案：
測試指令與結果：
Isaac Sim 6.0.1 live stage（scratch path / prim namespace）：
read-back 證據：
Kit warning/error：
未完成或外部阻塞：
變更後備份路徑 / SHA-256 / verify：
```
