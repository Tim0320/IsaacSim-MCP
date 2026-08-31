# IsaacSim-MCP Robot control 2.x

Use this reference for Phase 2 Robot control work in
`docs/research/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`.

## Contents

- [Retrieval workflow](#retrieval-workflow)
- [Numbering map](#numbering-map)
- [2.3 invariants](#23-invariants)
- [2.2 invariants](#22-invariants)
- [2.1 invariants](#21-invariants)
- [Recorded 2.1 evidence](#recorded-21-evidence)
- [Recorded 2.2 evidence](#recorded-22-evidence)
- [Recorded final 2.3 acceptance](#recorded-final-23-acceptance)
- [Task 2.4 controller profile invariants](#task-24-controller-profile-invariants)
- [Runtime lifecycle corrections](#runtime-lifecycle-corrections)
- [Recorded 2.4 read-only guard evidence](#recorded-24-read-only-guard-evidence)
- [Recorded 2.4 failed scratch rerun](#recorded-24-failed-scratch-rerun)
- [Recorded final 2.4 acceptance](#recorded-final-24-acceptance)

## Retrieval workflow

1. Identify the research label in the numbering map.
2. Read the linked contract for schema, units, prerequisites, limitations, and stable errors.
3. Inspect the linked verifier before changing implementation or making a live claim.
4. Read the matching invariant and recorded-evidence sections below.
5. Confirm the current checkbox and Phase boundary in the implementation task.

Recorded results are historical baselines. A current live claim requires a fresh guarded verifier run plus checkout, capability registry, backend/extensions, GPU, TCP, cleanup, process, log, and native-dump evidence.

## Numbering map

| Research label | Task item | Capability | Named tools | Contract | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 2.1 | Phase 2 item 7 | Complete V6 joint state and atomic position/velocity/effort commands | `get_joint_state`, `set_joint_command` | `docs/reference/ROBOT_JOINT_CONTROL.md` | `scripts/verify_robot_joint_control_live.py` |
| 2.2 | Phase 2 item 8 | Atomic V6 drive gains, limits, and drive type | `set_joint_drive_config`, `get_joint_config` | `docs/reference/ROBOT_JOINT_DRIVE_CONFIG.md` | `scripts/verify_robot_joint_drive_config_live.py` |
| 2.3 | Phase 2 item 9 | Lula IK, RRT/C-space trajectories, bounded non-blocking jobs | `compute_ik`, `plan_joint_trajectory`, `execute_trajectory`, `cancel_motion`, `get_motion_status` | `docs/reference/MOTION_CONTROL.md` | `scripts/verify_motion_control_live.py` |
| 2.4 | Phase 2 item 10 | Explicit-profile gripper and differential/holonomic mobile-base commands | `list_controller_profiles`, `set_gripper_width`, `open_gripper`, `close_gripper`, `set_mobile_base_velocity`, `stop_mobile_base` | `docs/reference/CONTROLLER_PROFILES.md` | `scripts/verify_controller_profiles_live.py` |

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

- Resolve the canonical repository as `F:\IsaacSim-MCP` and preserve its
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

## Runtime lifecycle corrections

The 2026-08-31 Q2 benchmark exposed stale SimulationView/articulation state after robot recreation. The maintained rules are centralized in [Robot runtime lifecycle](../../../../docs/reference/ROBOT_RUNTIME_LIFECYCLE.md):

- `franka` and `panda` resolve explicitly to `frankapanda`; fuzzy matching must not select FR3.
- Rebuild an invalid physics simulation view before creating a fresh articulation wrapper.
- Invalidate caches on Stage identity changes and on same-path USD/tensor joint-identity mismatch.
- Read joint names and values atomically from one joint-state snapshot.
- Fall back to explicit `angular`/`linear` `PhysicsDriveAPI` instances when tensor DOF metadata is invalid.
- MCP wrappers must build JSON-safe payload dictionaries explicitly; do not send `locals()` from a closure.

These corrections preserve the public joint, drive, motion, and controller contracts. Treat the 2026-08-31 paused-Panda IK/joint/drive result as dated evidence and rerun guarded Q2 acceptance before declaring a new current pass.

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

## Recorded final 2.3 acceptance

The clean-restart 2026-08-24 Isaac Sim `6.0.1-rc.7` PhysX run verified 68 commands
and motion-generation extension `8.2.9`. Franka IK reached
`7.363885225415161e-7 m` position error and repeated exactly with warm start and
seed 17. RRT returned a scoped collision-checked valid path with zero registered
scene obstacles. The non-blocking job passed pause/resume to completion,
explicit cancellation, and a 1 ms deadline timeout. Task/physics fixtures were
absent after cleanup; timeline, Kit/TCP, run-log, and native-dump gates passed.

## Task 2.4 controller profile invariants

- High-level gripper and mobile-base writes always require an explicit profile;
  never infer a controller from a prim name or partial joint-name match.
- Bind every required joint name and type before apply. A mismatch must return
  `applied=false` without changing any target.
- Gripper width is total finger separation in meters. Mobile commands use m/s
  and rad/s; non-zero commands require a playing timeline and persist until an
  explicit stop or replacement command.
- `stop_mobile_base` must read every profiled wheel velocity target back as
  zero. This proves the command target, not that physical inertia is zero.
- Jetbot differential geometry is explicit. Kaya holonomic geometry must be
  read from USD through `HolonomicRobotUsdSetup`; do not hardcode wheel axes or
  roller angles.
- Run `scripts/verify_controller_profiles_live.py` only on an empty scratch
  Stage. Its guard must execute before Stop, clear, create, or target writes.

## Recorded 2.4 read-only guard evidence

On 2026-08-24, live Isaac Sim `6.0.1-rc.7` reported 68 commands, three explicit
controller profiles, and enabled `isaacsim.robot.experimental.wheeled_robots`
version `0.2.11`. The Stage contained pre-existing non-task prims, so the guard
refused all timeline and Stage writes. Gripper/base mutation, joint/base
read-back, mismatch atomicity, and stop postconditions were intentionally deferred
until the later empty-Stage run below.

## Recorded 2.4 failed scratch rerun

The 2026-08-24 scratch rerun found and corrected three harness/runtime issues:
mismatch atomicity must compare command targets rather than moving measured
state; owned physics scene/ground prims must be deleted; and Warp command arrays
must be allocated on the Articulation physics device rather than process-current
CUDA device. In the same long-lived Kit session, RTX began reporting CUDA
external-memory failures before the latest fixtures were created, then produced
a GPU page fault and `ERROR_DEVICE_LOST`. Do not accept 2.4 or rerun 2.3 in that
runtime. Restart Isaac Sim with the active-display physics GPU guard, then rerun
2.4 from an empty Stage before 2.3.

## Recorded final 2.4 acceptance

The replacement 2026-08-24 runtime used the active-display physics GPU guard and
an empty scratch Stage. Franka open/set-width/close mapped total widths
`0.08/0.03/0.0 m` to exact finger targets; a mismatched profile preserved all
command targets. Jetbot targets were `[2.9583333, 3.7083333] rad/s`; Kaya targets
were `[-9.304024, -6.6114283, -9.497344] rad/s`. Both produced finite measured
wheel velocities and immediate all-zero stop target read-back. Isaac Sim 6 may
return a raw ndarray from experimental `HolonomicController.forward()`, so the
adapter normalizes either ndarray or action-object results and reorders values
from USD setup joint names to profile order. All owned robot/physics fixtures
were absent after cleanup; timeline, Kit/TCP, log, and native-dump gates passed.

When an allocation lands on the wrong CUDA device or the run reports external-
memory/device-lost errors, discard that runtime. Keep Warp arrays on
`art._device`, restart with the active-display physics GPU guard, and rerun 2.4
before 2.3; never promote evidence from the contaminated session.
