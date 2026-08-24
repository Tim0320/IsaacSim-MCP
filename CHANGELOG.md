# Changelog

All notable changes to the isaacsim-mcp-server project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — guarded OmniGraph lifecycle and exact ScriptNode control

- Expanded Action Graph control from create/edit to twelve named tools, adding
  graph/node/edge query, delete, exact connect/disconnect, runtime-only enabled
  state, runtime status, explicit evaluation, and graph-scoped ScriptNode
  configure/reload. The named-tool inventory is now 98.
- New graph writes default to preview and require a stopped timeline. Disabling
  a graph remains available while playing as an emergency stop; enabling and
  every other graph write fail closed until the timeline is stopped.
- Added operation-specific apply/read-back/rollback for connections, enabled
  state, ScriptNode source changes, create/edit, and deletion. Graph deletion
  uses non-destructive `DeletePrimsCommand` with `undo()` on failed read-back.
- ScriptNode inline and file modes are explicit and mutually exclusive. File
  mode resolves an existing `.py`; configure/reload targets one exact graph and
  node, clears ScriptNode caches, resets `state:omni_initialized`, and reports
  source hash/path plus pending compile state.
- Runtime status and explicit evaluation report node compute counts, messages,
  and stable error codes. Enabled state responses explicitly state that this
  runtime flag is not persistent USD authoring.
- Added offline tool, capability, schema, and handler contract coverage. A
  dedicated scratch live run verified 98 commands, exact edge handling,
  inline/file ScriptNode reload, runtime errors, disabled compute-count freeze,
  graph/prim deletion, graph-list restoration, and stopped-timeline cleanup.

### Added — guarded Stage, layer, composition, and semantic authoring

- Added twelve named tools for scratch-guarded new/open/save-as, scoped Stage
  composition inspection, subLayers, reference/payload arcs and payload load
  rules, variant selection, Isaac Sim 6.0.1 `UsdSemantics.LabelsAPI`, typed
  attributes, and atomic batch transactions.
- Lifecycle writes default to preview, require a stopped timeline and explicit
  scratch root, reject source overwrite, and restore root/session layer state
  when an open/new operation fails. Save-as validates a temporary USD before
  atomic replacement.
- Layer, arc, semantic, and attribute writes use exact read-back and rollback.
  Batch transactions snapshot root/session layers plus payload load rules and
  restore them when any of at most 100 operations fails.

### Added — typed physics material schema and behavioral read-back

- Exposed static/dynamic friction and restitution in `create_material`, and
  added `get_material` plus `get_material_binding` named tools.
- Physics materials are now typed `UsdShade.Material` prims with
  `PhysicsMaterialAPI` and dedicated `material:binding:physics` relationships.
- Added validation, stopped-timeline guards, float32-aware read-back,
  create rollback, and binding rollback.
- A scratch live fixture verified eight bindings, a `2.558789 m` friction
  travel difference, and a `3.065565 m` high-restitution rebound across 181
  exact PhysX steps. The backend matrix now contains 21 rows.

### Added — typed physics body, collision group, and joint authoring

- Added six named tools for atomic dynamic/kinematic/static body setup,
  collider approximation, mass/density, collision groups, and fixed/revolute/
  prismatic joint create/query with explicit units and read-back.
- Added stopped-timeline validation, body schema snapshot rollback, and
  remove-on-failure group/joint transactions.
- Verified all schemas plus a fixed constraint across 120 exact PhysX steps in
  a disposable scratch namespace. The backend matrix now contains 20 rows;
  Newton remains fail-closed and untested for the three new rows.

### Added — audited PhysX/Newton capability split

- Added capability schema `1.1` with an adapter-owned 20-row backend matrix.
  Every row reports `physx_supported`, `newton_supported`, the untested backend
  list, and independent support/verification evidence.
- Projected active-backend state into simulation, physics, sensor, articulation,
  motion, gripper, and mobile-base feature flags. V6 code reuse no longer makes
  untested Newton paths appear supported.
- Added a shared adapter guard and applied it to PhysX scene time/GPU settings
  and `PhysxJointAPI` maximum velocity. Untested, unsupported, unknown, and
  unlisted backend paths fail before apply.
- Added a read-only live verifier for all 20 PhysX rows, seventeen Newton
  `untested` rows, three Newton `unsupported` rows, and unchanged scene/runtime
  state.

### Added — atomic V6 PhysX scene parameters

- Completed `set_physics_params` for gravity, integer-rate physics dt, GPU
  dynamics, and matching GPU/MBP broadphase on Isaac Sim 6.0.1 PhysX.
- Added stopped-timeline and single-scene guards, full input validation,
  attribute snapshots, rollback status codes, and USD/runtime/SimulationManager
  read-back. V5 and Newton continue to report time/GPU arguments unsupported.
- Synchronized Stage time codes, the minimum simulation frame-rate clamp, and
  the SimulationManager default scene with the selected physics rate.
- Fixed `_ensure_physics_world()` so later tools no longer call
  `setup_simulation(dt=1/60)` and silently erase a configured time step.
- Added a guarded live verifier for 120 Hz clock timing, invalid-input and
  active-timeline atomicity, GPU/CPU broadphase mapping, and exact baseline
  restoration.

### Added — explicit gripper and mobile-base controller profiles

- Added six named tools for profile discovery, Franka gripper open/close/width,
  differential or holonomic base velocity, and verified zero-target stop.
- Profiles bind exact joint names and types before apply; unknown, wrong-kind,
  mismatched, non-finite, over-limit, and invalid-timeline requests fail closed.
- Jetbot uses documented differential wheel geometry. Kaya reads holonomic wheel
  geometry from USD through Isaac Sim 6 experimental wheeled-robot APIs instead
  of embedding mecanum geometry in the MCP layer.
- A clean-restart scratch run verified 68 registered commands, three profiles,
  wheeled robots extension `0.2.11`, Franka width/open/close, mismatch atomicity,
  Jetbot differential and Kaya holonomic measured-state read-back, and zero-target stops.
- Bound Warp command arrays to the Articulation physics device instead of the
  process-current CUDA device, which may differ in a multi-GPU Kit session.
  The verifier now compares command targets rather than moving measured state,
  cleans its physics fixtures, and emits flushed phase progress. The prior
  `ERROR_DEVICE_LOST` session was discarded; the clean replacement passed
  stopped-timeline, fixture-absence, live PID/TCP, log, and native-dump gates.
- Normalized Isaac Sim 6 experimental `HolonomicController.forward()` ndarray
  results while retaining compatibility with action objects exposing
  `joint_velocities`; setup joint names are explicitly reordered to the profile.

### Added — bounded V6 motion generation and controller jobs

- Added `compute_ik`, `plan_joint_trajectory`, `execute_trajectory`,
  `cancel_motion`, and `get_motion_status` backed by NVIDIA Lula on 6.0.1.
- IK exposes warm start, deterministic seed, iteration/time bounds, achieved
  end-effector error, and an explicit unchecked collision result.
- Joint planning separates collision-aware RRT from unchecked deterministic
  C-space splines and stores results behind opaque trajectory IDs.
- Execution uses Kit update callbacks and returns immediately with a job ID;
  jobs support pause/resume, cancellation, deadline timeout, progress, and one
  active job per articulation.
- A clean-restart Franka scratch namespace produced deterministic IK
  (`7.36e-7 m` error), scoped RRT collision result, and completed/cancelled/
  timed-out terminal states. Cleanup read-back, stopped timeline, PID/TCP,
  run-log, and native-dump gates passed with the 68-command registry.

### Added — atomic V6 joint drive configuration

- Added `set_joint_drive_config` for stiffness, damping, maximum effort,
  maximum velocity, and force/acceleration drive type with name/index subsets.
- Drive writes require a stopped timeline, validate every field before apply,
  snapshot selected values, rollback already-written fields on failure, and
  return typed SI-unit read-back through `get_joint_config`.
- Capability discovery now separates verified PhysX fields from Newton's
  unverified USD DriveAPI fields and PhysX-only maximum velocity.
- Added an isolated Franka verifier for before/after values, invalid request
  atomicity, active-timeline rejection, cleanup, logs, and native dumps.
- The Isaac Sim 6.0.1 PhysX live run passed all five fields on `panda_joint1`,
  three pre-apply rejection paths, scratch cleanup, process/port survival,
  active-display GPU selection, log review, and native-dump review.

### Added — complete V6 joint state and command modes

- Added `get_joint_state` for joint name/index mapping, measured position,
  velocity, projected effort, all three active targets, joint types, and units.
- Added atomic `set_joint_command` modes for position, velocity, and effort with
  name/index subsets, finite-value checks, immediate read-back, and stable
  validation errors. Unknown joints and invalid selectors apply nothing.
- Fixed V6 subset position commands to pass `dof_indices` to the experimental
  Articulation API instead of treating DOF indices as articulation-view rows.
- Added an isolated Franka live verifier for all modes, stepped measured-state
  read-back, invalid-name atomicity, and scratch cleanup.
- The Isaac Sim 6.0.1 PhysX live run passed all three command modes on a 9-DOF
  Franka, atomic invalid-name rejection, stale tensor-wrapper rebinding,
  Stop-first cleanup, process/port survival, log review, and native-dump review.

### Added — deterministic Camera and LiDAR lifecycle

- Added `delete_sensor`, with sensor-aware `delete_object` routing, to release
  RTX runtime resources before deleting the USD prim. Isaac Sim 6 uses its
  complete `_invalidate_sensor()` path; older wrappers can use `destroy()` or
  the explicit detach fallback.
- Lifecycle failures now return stable errors and preserve the runtime cache
  reference for retry. Successful deletion waits for bounded Kit updates and
  reads back prim, RenderProduct, cache, and LiDAR metadata absence before it
  reports success.
- Timeline Stop and same-path recreation release cached sensor runtimes to
  prevent duplicate annotators, writers, RenderProducts, or callbacks while
  preserving LiDAR authoring metadata across Stop. Two live Camera/LiDAR
  create-read-delete-recreate cycles passed on Isaac Sim 6.0.1 with no pipeline
  duplicates, resource survivors, server loss, or native crash signature.

### Added — shared managed artifact transport

- Added `get_artifact_info`, `read_artifact`, `delete_artifact`, and
  `cleanup_artifacts` for bounded chunk downloads, metadata read-back,
  explicit deletion, and TTL cleanup of Camera and LiDAR payloads.
- Managed artifacts use unpredictable opaque handles, a controlled root,
  atomic data/sidecar writes, SHA-256, expiry metadata, traversal protection,
  and configurable per-file, total-capacity, and chunk limits.
- Camera PNG/NPY and LiDAR NPZ outputs now share the same transport contract.
  Chunk reconstruction, hashes, limit errors, deletion, expiry, cleanup, and
  scratch-stage cleanup passed the Isaac Sim 6.0.1 live harness.

### Added — effective RTX LiDAR configuration

- Added `get_lidar_config` and expanded `create_lidar` with validated generic
  horizontal/vertical FOV, angular resolution, rotation rate, and range inputs.
  Named Isaac Sim presets and variants remain available as a separate mode.
- V6 maps generic settings to `OmniSensorGenericLidarCoreAPI`, uses the
  one-based emitter channel IDs required by 6.0.1, and reads effective values
  back from the authored USD attributes. Unsupported or conflicting settings
  return stable errors instead of being silently ignored.
- Partial-FOV sensors stream per-tick output so both tested configurations
  produce live point clouds. Two distinct configurations, invalid-resolution
  rejection, transform read-back, Play/Stop, and scratch cleanup passed the
  Isaac Sim 6.0.1 live harness.

### Added — typed RTX LiDAR point clouds

- Expanded `get_lidar_point_cloud` from a point count into a bounded transfer
  contract with metadata, controlled `.npz` artifacts, and size-limited inline
  output. Each artifact stores typed `.npy` arrays for Cartesian XYZ, range,
  azimuth, elevation, and available auxiliary fields with per-field hashes.
- Isaac Sim 6 GMO spherical azimuth/elevation/range data is now converted to
  Cartesian meters instead of being mislabeled as XYZ. Responses also expose
  coordinate type/frame, sensor timestamp/frame, sensor pose, stable 128-bit
  object IDs and their prim map when available; unavailable fields are explicit.
- V6 LiDAR wrappers request `FULL` auxiliary output and attach both
  `generic-model-output` and `stable-id-map` annotators.

### Added — typed RTX camera outputs and calibration

- Added `capture_camera_output` for depth, distance-to-image-plane,
  semantic/instance/instance-ID segmentation, normals, and motion vectors. Responses expose
  dtype, shape, units, coordinate space, frame/timestamp, annotator info, and
  hashes through metadata, controlled `.npy` artifacts, or bounded raw inline
  bytes.
- Added `get_camera_calibration` for pinhole intrinsics, USD camera-to-world and
  world-to-camera matrices, projection, resolution, clipping, and explicit unit
  conventions.
- Fixed the V6 CameraSensor lifecycle by committing Play before Replicator
  capture-on-play and avoiding pause-render fallback while the timeline runs.
  All six outputs, known-geometry/prim read-back, and calibration passed the
  Isaac Sim 6.0.1 live scratch harness.

### Fixed — Isaac Sim 6.0.1 multi-GPU PhysX launch guard

- The Windows launcher now resolves the current unique
  `display_active=Enabled` NVIDIA GPU to an explicit `/physics/cudaDevice`
  ordinal. Selection precedence is raw Kit setting, `-PhysicsGpu`,
  `ISAAC_PHYSICS_GPU`, then automatic detection. Ambiguous detection warns and
  falls back to GPU 0. Explicit `-1` is preserved but warns about the reproduced
  Timeline Stop crash in `PhysXGpu_64.dll`.

### Fixed / Changed — tool hardening for agent use
- step_simulation now fails loud on a running timeline and the debug loop is
  documented as step-only (never play while debugging). (#1)
- create_action_graph gains inline_script= one-step shortcut; the broken inline
  example is removed. (#2)
- reload_script recompiles Action-Graph ScriptNodes that reference the edited
  file, instead of silently no-oping. (#3)
- get_isaac_logs: eager listener, run-scoped (since_last_play default),
  non-destructive default, and captures print() as [PRINT]. (#4/#5)
- execute_script documents that it can silently disturb a live ScriptNode. (#6)
- create_object documents that scale= is a raw native-size multiplier. (#7)
- stop_simulation resets the scene to spawn state. (#8)

### Fixed — silent wrong answers found by live testing on 5.1.0 and 6.0.1

Each of these was reproduced against a running simulator, one version at a
time, and re-measured after the fix. Unit tests passed throughout: every one of
them needs a real stage, a real physics step or a real referenced asset to show
up at all.

- **Joint limits were reported in degrees while positions were radians.**
  `get_joint_config` returned USD's raw revolute limits: FR3 joint 1 read
  `[-157.2, 157.2]` next to `actual_position=0.5`, where the real limit is
  ±2.7437 rad. An agent clamping a target to those limits would command 25
  revolutions. Limits now arrive in the same units as positions, with an
  explicit `limit_units` per joint. Prismatic limits are deliberately untouched
  — USD stores those in stage units, and converting them turns a 0.04 m gripper
  stroke into 0.0007. `get_robot_info` previously advertised `"degrees"` for the
  same attributes and now agrees. Both adapters. (`adapters/units.py`)
- **A requested rotation compounded with the prim's existing orientation.**
  `set_prim_transform` only ever wrote `xformOp:rotateXYZ`, so on a prim
  carrying `xformOp:orient` the rotation was appended rather than replacing
  anything, landing after `xformOp:scale`. On a prim with orient=90° and
  scale=(1,2,1), asking for 45° produced 135° and a shear of 1.5. It already
  bit in practice: 5.1 cameras ship `orient=(0.5,0.5,-0.5,-0.5)`, so
  `create_camera(rotation=...)` could not aim a camera at all. Both adapters.
  (`adapters/transforms.py`)
- **`get_prim_info` had no rotation.** It returned position only, so "is this
  prim rotated?" was unanswerable through the tools while the docstring
  advertised the transform. It now reports rotation (XYZ degrees, the order
  `transform_object` accepts) and scale, read off the orthonormalized matrix so
  scale cannot corrupt the angle.
- **Environments lost their axis and unit conversion.** USD authors
  `unitsResolve` ops for a reference whose layer declares a different `upAxis`
  or `metersPerUnit` — but only when the target prim has no pre-existing
  children. `load_environment` referenced onto `/Environment`, which ships
  `defaultLight`, so the conversion was skipped: a ground standing on edge,
  10 km across, floor at z=-5000. That is 6 of 25 shipped environments on 5.1
  and 8 of 28 on 6.0 by up-axis, 8 and 10 by units. It now references onto
  `/Environment/<name>` and reports what USD applied under `corrections`, plus
  `bounds` with extent and floor height. Both adapters.
- **`clear_scene` did not clear a loaded environment**, so a later
  `create_physics_scene(floor=True)` stacked a second ground under the first.
  It now empties `/Environment` while always keeping `defaultLight` — an unlit
  stage renders black, which reads as a broken sensor — and takes
  `keep_environment` for callers who want to keep it. Reloading an environment
  now replaces rather than stacking references.
- **`stop_simulation` silently kept the stepped pose** when called promptly
  after `step_simulation`. `_arm_reset_point` queues play/pause to give PhysX a
  restore point, but timeline transitions are tick-driven, so the point landed
  after `step()` returned. Deterministic on 6.0.1: a cube stepped from z=2.0
  stayed at z=-3.32 through stop. Arming now pumps once so the transition lands.
  The stepped result stays bit-identical. V6 only — V5 never had it. (#8 above
  covers the reset itself.)
- **`get_simulation_state` reported a Python repr as the version.** On 6.0
  `get_version()` returns an 8-tuple, not a string, so clients saw
  `"('6.0.1', 'rc.7', '6', ...)"` instead of `6.0.1-rc.7`. The same wrong
  assumption made adapter selection load V5 on a 6.0 runtime; that half had been
  fixed, this half had not. Both now read the duality from one place.
  (`adapters/version.py`) V6 only.
- **Both lidar tools were dead on 5.1.** `create_lidar` raised
  `got multiple values for keyword argument 'config'` (5.1's `LidarRtx` takes
  `config_file_name`), and `get_lidar_point_cloud` raised
  `'LidarRtx' object has no attribute 'get_point_cloud'` (5.1 exposes annotators
  plus `get_current_frame()`). The annotator must be attached *before*
  `initialize()` and the wrapper must be cached, exactly as cameras already are.
  V5 only — 6.0's lidar path was fixed earlier and left 5.1 behind.
- **Commands sent during startup failed with a raw AttributeError.** The socket
  accepts connections several seconds before Kit has a stage — measured on
  6.0.1 at t+6.8s versus t+14.5s, and an MCP client normally connects the moment
  the port opens. Every stage-dependent tool in that window returned
  `'NoneType' object has no attribute 'GetPrimAtPath'`, which reads as a broken
  server rather than one still starting. Dispatch now detects the pending stage
  and returns a message saying to retry. Both adapters.
- **Cameras could not be deleted.** `delete_object` on a camera returned
  success and the prim was still there a tick later, surviving `clear_scene`
  too, because an initialized Camera wrapper owns a render product, annotators
  and event subscriptions that keep its prim alive — dropping the cache entry is
  not enough, the wrapper has to be destroyed. Adapters now release the sensor
  before deleting, which also frees the render product that otherwise keeps
  rendering for the life of the Kit process. Measured on 5.1.0: camera prims
  1 -> 0 and render products 2 -> 1 on delete, where both previously stayed put.
  6.0 is unfixed — see known issues.
- **`apply_material` leaked a raw USD C++ error** naming NVIDIA's build tree
  when a path did not exist. It validates both prims and names the offending
  one. Both adapters.

### Changed
- `scripts/smoke_test_v6.py` is now `scripts/smoke_test.py` and runs against
  either runtime, detecting the adapter from `simulation.get_state` and
  asserting what is true for each — V5 must *not* grow the V6-only reporting
  fields, so a misdetected adapter fails the run instead of passing quietly.
  Several of its checks had encoded contracts the code deliberately no longer
  has, or never had: two did `play` → `step` after that was made an error, and
  the reset check read a top-level `position` from `get_prim_info`, which has
  always nested it under `transform`.
- `clear_scene` gains `keep_environment`; `load_environment` returns
  `corrections` and `bounds`, and its `prim_path` now defaults to a named child
  of `/Environment` — read it from the response rather than assuming it.

### Known issues
- **Recurrence guard:** on Isaac Sim 6.0.1 multi-GPU systems, do not remove the
  launcher's explicit PhysX GPU selection or silently restore
  `/physics/cudaDevice=-1`. Both GPU 0 and GPU 1 passed when fixed explicitly;
  the failure is auto-selection/context migration, not a requirement to always
  use GPU 0. Renderer multi-GPU settings do not fix this PhysX failure.
- `get_lidar_point_cloud` returns `point_count` without the points themselves on
  6.0; the decoded cloud is discarded by the handler.
- Camera deletion is fixed on 5.1 but **not on 6.0**, and cannot be fixed at
  this layer. `create_camera` builds an `RtxCamera`, and that class exposes no
  teardown at all — only `reset_to_default_state`, `reset_xform_op_properties`
  and `valid` — while Isaac holds the instance internally, so nothing can
  release it. It re-creates the camera prim on the tick after a delete: the prim
  is genuinely gone in the same tick, then reappears at the end of the parent's
  children with its render product still targeting it
  (`HydraTextures/camera_sensor_NNN -> camera: ['/World/C1']`). `delete_object`
  now verifies the prim went and reports failure when it did not, but a handler
  cannot wait a tick, so the reappearing case still slips through. Reuse a
  camera rather than deleting it on 6.0.
- On 5.1, `clear_scene` with several cameras alive still removes only one per
  pass, and Kit logs `SDGPipeline/Replicator_NN_Reference` attribute errors, so
  destroying a sensor appears to need a tick before its prim can go. A repeated
  `clear_scene` drains the rest.
- `create_camera` has no look-at parameter, so aiming requires computing euler
  angles by hand.
- Only one Isaac Sim instance can run at a time on a single GPU; a second
  concurrent instance caused device-lost crashes during testing.

## [0.6.0] - 2026-06-13

### Added
- **Isaac Sim 6.0.0 support** — new `IsaacAdapterV6` built on `isaacsim.core.experimental.*` + `SimulationManager` + `isaacsim.sensors.experimental.rtx` + `isaacsim.asset.importer.urdf.URDFImporter`. Works under both the PhysX launcher (`isaac-sim.sh`) and the Newton launcher (`isaac-sim.newton.sh`).
- **Engine auto-detection** — `adapters/__init__.py:get_adapter()` reads `isaacsim.core.version.get_version()` and selects V5 or V6 by major version. V6 reads `SimulationManager.get_active_physics_engine()` at construction time.
- **`engine` and `isaacsim_version` fields on `get_simulation_state`** — MCP clients can see the active backend without poking at the runtime.

### Changed
- V6 URDF import uses `URDFImporter(URDFImporterConfig(...))` instead of the deprecated `URDFCreateImportConfig`/`URDFParseFile`/`URDFImportRobot` kit commands.
- V6 physics state reads route through `SimulationManager.get_physics_simulation_view()` (the `omni.physics.tensors` view), replacing the V5 direct call to `omni.physx.get_physx_interface().get_rigidbody_transformation()` (which is unavailable under the Newton kit).
- V6 sensor methods use `isaacsim.sensors.experimental.rtx.{RtxCamera,CameraSensor,Lidar,LidarSensor}` instead of the deprecated `isaacsim.sensors.camera.Camera` / `isaacsim.sensors.rtx.LidarRtx`.

### Notes
- 5.1.0 behavior unchanged — `IsaacAdapterV5` is untouched.
- Hot-reload script (`scripts/dev_mcp_server.sh`) now reloads `adapters.v6` alongside `adapters.v5`.

## [0.5.2] - 2026-04-07

### Fixed
- Code style: apply ruff formatting to v5 adapter, graphs handler, and scene handler

## [0.5.1] - 2026-04-06

### Added
- **`edit_action_graph` tool**: Modify attribute values and add connections on existing Action Graphs. Uses `og.Controller.set()` for ScriptNode `usePath`/`scriptPath` attributes (matching the pattern from `omni.graph.scriptnode` official tests). Auto-resets `state:omni_initialized` when script content or path changes to force ScriptNode reload
- **`script_file` parameter on `create_action_graph`**: One-step convenience for the common OnPlaybackTick → ScriptNode workflow. Automatically creates nodes, wires connections, and attaches the script file — replaces the previous two-step create + edit pattern
- **`prim_path` parameter on `create_robot`**: Explicit USD prim path control (e.g. `/World/Franka`) instead of name-based path derivation. Solves the common issue where robots are created at `/{Name}` but scripts expect `/World/{Name}`
- ScriptNode workflow documentation in MCP server instructions covering one-step (`script_file`) and two-step (`create` + `edit`) patterns, script reload via `edit_action_graph`, and `setup(db)`/`compute(db)` function requirements

### Changed
- `create_action_graph` docstring updated with `script_file` example and inline/file-based usage patterns
- `create_robot` docstring updated with `prim_path` parameter documentation
- Tool count updated to 42 across 9 categories

## [0.5.0] - 2026-04-06

### Added
- **`create_action_graph` tool**: Build OmniGraph Action Graphs programmatically (nodes, connections, attribute values) via `og.Controller.edit()` — no more raw `execute_script` calls for OnPlaybackTick → ScriptNode wiring
- **Drive config warnings**: `get_joint_config` and `create_robot` now return a `warnings` array when any joint has `stiffness=0` and `damping=0` (e.g. FR3 `finger_joint2` broken drive)
- **Dimensional data in responses**: `create_object` now returns `actual_size` [x, y, z] in meters and `bounding_box` (min/max world-space corners)
- **Prim size inspection**: `get_prim_info` returns `actual_size` for geometric prims (Cube, Sphere, Cylinder, Cone, Capsule)
- **Inline joint info**: `create_robot` now returns `joint_names` and `num_dof` in the response, eliminating the need for a follow-up `get_robot_info` call
- **Joint limits**: `get_robot_info` now returns `joint_limits` with type (revolute/prismatic), lower/upper limits, and units per joint
- **Comprehensive server instructions**: MCP `instructions` field now includes workflow guidance for scene setup, debug loop (step-and-observe), controller development, and tool priority
- `get_prim_actual_size` adapter method for computing prim dimensions from USD geometry attributes and scale

### Changed
- **Tool docstrings rewritten** with workflow guidance:
  - `step_simulation` promoted as the primary debug tool with typical debug loop example
  - `execute_script` reframed as escape hatch with explicit list of preferred alternatives
  - `reload_script` positioned as the controller loading workflow
  - `get_joint_config`, `get_physics_state`, `get_isaac_logs` marked as diagnostic tools with when-to-call guidance
  - `set_joint_positions`, `get_joint_positions` now document units (radians/meters)
  - `create_object` documents default primitive sizes and scale behavior
- Replaced `asset_creation_strategy` prompt with inline `instructions` covering MCP vs Script/Action Graph scope
- Updated package name and version in extension.toml
- Added new application icon and social badge image

### Fixed
- **Ground plane collision**: `create_physics_scene` now applies `UsdPhysics.CollisionAPI` to the ground plane — objects no longer fall through the floor
- **Stale `.pyc` in `reload_script`**: Dev script now clears bytecode cache before `importlib.reload()` for both extension and user modules, preventing stale code from loading
- **Orphaned subscriptions**: `reload_script` exec() mode now cleans up subscriptions from previous runs before re-executing
- Dev hot-reload script: bypass pybind11 `__setattr__` on `omni.ext.IExt` subclasses using `__dict__` assignment
- Dev hot-reload script: use `isinstance(obj, MCPExtension)` instead of fragile `hasattr` checks that matched wrong objects
- Dev hot-reload script: clear stale `.pyc` files before `importlib.reload()` to ensure fresh source is loaded
- Use `Usd.TimeCode.Default()` instead of non-existent `Gf.TimeCode(0)` in `get_prim_actual_size`
- World-space (not local-space) transform for bounding box computation
- Cylinder/Cone axis attribute respected when computing dimensions

## [0.4.1] - 2026-04-02

### Changed
- Added MCP registry metadata (`server.json`) for marketplace listing
- Fixed demo GIF URL in README to use absolute GitHub raw URL

## [0.4.0] - 2026-04-02

### Added
- **Observability tools**: `get_simulation_state`, `get_physics_state`, `get_joint_config`, `get_isaac_logs`, `reload_script`
- **Step-and-observe**: `observe` parameters on `step_simulation` for combined stepping and inspection (issue #8)
- `cwd` parameter and stdout/stderr capture for `execute_script`
- Franka pick-and-place demo scene and USD file
- Development wrapper for MCP server with hot-reloading support
- Environment discovery and loading tools
- Dynamic robot discovery from Isaac Sim asset server
- PyPI packaging via `pyproject.toml` — installable with `pip install isaacsim-mcp-server`
- Tag-triggered PyPI publish and GitHub Release CD pipeline
- Smithery registry manifest
- CI lint and format checks on PRs (ruff)
- Desktop launcher instructions and scripts
- Documentation for running multiple Isaac Sim instances with MCP

### Changed
- **Renamed package** from `isaac-sim-mcp` to `isaacsim-mcp-server` across all references
- Complete modular architecture rewrite:
  - Extracted `IsaacConnection` into dedicated connection module
  - Added adapter layer with base ABC and v5 implementation
  - Split into 8 handler modules with 31+ command handlers
  - Split into 8 MCP tool modules with 31+ tools
  - Rewrote `server.py` as slim entry point using modular tools
  - Rewrote `extension.py` as slim registry-based command router
  - Extracted socket server from `extension.py`
- Added type hints across all handler, adapter, and connection modules
- Migrated all imports from `omni.isaac.*` to `isaacsim.*` for Isaac Sim 5.1.0 compatibility
- Refreshed project documentation to reflect the current Isaac Sim `5.1.0`-focused architecture
- Reworked the README with a clearer quickstart, architecture overview, and example prompting workflow
- Updated build scripts to use installed `isaacsim-mcp-server` CLI
- Added MIT License to all source files; updated copyright headers for fork continuation
- Now documents `39` MCP tools across `8` categories

### Fixed
- Correct argument order in `set_channel_enabled` (issue #2 bug 1)
- Use PhysX velocity API for accurate runtime readings (issue #2 bug 2)
- Read runtime joint targets from articulation controller (issue #2 bug 3)
- Flatten `execute_script` and `reload_script` response structure (issue #2 bug 4)
- Use `add_message_consumer` API for Isaac Sim 5.1 log listener
- Compare log level enum by value for Isaac Sim 5.1 compatibility
- Use USD `RigidBodyAPI` velocity attrs instead of missing PhysX methods
- Initialize `SingleArticulation` before accessing controller APIs
- `scene.clear` now removes all user prims including root-level ones
- Fix transform precision conflict and URDF file validation
- Remove dead code and fix adapter bypass in handlers

### Tests
- Added 43 integration tests for all tool categories
- Updated structural tests for new observability methods

## [0.3.0] - 2025-04-22

### Added
- USD asset search integration with `search_3d_usd_by_text` tool
- Ability to search and load pre-existing 3D models from USD libraries
- Support for custom positioning and scaling of USD models
- Direct model transformation capabilities with the improved `transform` tool
- Enhanced scene management with multi-object placement

### Improved
- Scene object manipulation with precise positioning controls
- Asset loading performance and reliability
- Error handling for model search and placement
- Integration with existing physics scene management

### Technical Details
- Advanced USD model retrieval system
- Optimized asset loading pipeline
- Position and scale customization for USD models
- Better compatibility with Isaac Sim's native USD handling

## [0.2.1] - 2025-04-15

### Added
- Beaver3D integration for 3D model generation from text prompts and images
- Asynchronous model loading with asyncio support
- Task caching system to prevent duplicate model generation
- New MCP tools:
  - `generate_3d_from_text_or_image` for AI-powered 3D asset creation
  - `transform` for manipulating generated 3D models in the scene
- Texture and material binding for generated 3D models

### Improved
- Asynchronous command execution with `run_coroutine`
- Error handling and reporting for 3D generation tasks
- Performance optimizations for model loading

### Technical Details
- Integration with Beaver3D API for 3D generation
- Task monitoring with callback support
- Position and scale customization for generated models

## [0.1.0] - 2025-04-02

### Added
- Initial implementation of Isaac Sim MCP Extension
- Natural language control interface for Isaac Sim through MCP framework
- Core robot manipulation capabilities:
  - Dynamic placement and positioning of robots (Franka, G1, Go1, Jetbot)
  - Robot movement controls with position updates
  - Multi-robot grid creation (3x3 arrangement support)
- Advanced simulation features:
  - Quadruped robot walking simulation with waypoint navigation
  - Physics-based interactions between robots and environment
  - Custom lighting controls for better scene visualization
- Environment enrichment:
  - Various obstacle types: boxes, spheres, cylinders, cones
  - Wall creation for maze-like environments
  - Dynamic obstacle placement with customizable properties
- Development tools:
  - MCP server integration with Cursor AI
  - Debug interface accessible via local web server
  - Connection status verification with `get_scene_info`
- Documentation:
  - Installation instructions
  - Example prompts for common simulation scenarios
  - Configuration guidelines

### Technical Details
- Extension server running on localhost:8766
- Compatible with NVIDIA Isaac Sim 4.2.0
- Support for Python 3.9+
- MIT License for open development 
