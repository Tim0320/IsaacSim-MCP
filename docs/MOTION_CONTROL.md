# Motion control（Task 2.3）

Isaac Sim 6.0.1 的 MCP 現在提供五個 motion named tools：

- `compute_ik`：使用 NVIDIA Lula IK；只計算、不套用 joint command。
- `plan_joint_trajectory`：`rrt` 產生 collision-aware path，`cspace` 產生 deterministic time-optimal spline。
- `execute_trajectory`：建立 job 並立即返回，不阻塞 MCP worker。
- `cancel_motion`：停止後續 target 更新，保留最後 command target。
- `get_motion_status`：回傳 queued/running/paused/completed/cancelled/failed/timeout 與 progress。

## 嚴格能力邊界

`compute_ik` 使用的 `LulaKinematicsSolver` 不支援 obstacle collision avoidance，因此永遠回傳
`collision_check.checked=false`。`plan_joint_trajectory(planner="rrt")` 才回傳
`collision_check.checked=true`；目前 MCP 尚未把 USD scene obstacle 註冊到 Lula world view，response
會回 `scene_obstacles_included=false` 與 obstacle count 0，不得解讀為整個 Stage collision-free。`cspace` 只做
joint-space spline，不能當成 collision-free planning。

IK quaternion 採 `[w, x, y, z]`。位置單位是 meters，revolute joint 是 radians。Franka profile
使用七個 active arm joints，不包含兩個 finger joints。`random_seed` 與 warm start 會回傳供重現；
`max_iterations`、`timeout_ms` 均有上限，native solver 完成後也會核對 elapsed time。

`execute_trajectory` 依 Kit update callback 推進。timeline Stop/Pause 時 job 狀態為 `paused`，Play
後繼續；超過 deadline 轉成 `timeout`。同一 articulation 同時只允許一個 active job。

## Live 驗證

在 Isaac Sim 6.0.1、TCP 8766、scratch stage 執行：

```powershell
.\.venv\Scripts\python.exe scripts\verify_motion_control_live.py
```

腳本建立並清除 `/World/MCP_Task_2_3_Robot`，驗證 IK end-effector error、相同 seed 的 deterministic
結果、RRT collision result、non-blocking execute、pause/resume、cancel、timeout，以及 cleanup read-back。

2026-08-24 在乾淨重啟的 Isaac Sim `6.0.1-rc.7`／PhysX 完成最終驗收：registry `68`、motion
generation `8.2.9`、IK position error `7.363885225415161e-7 m`、seed `17` 重現、RRT
`checked/path_valid=true`、completed/cancel/1 ms timeout 均通過。cleanup 後 task robot、ground plane 與
physics scene 全 absent，timeline stopped，Kit/TCP 存活，當次 log 與 native dump gate 通過。
