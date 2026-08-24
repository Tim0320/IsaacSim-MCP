# IsaacSim-MCP research baseline 1.x

This reference maps the conversation and research labels `1.1` through `1.6`
to the completed Phase 1 items in
`docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`. Use it as a navigation index,
not as a substitute for the linked contract, source, tests, or current live
read-back.

## Numbering map

| Research label | Task document item | Capability | Named tools | Contract | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 1.1 | Phase 1 item 1 | Camera RGB metadata, managed PNG artifact, bounded inline PNG | `create_camera`, `capture_image` | `docs/CAMERA_RGB.md` | `scripts/verify_camera_rgb_live.py` |
| 1.2 | Phase 1 item 2 | Depth, distance, segmentation, normals, motion vectors, calibration | `capture_camera_output`, `get_camera_calibration` | `docs/CAMERA_OUTPUTS.md` | `scripts/verify_camera_outputs_live.py` |
| 1.3 | Phase 1 item 3 | Typed RTX LiDAR Cartesian point cloud and auxiliary fields | `get_lidar_point_cloud` | `docs/LIDAR_POINT_CLOUD.md` | `scripts/verify_lidar_point_cloud_live.py` |
| 1.4 | Phase 1 item 4 | Effective RTX LiDAR preset/generic configuration and USD read-back | `create_lidar`, `get_lidar_config` | `docs/LIDAR_CONFIG.md` | `scripts/verify_lidar_config_live.py` |
| 1.5 | Phase 1 item 5 | Shared managed artifact store, chunks, hash, TTL, capacity, cleanup | `get_artifact_info`, `read_artifact`, `delete_artifact`, `cleanup_artifacts` | `docs/ARTIFACT_TRANSPORT.md` | `scripts/verify_artifact_transport_live.py` |
| 1.6 | Phase 1 item 6 | Deterministic Camera/LiDAR teardown, verified deletion, same-path recreation | `delete_sensor`; sensor-aware `delete_object` | `docs/SENSOR_LIFECYCLE.md` | `scripts/verify_sensor_lifecycle_live.py` |

The task document also contains item `1.1a`, the Isaac Sim 6.0.1 multi-GPU
Timeline Stop guard. It is a prerequisite shared by Camera/LiDAR live testing,
not a seventh research capability. Keep `/physics/cudaDevice` on a fixed ordinal
selected by the launcher. Do not restore silent `-1` auto-selection or treat a
renderer multi-GPU setting as a substitute.

## What is implemented

### 1.1 Camera RGB

- `capture_image` supports `metadata|artifact|inline`.
- The managed default is an atomic PNG artifact with dimensions, dtype, frame,
  timestamp, pixel SHA-256, artifact SHA-256, and producer metadata.
- Inline output has a 1 MiB default and a 4 MiB hard cap. Oversize output uses
  `INLINE_SIZE_LIMIT_EXCEEDED`.
- A valid hash or a black empty-stage PNG is insufficient live evidence. Use
  visible geometry and lighting, Play/warm-up, Stop, read-back, post-Stop Kit
  updates, process state, and native-dump/log evidence.

### 1.2 Camera outputs and calibration

- Seven typed outputs are supported: depth, distance-to-image-plane, semantic,
  instance, instance-ID segmentation, normals, and motion vectors.
- Artifact mode stores controlled `.npy`; inline mode carries bounded raw
  little-endian bytes. Responses expose dtype, shape, units, coordinate space,
  frame/timestamp, hashes, and annotator info.
- Calibration exposes intrinsics, camera/world transforms, projection,
  resolution, clipping, and unit conventions.

### 1.3 LiDAR point cloud

- The V6 adapter converts Generic Model Output spherical fields to Cartesian
  meters and returns typed fields instead of only `point_count`.
- Managed `.npz` artifacts contain Cartesian points, range, azimuth, elevation,
  and available intensity/object-ID arrays. Every member has dtype, shape,
  units, byte size, and raw SHA-256.
- Semantic ID is explicitly unavailable when the runtime provides no direct
  field. Do not infer it from object IDs.

### 1.4 LiDAR configuration

- `create_lidar` accepts either a named preset/variant or generic FOV, angular
  resolution, rotation rate, and range. The two modes are mutually exclusive.
- Generic settings author and read back the Isaac Sim 6.0.1 RTX LiDAR Core USD
  schema. Invalid ranges, non-divisible resolutions, unknown arguments, and
  sample-budget violations return stable errors without partial authoring.
- Isaac Sim 6.0.1 emitter channel IDs are one-based. Partial-FOV sensors use
  per-tick output so a frame is not blocked on full 360-degree accumulation.

### 1.5 Artifact transport

- Camera PNG/NPY and LiDAR NPZ use the same managed store and opaque
  `artifact://managed/<id>` handle contract.
- The store enforces a controlled root, random IDs, atomic data/sidecar writes,
  SHA-256, TTL, per-file/total capacity, bounded chunks, traversal protection,
  explicit deletion, and cleanup.
- Explicit caller `output_path` remains unmanaged and returns no managed handle.

### 1.6 Sensor lifecycle

- Isaac Sim 6 uses the NVIDIA runtime `_invalidate_sensor()` teardown path to
  detach writers/annotators, destroy the Hydra texture/RenderProduct, and clear
  runtime collections.
- Release failures return `SENSOR_RELEASE_FAILED` and retain the cache reference
  for inspection or retry. Deletion reports success only after bounded Kit
  updates prove prim, actual LiDAR prim, RenderProduct, cache, and LiDAR metadata
  absence. Survivors return `SENSOR_DELETE_INCOMPLETE`.
- Timeline must be non-playing. Timeline Stop releases runtime state while
  preserving LiDAR authoring metadata. Same-path creation releases an existing
  cached runtime first to prevent duplicate pipelines.
- The live verifier refuses unrelated stage prims, runs both `delete_sensor` and
  sensor-aware `delete_object`, recreates the same paths, and checks cleanup.

## Recorded evidence boundary

The completed 2026-08-23 Isaac Sim `6.0.1-rc.7` runs verified all six items on
`IsaacAdapterV6` and PhysX. The final 1.6 run reported 54 extension commands,
two Camera/LiDAR create-read-delete-recreate cycles, 32 post-delete Kit updates,
no duplicate pipeline, full resource absence, scratch cleanup, a live TCP
server, and no matching native crash signature.

These values are a historical baseline. Before reporting current support:

1. Resolve the exact repository and record Git HEAD/status/remote.
2. Confirm `C:\isaacsim\VERSION`, the active adapter/backend, and the physics GPU
   selection from the current launcher output.
3. Call `get_capabilities`; do not assume the command count or extension states.
4. Confirm TCP `8766` for live control. Documentation MCP output is not stage
   evidence.
5. Use a dedicated scratch namespace and the relevant live verifier. Preserve
   user prims, USD files, artifacts, credentials, and unrelated dirty changes.
6. Record read-back, hashes where applicable, process/port survival, cleanup,
   and log/native-dump evidence. Static tests alone are not live verification.

## Reading order for future work

1. Read the matching row in this reference.
2. Read the linked contract document completely.
3. Read `docs/CAPABILITIES.md` and `docs/RESPONSE_SCHEMA.md` for current feature
   flags and envelope rules.
4. Inspect the named tool, extension handler, V6 adapter, focused tests, and live
   verifier before changing behavior.
5. Use `docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md` for full research history,
   limitations, and acceptance evidence.
