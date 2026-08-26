# Gripper 與 mobile-base controller profiles

Task 2.4 提供六個高階 named tools。所有會寫入控制 target 的呼叫都必須帶入明確
`profile`；handler 會先比對 articulation 的完整 joint name 與 joint type，任何一項不符
就回 `CONTROLLER_PROFILE_MISMATCH`，且不套用部分命令。

## Named tools

| Tool | 參數 | 行為 |
|---|---|---|
| `list_controller_profiles` | 無 | read-only 列出可用 profile 與限制 |
| `set_gripper_width` | `prim_path`, `profile`, `width_m` | 設定兩指之間的總寬度（meter） |
| `open_gripper` | `prim_path`, `profile` | 套用 profile 的 open width |
| `close_gripper` | `prim_path`, `profile` | 套用 profile 的 closed width |
| `set_mobile_base_velocity` | `prim_path`, `profile`, `forward_mps`, `lateral_mps=0`, `yaw_radps=0` | 設定 base twist；非零命令要求 timeline playing |
| `stop_mobile_base` | `prim_path`, `profile` | 將 profile 中所有 wheel velocity targets 設為零並立即讀回 |

非零 mobile-base target 會持續存在，直到新 target、`stop_mobile_base` 或其他 controller
覆寫。工作流程必須在成功送出移動命令後安排 stop；不能把 MCP request 結束視為停止。

## Isaac Sim 6.0.1 profiles

| Profile | 綁定條件 | 映射與限制 |
|---|---|---|
| `franka_parallel_gripper` | `panda_finger_joint1/2`，prismatic | total width `0–0.08 m`，兩側各為 `width/2` |
| `nvidia_jetbot_differential` | `left_wheel_joint`, `right_wheel_joint`，revolute | wheel radius `0.03 m`、wheel base `0.1125 m`；不接受 lateral velocity |
| `nvidia_kaya_holonomic` | `axle_0/1/2_joint`，revolute；COM prim `/base_link/control_offset` | 由 USD wheel geometry 與 Isaac Sim `HolonomicController` 計算 wheel targets |

Jetbot differential 映射為：

```text
left_radps  = (forward_mps - yaw_radps * wheel_base_m / 2) / wheel_radius_m
right_radps = (forward_mps + yaw_radps * wheel_base_m / 2) / wheel_radius_m
```

Kaya 不把 mecanum/omni wheel geometry 寫死在 MCP profile；V6 adapter 使用
`HolonomicRobotUsdSetup` 從 USD 讀取 wheel radius、position、orientation 與 roller angle，再交由
`HolonomicController` 計算。這條路徑需要
`isaacsim.robot.experimental.wheeled_robots`；extension 未啟用時 capability 不得宣稱支援。

## 回傳與錯誤契約

成功 response 會包含 `profile`、實際 joint names/indices、command 或 requested width、計算後
wheel/finger targets，以及 immediate joint target read-back。常用穩定 code：

- `CONTROLLER_PROFILE_NOT_FOUND`：未知 profile。
- `CONTROLLER_PROFILE_KIND_MISMATCH`：把 gripper profile 用於 mobile base，或反之。
- `CONTROLLER_PROFILE_MISMATCH`：joint name/type 與 profile 不一致，`applied=false`。
- `GRIPPER_WIDTH_OUT_OF_RANGE`、`BASE_VELOCITY_LIMIT_EXCEEDED`：超出 profile 限制。
- `PROFILE_DOES_NOT_SUPPORT_LATERAL_VELOCITY`：differential base 收到非零 lateral velocity。
- `TIMELINE_NOT_PLAYING`：timeline 非 playing 時送出非零 base target。
- `HOLONOMIC_GEOMETRY_INVALID`：USD mecanum joints/geometry 與 profile 不一致，未套用命令。
- `MOBILE_BASE_STOPPED`：全部 wheel velocity target 已讀回為零。

`stop_mobile_base` 只驗證 target 已歸零；慣性、接觸或其他 controller 仍可能讓 measured wheel/base
速度短暫非零。安全停止應另由應用層讀取 measured joint/base state，並設定 timeout。

## Live verifier

```powershell
\.venv\Scripts\python.exe scripts\verify_controller_profiles_live.py
```

verifier 會先 read-only 檢查 Stage。只要存在非 baseline、非 task fixture prim，就回
`SCRATCH_STAGE_REQUIRED` 並在任何 `Stop`、clear、create 或 target write 之前結束。空白 scratch
Stage 才會建立 Franka、Jetbot、Kaya，驗證 gripper mapping、profile mismatch atomicity、兩種 base
target/joint/base read-back 與 stop postcondition，最後只刪除自己的 fixture namespace。

V6 adapter 建立 Warp command arrays 時必須使用 Articulation 的 physics device，不得使用 process-current
Warp device。雙 GPU session 中兩者可能不同；錯誤 device 可能回 allocation failure，該次 runtime 應視為
失效並在重新啟動後才重跑 live verifier。

2026-08-24 的乾淨重啟 scratch run 已完成最終驗收。Franka `0.08/0.03/0.0 m` total width mapping、
profile mismatch target atomicity、Jetbot 與 Kaya wheel target/measured velocity read-back，以及兩者 stop
後全零 target 均通過。Isaac Sim 6 experimental holonomic controller 可能直接回 ndarray，也可能回含
`joint_velocities` 的 action；adapter 會正規化兩種格式並依 USD setup joint names 重排。cleanup 後三個
robot、ground plane 與 physics scene 全 absent，timeline stopped，Kit/TCP、run log、native dump gate 通過。
