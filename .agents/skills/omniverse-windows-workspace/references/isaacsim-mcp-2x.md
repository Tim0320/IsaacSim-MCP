# IsaacSim-MCP Robot control 2.x

Use this reference for Phase 2 Robot control work in
`docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`.

## Numbering map

| Research label | Task item | Capability | Named tools | Contract | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 2.1 | Phase 2 item 7 | Complete V6 joint state and atomic position/velocity/effort commands | `get_joint_state`, `set_joint_command` | `docs/ROBOT_JOINT_CONTROL.md` | `scripts/verify_robot_joint_control_live.py` |
| 2.2 | Phase 2 item 8 | Atomic V6 drive gains, limits, and drive type | `set_joint_drive_config`, `get_joint_config` | `docs/ROBOT_JOINT_DRIVE_CONFIG.md` | `scripts/verify_robot_joint_drive_config_live.py` |
| 2.3 | Phase 2 item 9 | Lula IK, RRT/C-space trajectories, bounded non-blocking jobs | `compute_ik`, `plan_joint_trajectory`, `execute_trajectory`, `cancel_motion`, `get_motion_status` | `docs/MOTION_CONTROL.md` | `scripts/verify_motion_control_live.py` |

## 2.3 invariants

- IK is calculation-only and must report achieved position/orientation error.
- Lula IK does not support collision avoidance; always report collision unchecked.
- Only RRT may report a collision-checked path. Task 2.3 registers no USD scene
  obstacles, so report count 0 and `scene_obstacles_included=false`.
- C-space spline generation is deterministic but is not collision-aware.
- Warm start, random seed, max iterations, elapsed time, and timeout must be explicit.
- `execute_trajectory` returns immediately; Kit update callbacks advance jobs.
- Active states are queued/running/paused. Terminal states are completed,
  cancelled, failed, and timeout. A robot may have only one active job.
- Live acceptance requires deterministic IK, end-effector error, RRT result,
  pause/resume completion, cancel, timeout, finite read-back, and scratch cleanup.

## 2.2 invariants

- Require a stopped timeline before drive authoring.
- Validate the complete selector and every field before the first write.
- Numeric fields are finite, non-negative, float32-representable values.
- Report revolute gains per radian, not raw USD per-degree attributes.
- Snapshot selected fields and rollback already-written fields on apply error.
- Treat rollback failure as partial with unknown applied state.
- `max_velocity` is PhysX-only because it uses `PhysxJointAPI`; Newton remains
  partial and unverified for USD DriveAPI fields until a dedicated live run.
- Current support claims require before/after read-back, invalid request
  atomicity, active-timeline rejection, scratch cleanup, TCP/log/dump evidence.

## 2.1 invariants

- Resolve the canonical repository as `D:\Dev\IsaacSim-MCP` and preserve its
  worktree and verified backup before editing.
- Use joint names or zero-based DOF indices, never both. Preserve caller order.
- Validate every selector, value, duplicate, range, and value count before the
  adapter command. Invalid input must report `applied=false`.
- Revolute units are radians, radians/second, and newton-meters. Prismatic units
  are meters, meters/second, and newtons.
- V6 measured effort comes from projected joint forces. Effort command read-back
  comes from the current DOF effort array.
- V6 experimental Articulation subset setters require `dof_indices`; `indices`
  selects articulation rows and must not be used for a DOF subset.
- Effort control requires reapplying `set_dof_efforts` every simulation update.
  A single MCP call is one command update, not a persistent controller.
- If apply succeeds and read-back fails, report partial completion with
  `applied=true`; do not falsely claim the write was rejected.
- Current live support claims require a scratch articulation, Play/Pause or
  step evidence, target and measured read-back for all three modes, invalid-name
  atomicity, cleanup, TCP survival, and log/native-dump review.

## Recorded 2.1 evidence

The 2026-08-24 Isaac Sim `6.0.1-rc.7` PhysX run verified a 56-command registry
and a 9-DOF Franka fixture. Position, velocity, and effort targets matched the
requested float32 values; measured position, velocity, and projected effort
were finite after physics updates. Invalid-name atomic rejection, Stop-first
deletion, scratch absence, Kit/TCP survival, fixed active-display GPU selection,
run-scoped logs, and zero new native dumps passed. Treat this as historical
evidence and rerun the verifier before making a current claim later.

## Recorded 2.2 evidence

The 2026-08-24 PhysX run verified a 57-command registry and the five drive
fields on `panda_joint1` of a 9-DOF Franka. Stiffness, damping, max force, max
velocity, and force-to-acceleration drive type changes matched float32
read-back. Negative-value, unknown-name, and active-timeline requests applied
nothing and preserved the complete snapshot. Scratch cleanup, stopped timeline,
Kit/TCP survival, active-display GPU selection, zero error-like run logs, and
zero new native dumps passed. Newton max velocity remains unsupported and its
other DriveAPI fields remain unverified.

## Recorded 2.3 evidence

The 2026-08-24 Isaac Sim `6.0.1-rc.7` PhysX run produced functional evidence for 62 commands and
motion-generation extension `8.2.9`. Franka IK reached `7.363885225415161e-7 m`
position error and repeated exactly with warm start and seed 17. RRT returned a
collision-checked valid path. The non-blocking job passed pause/resume to
completion, explicit cancellation, and a 1 ms deadline timeout, followed by
fixture-namespace cleanup. A later guard found pre-existing non-task prims and
refused to clear or write the Stage. This is not scratch-isolated final evidence;
rerun on a user-provided empty Stage before checking task 2.3 complete.
