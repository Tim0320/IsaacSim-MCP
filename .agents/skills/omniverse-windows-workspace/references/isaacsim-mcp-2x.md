# IsaacSim-MCP Robot control 2.x

Use this reference for Phase 2 Robot control work in
`docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`.

## Numbering map

| Research label | Task item | Capability | Named tools | Contract | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 2.1 | Phase 2 item 7 | Complete V6 joint state and atomic position/velocity/effort commands | `get_joint_state`, `set_joint_command` | `docs/ROBOT_JOINT_CONTROL.md` | `scripts/verify_robot_joint_control_live.py` |

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
