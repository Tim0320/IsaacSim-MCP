# Robot joint state and command contract

Task 2.1 adds two named tools for Isaac Sim 6.0.1 articulations:

- `get_joint_state`: measured position, velocity, projected joint effort, and
  the active position, velocity, and effort command values.
- `set_joint_command`: atomic `position`, `velocity`, or `effort` commands with
  immediate read-back.

Both use the live Isaac Sim route on TCP `8766`. The documentation MCP on port
`9904` cannot provide stage-control evidence.

## Joint selection

The caller may provide exactly one selector:

- `joint_names`: exact, case-sensitive DOF names in caller-defined order.
- `joint_indices`: zero-based DOF indices in caller-defined order.

Omitting both selects every DOF in articulation order. Empty, duplicate,
unknown, out-of-range, or simultaneous selectors are rejected before the
adapter command runs. The number of `values` must exactly equal the number of
selected DOFs, and every value must be finite.

## Units

| Joint type | Position | Velocity | Effort |
| --- | --- | --- | --- |
| Revolute | radians | radians per second | newton-meters |
| Prismatic | meters | meters per second | newtons |

`get_joint_state` returns one object per selected DOF with `index`, `name`,
`type`, measured values, target values, and these units. Isaac Sim 6 reads the
measured effort through `get_dof_projected_joint_forces()` and the current
effort command through `get_dof_efforts()`.

## Command semantics

`position` and `velocity` write targets. Their physical tracking depends on the
joint drive configuration. Velocity control normally requires zero stiffness
and non-zero damping; drive configuration is defined in
[`ROBOT_JOINT_DRIVE_CONFIG.md`](ROBOT_JOINT_DRIVE_CONFIG.md).

`effort` calls `set_dof_efforts()`. Isaac Sim requires the effort to be renewed
on every simulation update for continuous effort control. One MCP call applies
one command update; a later motion/controller lifecycle must own continuous
renewal.

The handler resolves and validates the complete selector and value list before
calling the adapter. A rejected request returns `applied=false`. If the command
applies but the required read-back fails, the response is `partial` with
`JOINT_COMMAND_READBACK_FAILED` and `applied=true`.

## Stable validation codes

- `INVALID_JOINT_COMMAND_MODE`
- `JOINT_SELECTOR_CONFLICT`
- `EMPTY_JOINT_SELECTOR`
- `DUPLICATE_JOINT_SELECTOR`
- `JOINT_NOT_FOUND`
- `INVALID_JOINT_INDEX`
- `JOINT_INDEX_OUT_OF_RANGE`
- `INVALID_JOINT_VALUE`
- `JOINT_VALUE_COUNT_MISMATCH`
- `JOINT_STATE_UNAVAILABLE`
- `JOINT_COMMAND_UNSUPPORTED`
- `JOINT_COMMAND_FAILED`
- `JOINT_COMMAND_READBACK_FAILED`

## Live verification

Run the dedicated scratch verifier only while the project extension is loaded
and TCP `8766` is listening:

```powershell
.venv\Scripts\python.exe scripts\verify_robot_joint_control_live.py
```

The verifier refuses a stage containing unrelated prims, creates one Franka
fixture below `/World/MCP_Task_2_1_Robot`, exercises all three modes on a DOF
subset, steps the simulation, reads measured and target values, proves an
unknown joint name applies nothing, then deletes and reads back absence of the
scratch articulation.

The verifier keeps Timeline Play active while reading the V6 tensor state. It
stops the timeline before deleting the articulation; deleting tensor-owned
robot prims while merely paused invalidates the PhysX simulation view.

## Verified Isaac Sim 6.0.1 result

The 2026-08-24 scratch run used Isaac Sim `6.0.1-rc.7`, `IsaacAdapterV6`,
PhysX, and a 56-command extension registry. The Franka fixture exposed 9 DOFs.
Position, velocity, and effort commands on `panda_joint1` all returned their
requested target within float32 tolerance, and post-update measured position,
velocity, and projected effort were finite. Invalid-name atomicity, Stop-first
cleanup, prim absence, TCP/process survival, GPU selection, run-scoped logs,
and zero new native dumps all passed.
