# Robot Runtime Lifecycle

This reference defines how IsaacSim-MCP keeps robot articulation, physics tensor, joint-state, drive, and motion state valid across Stage and robot lifecycle changes in Isaac Sim 6.0.1.

## Scope

The contract applies to:

- `get_joint_state`, `set_joint_command`, `get_joint_config`, and `set_joint_drive_config`;
- `compute_ik`, trajectory planning, and trajectory execution;
- gripper and mobile-base controller profiles;
- `step_simulation(..., observe_joints=[...])`;
- robot creation and same-path asset replacement.

Public MCP schemas and Extension command names remain separate from this internal lifecycle. Tool-profile consolidation changes only which public wrappers a client sees.

## Failure modes this contract prevents

| Symptom | Confirmed cause | Required recovery |
|---|---|---|
| `IK_FAILED: Instance's physics tensor entity is not valid` | Cached or newly-created articulation bound to an invalid SimulationView | Invalidate the physics view, rebuild physics, then create and validate a fresh articulation wrapper. |
| Panda finger values contain arm-scale radians such as `3.037` | Joint names and values came from separate lifecycle-sensitive reads | Return names, measured values, and targets from one joint-state snapshot. |
| `PhysicsDriveAPI, a non-empty instance name must be provided` | Multiple-apply `DriveAPI` queried without `angular` or `linear` instance | Resolve the current joint type and call `DriveAPI.Get(prim, "angular")` or `DriveAPI.Get(prim, "linear")`. |
| `/World/Franka` reports stale `fr3_*` joints after loading Panda | The prim path stayed the same while the USD asset identity changed | Compare current USD joint names with tensor DOF names and discard the stale wrapper on mismatch. |
| `Object of type function is not JSON serializable` | An MCP closure passed `locals()` and captured `send` | Build an explicit JSON-safe payload dictionary. Never pass closure `locals()` to the connection. |

Repeated Play/Pause calls are not a recovery mechanism for an invalid tensor entity. The runtime must repair or reject the stale binding before motion or joint operations continue.

## Stage and articulation identity

`RobotRuntime` owns articulation wrappers. Its cache follows these rules:

1. Record the current Stage/root-layer identity.
2. Clear cached articulations when that identity changes.
3. Before reusing a cached prim path, compare the current USD joint identity with the tensor DOF identity.
4. Build a fresh wrapper when either identity differs.
5. Return the wrapper only after its tensor entity is valid.

`franka` and `panda` are explicit aliases for the `frankapanda` library key. Fuzzy matching must not select the shorter FR3 key for these names.

## Physics SimulationView recovery

Before articulation initialization, query `SimulationManager.get_physics_simulation_view()` when available. If an existing view reports `is_valid=false`:

1. call `SimulationManager.invalidate_physics()`;
2. run the existing physics cleanup/setup sequence;
3. initialize physics again;
4. construct a fresh articulation wrapper;
5. verify the wrapper's tensor entity before use.

A second invalid fresh wrapper is a hard runtime error. Do not return it, cache it, or ask the caller to replay writes.

## Atomic joint observation

`step_simulation` joint observations use one `get_joint_state` call per articulation. The same snapshot supplies:

- articulation-order names and indices;
- measured position, velocity, and effort;
- position, velocity, and effort targets;
- joint type and public units.

Separate `get_joint_positions` and name lookups are forbidden in this observation path because Stage or tensor identity can change between calls.

## Drive configuration fallback

Tensor metadata remains the preferred fast path when it is complete and valid. When DOF types or tensor getters are invalid, read authored USD joints instead:

- revolute joints use `UsdPhysics.DriveAPI.Get(joint_prim, "angular")`;
- prismatic joints use `UsdPhysics.DriveAPI.Get(joint_prim, "linear")`;
- angular stiffness, damping, and velocity values are converted from USD degree units to the public radian contract;
- PhysX-only `max_velocity` remains capability-gated.

This fallback is read-only. It does not weaken stopped-timeline, backend, atomic validation, rollback, or read-back requirements for drive writes.

## Verification

Offline regression coverage:

- `tests/test_v6_runtime_physics.py`: invalid SimulationView recovery;
- `tests/test_v6_runtime_robots.py`: Stage identity, same-path robot replacement, and invalid fresh tensor rejection;
- `tests/test_v6_runtime_final_facade.py`: atomic step joint snapshot;
- `tests/test_robot_joint_drive_config.py`: explicit USD DriveAPI instances and tensor fallback;
- `tests/test_robot_asset_resolution.py`: Panda alias resolution;
- `tests/test_motion_tool_contract.py` and `tests/test_controller_profile_contract.py`: JSON-safe MCP payloads.

The dated 2026-08-31 read-only live check used an existing paused `/World/Panda` and observed:

- 9 correctly ordered `panda_joint*` and `panda_finger_joint*` DOFs;
- finger positions near zero instead of arm-angle values;
- successful `get_joint_config` without the empty-instance error;
- `IK_SOLVED` while paused with position error about `1.21e-7 m`;
- unchanged Stage prim count and timeline state.

This is historical evidence for the checked commit. Full Q2 acceptance still requires the guarded scratch-stage verifier, actual motion/gripper writes, operation-specific read-back, cleanup, Kit/TCP health, logs, GPU state, and native-dump review.
