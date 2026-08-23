# Isaac Sim 6.0.1 MCP 深度實作 Task

> 本文件是 `D:\Dev\isaacsim-mcp` 的單一實作清單。先完成 Isaac Sim MCP，再另案處理 Isaac Lab MCP。

## 專案基準

- 專案目錄：`D:\Dev\isaacsim-mcp`
- GitHub origin：`https://github.com/Tim0320/IsaacSim-MCP.git`
- 建立 task 時基準：`main` / `092456e4fffba0096846ab384bf4a99026e03a2d`
- 固定執行環境：`C:\isaacsim`，Isaac Sim `6.0.1-rc.7+release.42383.32955d8d.gl`
- Live 控制路由：Isaac Sim extension TCP `8766`
- `isaac-sim-mcp` 的 `9904` 僅供文件查詢，不視為 live stage 控制驗證
- 目前 MCP 共註冊 53 個 named tools；既有 42-tool 歷史報告為參考，新增工具仍需統一重跑
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

- [x] 0.3 新增 `get_capabilities` 與版本相容矩陣
  > 完成：新增 read-only `get_capabilities` named tool 與 `system.get_capabilities` extension command，schema version 為 `1.0`；回傳 MCP/extension 版本、Isaac Sim 版本、adapter generation、active physics backend、stage state、extension states、feature flags、unsupported arguments 與 sensor warm-up 狀態。
  > 限制呈現：`time_step`、`gpu_enabled`、RGB pixels、decoded LiDAR points 與 V6 LiDAR `config` 都回傳 machine-readable state/reason；Newton 未完成 live matrix 時保持 `unverified`。
  > startup 契約：`system.get_capabilities` 不受 stage pending gate 阻擋，stage 建立前後都能查詢；其他 stage-dependent commands 維持原保護。
  > 測試證據：專案離線測試 `152 passed, 1 deselected`，Ruff 全部通過；FastMCP 實際註冊 46 tools。
  > live 證據：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX；stage 建立前回 `stage_available=false`，建立後回 `true`，兩次查詢皆成功且沒有修改 stage。

- [x] 0.4 統一 MCP response 與 error schema
  > 現況：多數 tool 回傳 JSON 字串，各 handler 的 `status`、`message`、資料欄位與錯誤細節不完全一致。
  > 缺漏位置：`isaac_mcp/tools/*.py`、`isaac.sim.mcp_extension/.../handlers/*.py`、connection protocol。
  > 實作：定義 `status`、`code`、`message`、`data`、`warnings`、`command_id`、`timing`、`artifacts`、`readback`。
  > 驗收：所有 named tools 通過共同 schema test；partial/unsupported/timeout/cancelled 不得回報為普通 success。
  > 完成：extension router、TCP connection 與 FastMCP tool registration 都會產生 schema `1.0` envelope；rolling upgrade 仍可接收舊 `{status,result}` response。
  > 狀態契約：`success/error/partial/unsupported/timeout/cancelled` 分開，並提供 `STAGE_NOT_READY`、`UNKNOWN_COMMAND`、`INTERNAL_ERROR` 等穩定 code。
  > 測試證據：全部 46 個 named tools 通過共同 schema wrapper test；專案離線測試 `158 passed, 1 deselected`，Ruff 與 format check 通過。
  > live 證據：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX、46 commands；capabilities 與 scene info 具有完整欄位，未知 command 回 `UNKNOWN_COMMAND`；read-only 查詢前後 `prim_count=14`。

## Phase 1：Camera、LiDAR 與感測資料

- [x] 1. Camera RGB 資料回傳
  > 現況（已確認）：`capture_image` 有 `output_path` 時存檔；未指定時只回傳 `shape`，沒有 RGB pixels 或可讀取的 artifact handle。
  > 缺漏位置：`isaac_mcp/tools/sensors.py:66`、`isaac.sim.mcp_extension/isaac_sim_mcp_extension/handlers/sensors.py:57`，目前資料在 handler 被縮減。
  > 實作：增加 `return_mode=metadata|artifact|inline`；預設回傳 artifact，包含格式、dtype、shape、width、height、channels、frame/timestamp、camera prim 與校驗 hash。
  > 傳輸限制：`inline` 設大小上限；完整 RGB/RGBA 優先存 PNG 或 `.npy`，由受控 resource handle 取回。
  > 驗收：在 Isaac Sim 6.0.1 建立 scratch camera，play/warm-up 後取得非空影像；解碼後 dimensions、dtype、hash 與本機檔案一致。
  > 完成：`capture_image` 支援 `metadata|artifact|inline`，預設以原子寫入產生受控 PNG artifact；回傳 image metadata、pixel SHA-256、artifact handle/path、PNG SHA-256，explicit `output_path` 保留相容。
  > 限制：inline 預設 1 MiB、hard cap 4 MiB；超限回 `INLINE_SIZE_LIMIT_EXCEEDED`。managed artifact 的 TTL、分塊讀取與清理已由 Phase 1 item 5 完成。
  > 測試證據：全部離線測試 `165 passed, 1 deselected`，Ruff 與 format check 通過；包含 PNG round-trip、artifact 原子寫入、base64 decode、hash 與上限測試。
  > live 證據：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX；scratch camera `/World/MCP_Task_1_1_Camera` 讀回成功，RGB `[48,64,3]`、`uint8`、frame 91；artifact/inline PNG 解碼後 dimensions 與 pixel SHA-256 一致，PNG SHA-256 也一致。

- [x] 1.1a. Timeline Stop 的雙 GPU auto CUDA 防護
  > 隔離結論（2026-08-23）：Camera、sensor teardown、V6 STOP observer、socket server、MCP client、專案 module import、multi-GPU renderer 與 viewport 都不是必要觸發條件。完全不載入 IsaacSim-MCP 的 `kit.exe isaacsim.exp.full.kit --exec ...` 仍可重現。
  > native 證據：兩份獨立 minidump 都是 `EXCEPTION_ACCESS_VIOLATION`，讀取位址 `0x8`，fault 位址固定為 `PhysXGpu_64.dll+0xD5307`；該指令為 `jmp qword ptr [rax+8]` 且 exception context 的 `RAX=0`。backtrace 路徑為 `omni.timeline -> carb.eventdispatcher -> omni.stageupdate -> physicsumbrella -> omni.physx -> PhysXGpu_64.dll`。
  > 根因範圍：本機有兩張 CUDA GPU，未覆寫時 `/physics/cudaDevice=-1`。log 顯示 PhysX 先使用 active context 的 device 1，啟動期間又保留 device 0，Play 前再切回 device 1 並重建 CUDA context；Stop teardown 隨後落入空 callback/vtable。這是 Isaac Sim 6.0.1 / Omni Physics 110.1.13 的 auto-selection context migration 問題，不是 `capture_image` response 實作造成。
  > 已驗證 workaround：只加入 `--/physics/cudaDevice=0` 即可完成 Play、Stop 與 240 個後續 update；顯式 `--/physics/cudaDevice=1` 也通過，表示關鍵是固定 ordinal，並非特定 GPU 0。`--/renderer/multiGpu/enabled=False` 單獨無效。
  > standalone 對照：`SimulationApp` 成功的直接差異已確認為官方 `DEFAULT_LAUNCHER_CONFIG` 會把 `physics_gpu` 預設成 `0`，並轉成 `--/physics/cudaDevice=0`；一般 `isaac-sim.bat`/`kit.exe` 路徑沒有這個保護。
  > 官方依據：Omni Physics 110.1 說明 `/physics/cudaDevice` 預設 `-1` 並交由 NVIDIA Control Panel/active context 自動選擇；多 GPU 應明確指定 simulation GPU ordinal。Isaac Sim 6.0.0 `SimulationApp` 文件則明列 `physics_gpu=0`。參考 `https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.1/dev_guide/simulation_control/simulation_control.html`、`https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.simulation_app/docs/index.html`。
  > 已實作：Windows launcher 依優先序採用 raw Kit argument、`-PhysicsGpu`、`ISAAC_PHYSICS_GPU`，否則以 `nvidia-smi` 找出當下唯一的 `display_active=Enabled` GPU 並解析成明確 ordinal；無法唯一判定時才警告並 fallback 到 GPU 0。這不是永久固定 GPU 0。
  > 再發防護：launcher 原始碼保留醒目維護註解；`-1` 仍可顯式使用，但會直接警告 Isaac Sim 6.0.1、Timeline Stop 與 `PhysXGpu_64.dll` crash signature。renderer multi-GPU 不得視為替代修復。
  > 離線測試：`tests/test_run_isaac_sim_windows.py` 覆蓋 precedence、主要 GPU 偵測、probe failure fallback、query contract、raw 去重、`-1` 警告、無效值拒絕與 exit code，共 `16 passed`。
  > live 證據（2026-08-23）：launcher 依本機 `display_active=Enabled` 偵測為 `Physics CUDA device: 0 (active display GPU)`；原始 MCP Camera 1.1 scratch 流程完成 Play、RGB capture、Stop，frame 120、shape `[48,64,3]`、pixel/artifact/inline SHA-256 與 camera read-back 全數通過。Kit 內部再完成 240 次 `next_update_async()`；程序仍存活，新增 dump `0`，`EXCEPTION_ACCESS_VIOLATION` / `PhysXGpu_64.dll+0xD5307` signature `0`。

- [x] 2. Camera depth、segmentation、normals 與 calibration
  > 原始現況：typed MCP 只涵蓋基本 camera 建立與 RGB capture，缺少常用 annotator 與完整相機模型。
  > 原始缺漏位置：`tools/sensors.py`、`handlers/sensors.py`、V6 camera/Replicator annotator lifecycle。
  > 已實作：新增 `capture_camera_output` 與 `get_camera_calibration` named tools。V6 共用長生命週期 CameraSensor/render product，支援 depth、distance-to-image-plane、semantic/instance/instance-ID segmentation、normals、motion vectors，以及 intrinsic/extrinsic、projection、resolution 與 units。
  > 傳輸契約：`metadata|artifact|inline`；artifact 是受控 `.npy`，inline 是 raw little-endian bytes。每次回傳明確 annotator、dtype、shape、units、coordinate space、frame/timestamp、raw size/SHA-256 與 JSON-safe annotator info。
  > 錯誤契約：無效 output/return mode、尚未產生 frame、inline 超限與 V5/annotator unavailable 均回傳穩定 code；不以空陣列宣稱成功。
  > lifecycle 修復：Play transition 依 Isaac Sim 6.0.1 CameraSensor reference flow 呼叫 `timeline.commit()`；Play 中 frame 尚未就緒時等待正常 render tick，不再排程會 pause timeline 並觸發 sensor release 的 fallback render。
  > live 驗收（2026-08-23）：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX；`64x48` 七種輸出皆取得 frame，dtype/shape/units、raw 與 `.npy` hashes 全數通過。已知 cube 的 depth/normals 非零，semantic label `mcp_task_1_2_target` 與 instance-ID prim `/World/MCP_Task_1_2_Target` 可讀回；intrinsic、camera-to-world/world-to-camera、projection、meters-per-unit 可讀回；scratch prim 全數清除。
  > 離線驗收：Task 1.2 focused tests `74 passed, 1 deselected`；排除 live/destructive 與本 sandbox Git-for-Windows shell 問題的 suite `193 passed, 1 deselected`；Ruff、format check、`git diff --check` 通過。完整 suite 另有既有 backup-script tests `2` 項因 sandbox 的 `git-submodule` 找不到 `git-sh-setup` 失敗，與 Camera 變更無關。
  > 驗證腳本：`scripts/verify_camera_outputs_live.py`。完整輸出契約：`docs/CAMERA_OUTPUTS.md`。

- [x] 3. LiDAR point cloud 資料回傳
  > 現況（已確認）：V6 adapter 已能取得 point cloud，但 handler 最後只回傳 `point_count`，XYZ points 被丟棄。
  > 缺漏位置：`handlers/sensors.py:126-146`、`adapters/v6.py` 的 RTX LiDAR 讀取路徑、`tools/sensors.py` response schema。
  > 實作：輸出 XYZ，並在可用時加入 intensity、range、azimuth、elevation、object/semantic ID；大型資料存 `.npy`、`.npz` 或 PCD artifact。
  > 驗收：warm-up 後 point count 大於 0；artifact row count 等於 `point_count`，座標系、units、timestamp、sensor pose 可讀回。
  > 已實作：`get_lidar_point_cloud` 支援 `metadata|artifact|inline`，預設回受控 `.npz`；fields 內含 Cartesian `points`、range、azimuth、elevation，以及 GMO 可用時的 intensity 與 128-bit object ID high/low。每個 `.npy` member 都有 dtype、shape、units、size 與 raw SHA-256；semantic ID 無 direct GMO field，因此明確列為 unavailable。
  > V6 修正：以 `FULL` auxiliary output 建立 LiDAR，掛載 `generic-model-output` 與 `stable-id-map` annotators；依官方公式把 GMO spherical azimuth/elevation/range 轉成 Cartesian meters，避免把角度與距離誤標為 XYZ。
  > live 驗收（2026-08-23）：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、PhysX；取得 134,880 points，七個 fields 的 row count、dtype/shape/units、raw hashes 與 NPZ hash 全數通過。coordinate frame=`sensor`、timestamp/frame、pose `[0,0,1]` 可讀回；stable object ID 成功解析到已知 scratch cube；Play、Stop 後 Kit/8766 存活，沒有新增 native dump，scratch prim 全數清除。
  > 離線驗收：Task 1.3 focused tests `72 passed, 1 deselected`；排除 live、固定 `C:\isaacsim` version-negative case 與缺少 `/bin/bash` 的 Unix launcher tests 後，專案 suite `201 passed, 1 deselected`；Ruff 與 `git diff --check` 通過。
  > 驗證腳本：`scripts/verify_lidar_point_cloud_live.py`。完整輸出契約：`docs/LIDAR_POINT_CLOUD.md`。

- [x] 4. LiDAR `config` 真正套用到 Isaac Sim 6.0.1
  > 現況（已確認）：建立 LiDAR 時接受 `config`，V6 路徑目前主要以 `Lidar(path=prim_path)` 建立，輸入設定沒有完整映射與 read-back。
  > 缺漏位置：`adapters/v6.py` 約 `1016-1026`、LiDAR tool/handler schema。
  > 實作：把支援設定映射到 Isaac Sim 6.0.1 RTX LiDAR schema；不支援欄位明確拒絕，禁止靜默忽略。
  > 驗收：使用至少兩組不同 horizontal/vertical FOV、resolution/rate/range 設定建立感測器，read-back 值與輸入一致。
  > 已實作：`create_lidar` 支援 named preset `config/variant`，或 generic `horizontal_fov_deg`、`vertical_fov_deg`、`horizontal_resolution_deg`、`vertical_resolution_deg`、`rotation_rate_hz`、`min_range_m`、`max_range_m`。模式衝突、未知欄位、無效範圍、無法整除與 sample budget 都以 stable error code 拒絕。
  > schema/read-back：generic 設定會 author `OmniSensorGenericLidarCoreAPI` 的 azimuth window、scan/tick/firing rate、range、emitter elevation/channel arrays；`get_lidar_config` 回傳 effective values 與 raw USD attributes。Isaac Sim 6.0.1 的 emitter channel ID 使用 1-based；partial-FOV 使用 per-tick output，避免完整 360° accumulation 無法發布 frame。
  > live 驗收（2026-08-23）：A=`120x20°`、`1x2°`、`10 Hz`、`0.5–40 m`，read-back 一致並取得 33 points；B=`180x30°`、`0.5x5°`、`20 Hz`、`1–80 m`，read-back 一致並取得 262 points。`100°/3°` 回 `LIDAR_HORIZONTAL_RESOLUTION_NOT_DIVISIBLE` 且未建立 prim；Play、Stop 與 scratch cleanup 通過。
  > 驗證腳本：`scripts/verify_lidar_config_live.py`。完整契約：`docs/LIDAR_CONFIG.md`。

- [x] 5. 共用 artifact 資料傳輸層
  > 現況：影像與 point cloud 沒有統一的大型資料 transport、保存期限、清理與 hash 契約。
  > 缺漏位置：MCP server resource/provider、extension 暫存區、tools response schema。
  > 實作：受控 artifact 根目錄、不可猜測 ID、MIME/dtype/shape/size/hash、TTL、分塊讀取、刪除與容量上限；路徑必須防止 traversal。
  > 驗收：影像與 LiDAR 共用同一契約；超過限制會回明確錯誤；artifact 可下載、驗 hash、過期並安全清理。
  > 已實作：新增共用 managed store 與 `get_artifact_info`、`read_artifact`、`delete_artifact`、`cleanup_artifacts` 四個 named tools。handle 為 192-bit random `artifact://managed/<opaque-id>`；metadata 包含 MIME、format、dtype/shape、size、SHA-256、建立/到期時間與 producer 欄位。Camera PNG/NPY 與 LiDAR NPZ 已改用同一 writer；explicit `output_path` 保留為 `managed=false`、`handle=null`。
  > 安全與限制：root、TTL、單檔/總容量、chunk 上限可由環境變數設定；輸入必須為正整數。handle 使用完整格式驗證，sidecar path 必須留在 root；寫入採 atomic replace，並提供 `ARTIFACT_TOO_LARGE`、`ARTIFACT_CAPACITY_EXCEEDED`、`ARTIFACT_CHUNK_LIMIT_EXCEEDED` 等 stable codes。
  > live 驗收（2026-08-23）：Isaac Sim `6.0.1-rc.7`、`IsaacAdapterV6`、53 commands。Camera PNG 1,087 bytes 與 LiDAR NPZ 1,248 bytes 均用 512-byte chunks 下載重組，完整 SHA-256 一致；traversal、1,025-byte chunk limit、delete、15 秒 TTL expiry、cleanup 與 scratch prim 清理全數通過。
  > 驗證腳本：`scripts/verify_artifact_transport_live.py`。完整契約：`docs/ARTIFACT_TRANSPORT.md`。

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

- [ ] 25. 目前 53 個 tools 的統一 Isaac Sim 6.0.1 live 報告
  > 現況：歷史 42-tool 報告為 38 passed、2 partial、2 external-config blocked；目前新增的 NVIDIA asset、human、capability、LiDAR config 與 artifact transport 工具未納入同一輪 53-tool live matrix。
  > 缺漏位置：`docs/ALL_TOOLS_TEST_REPORT.md` 與新的 machine-readable result artifact。
  > 實作：每個 tool 記錄用途、前置條件、input、read-back、結果、限制、Kit log、artifact/hash；外部 API key 阻塞與程式缺陷分開。
  > 驗收：53 個現有 tools 加上本 task 後續新增 tools 全部有逐項證據；pass/partial/blocked/unsupported 定義固定，禁止只有總數。

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
