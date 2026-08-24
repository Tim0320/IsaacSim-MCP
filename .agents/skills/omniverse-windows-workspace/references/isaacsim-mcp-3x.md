# IsaacSim-MCP Physics and USD authoring 3.x

Use this reference for completed Phase 3 work in
`docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`. It is a navigation and safety
index, not a substitute for the linked contract, verifier, tests, or current
live read-back.

## Retrieval workflow

1. Identify 3.1 through 3.5 in the numbering map.
2. Read the linked contract completely for schema, units, prerequisites,
   rollback behavior, stable errors, and backend limits.
3. Inspect the linked verifier before any live run. Confirm its read-only guard,
   owned namespace, restore path, and health gates.
4. Query current `get_capabilities`; recorded command counts and backend states
   are historical evidence only.
5. Use the implementation task for full research history and acceptance output.

## Numbering map

| Research label | Task item | Capability | Named tools | Contract | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 3.1 | Phase 3 item 11 | PhysicsScene gravity, integer-rate time step, GPU dynamics and broadphase | `set_physics_params` | `docs/PHYSICS_PARAMS.md` | `scripts/verify_physics_params_live.py` |
| 3.2 | Phase 3 item 12 | Adapter-owned PhysX/Newton feature matrix and fail-closed guards | `get_capabilities` | `docs/BACKEND_CAPABILITY_MATRIX.md` | `scripts/verify_backend_capability_matrix_live.py` |
| 3.3 | Phase 3 item 13 | Typed body, collider, mass/density, collision group, and joint authoring | `configure_physics_body`, `get_physics_body`, `create_collision_group`, `get_collision_group`, `create_physics_joint`, `get_physics_joint` | `docs/PHYSICS_AUTHORING.md` | `scripts/verify_physics_authoring_live.py` |
| 3.4 | Phase 3 item 14 | PBR/physics materials, friction/restitution, purpose binding and read-back | `create_material`, `get_material`, `apply_material`, `get_material_binding` | `docs/PHYSICS_MATERIALS.md` | `scripts/verify_physics_material_live.py` |
| 3.5 | Phase 3 item 15 | Guarded Stage lifecycle, layers, composition, variants, semantics, typed attributes, and batch rollback | `new_stage`, `open_stage`, `save_stage_as`, `get_stage_composition`, `edit_sublayer`, `edit_composition_arc`, `set_variant_selection`, `get_semantic_labels`, `set_semantic_labels`, `get_typed_attribute`, `set_typed_attribute`, `apply_stage_batch` | `docs/STAGE_COMPOSITION.md` | `scripts/verify_stage_composition_live.py` |

## Cross-task invariants

- Run Isaac-bound code through the live Kit extension or `C:\isaacsim` runtime;
  a generic Python import is not runtime evidence.
- Require a stopped timeline for every 3.x write. Validate the complete request
  before the first authored change and verify success with read-back.
- Treat rollback failure as partial or unknown state, never success.
- Keep `/physics/cudaDevice` under the launcher GPU-selection policy.
  `set_physics_params(gpu_enabled=...)` changes scene dynamics/broadphase only;
  it never changes the device ordinal.
- Treat Newton `null`/`untested`, `false`/`unsupported`, unknown, and unlisted
  features as fail-closed. Shared V6 code or USD schemas do not prove support.
- Use verifier-owned Stage namespaces. Snapshot and restore any Isaac-created
  baseline PhysicsScene or pre-existing root/session layers; delete only owned
  fixtures.
- Current live acceptance requires TCP `8766`, exact read-back, cleanup,
  responsive Kit process, run-scoped log review, and no new native dump.

## 3.1 physics parameters

- Accept exactly three finite gravity values, time steps from `0.0001` to `1.0`
  seconds whose reciprocal is an integer, and a JSON boolean `gpu_enabled`.
- Map GPU enabled to GPU dynamics plus GPU broadphase; map disabled to CPU
  dynamics plus MBP. Report the PhysX CCD side effect when present.
- Keep USD `timeStepsPerSecond`, Stage `timeCodesPerSecond`, persistent minimum
  frame rate, SimulationManager default scene, and runtime time step consistent.
- Reject multiple PhysicsScene prims and active timelines before authoring.
- On apply/read-back failure, restore authored attributes and global timing.

Historical 2026-08-24 PhysX evidence verified 120 Hz USD/runtime/manager
read-back and 12 exact steps advancing 0.1 seconds. Invalid 0.007-second and
active-timeline requests preserved the snapshot, and the original scene timing
and default-scene state were restored.

## 3.2 backend capability matrix

- `physx_supported` and nullable `newton_supported` are independent facts.
- `newton_supported=true` requires a dedicated guarded Newton live run.
- Capability schema `1.1` projects the active backend from the adapter-owned
  matrix. Do not maintain a separate optimistic feature list in handlers.
- Call `require_backend_capability()` before known backend-sensitive writes.

The current historical matrix has 21 rows: PhysX 21 supported/verified;
Newton 0 supported, 18 untested, and 3 unsupported. The explicit PhysX-only
rows are physics time step, GPU dynamics, and joint-drive max velocity. Rerun
the read-only verifier before reporting these counts as current.

## 3.3 typed physics authoring

- Body modes are dynamic, kinematic, and static. Mass uses kilograms; density
  uses kilograms per cubic metre; mass and density are mutually exclusive.
- Mesh collider approximation is valid only for Mesh prims. Body configuration
  snapshots managed APIs/attributes and restores them after any failed apply or
  read-back.
- Collision-group members must already have `CollisionAPI`.
- Joints are fixed, revolute, or prismatic. Local positions and prismatic
  limits are metres; revolute limits are degrees; rotations are normalized
  `[w, x, y, z]`; axes are X, Y, or Z.
- Refuse existing group/joint paths and delete newly created prims after failed
  authoring or read-back.

Historical 2026-08-24 PhysX evidence covered six named tools, body/mass/density,
group relationships, all three joints, a deliberate mid-apply rollback, 120
exact steps, fixed-body constraint behavior, and complete scratch cleanup.

## 3.4 physics materials

- Author physics materials as `UsdShade.Material` with
  `UsdPhysics.MaterialAPI`; use `material:binding:physics` for physics purpose.
- Require finite non-negative friction, dynamic friction no greater than static
  friction, restitution in `[0, 1]`, and stopped timeline.
- Failed creation removes the new prim. Failed binding restores the previous
  direct material relationship and strength.
- Use float32 read-back tolerance from the contract; do not require exact JSON
  decimal equality.

Historical 2026-08-24 PhysX evidence verified two materials, eight
physics-purpose bindings, 181 exact steps, a 2.558789-metre sliding difference,
a 3.065565-metre high-restitution rebound, invalid-pair atomic rejection, and
scratch cleanup.

## 3.5 Stage and composition

- Lifecycle tools default to `preview=true`. Actual new/open/save-as requires
  `scratch_stage=true`, an existing canonical local `scratch_root`, and stopped
  timeline. Paths must remain inside the root.
- Accept only `.usd`, `.usda`, or `.usdc`. Never overwrite the currently opened
  source. Existing targets require explicit `overwrite=true`.
- Validate and read back subLayers, references/payloads and load rules, variant
  selections, `UsdSemantics.LabelsAPI`, and explicitly typed attributes.
- Batch at most 100 layer/arc/variant/semantic/attribute operations. Snapshot
  root/session layers and payload load rules; any failure must return
  `BATCH_ROLLED_BACK` after restoring the whole transaction.
- Keep lifecycle and filesystem side effects outside batch transactions.

Historical 2026-08-25 evidence verified an 88-command registry, composition
arcs, payload unload/load, variant selection, LabelsAPI, scalar/array typed
attributes, successful and rolled-back batches, save/reopen equality, and
restoration of the original anonymous Stage from 15 prims back to 15.

Do not run `tests/test_integration.py` as an offline regression while live TCP
`8766` is reachable. It creates Camera, LiDAR, and robot fixtures without the
3.5 snapshot/restore contract and then plays simulation. One broad run entered
Replicator `reset_scenario()` and caused a native Kit crash. Use the dedicated
3.5 verifier for acceptance and explicitly exclude destructive integration from
the offline suite.

## Current-claim checklist

1. Record repository root, remote, branch, HEAD, status, and a verified backup.
2. Confirm Isaac Sim 6.0.1, adapter/backend, current capability schema and tool
   count, TCP `8766`, and the launcher-selected physics GPU.
3. Run only the matching verifier after its read-only guard passes.
4. Capture requested/applied/read-back values, rollback evidence, fixture and
   filesystem cleanup, timeline state, Kit PID/response, port, log, and dumps.
5. Report recorded values as historical if the live verifier was not rerun.
