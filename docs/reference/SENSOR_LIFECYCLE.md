# Camera and LiDAR lifecycle

IsaacSim-MCP provides one verified deletion contract for managed RTX Camera and
LiDAR sensors. Use `delete_sensor` directly. `delete_object` detects managed
sensors and routes them through the same lifecycle.

## Prerequisite

The timeline must not be playing. Pause or Stop is accepted. A playing timeline
returns `SENSOR_DELETE_REQUIRES_NON_PLAYING` before resources or USD are changed.

`post_delete_updates` controls the verification window. It must be an integer
from 1 through 240 and defaults to 8.

## Teardown order

1. Identify the Camera or LiDAR runtime and capture its annotator, writer, Hydra
   texture/RenderProduct, actual LiDAR prim, cache, and metadata state.
2. On Isaac Sim 6, call the runtime `_invalidate_sensor()` path used by NVIDIA's
   own sensor destructor. It detaches writers and annotators, destroys the Hydra
   texture, and clears the runtime collections.
3. Verify that the runtime no longer owns annotators, writers, or a Hydra
   texture. A failure returns `SENSOR_RELEASE_FAILED` and keeps the cache
   reference so the caller can inspect or retry it.
4. Evict Camera/LiDAR runtime cache and LiDAR actual/config metadata, then delete
   the USD sensor prim.
5. Await the requested Kit updates and read the stage and adapter state again.
   Success requires all prim, RenderProduct, cache, and metadata checks to be
   absent. A survivor returns `SENSOR_DELETE_INCOMPLETE`.

Timeline Stop uses the same runtime teardown but preserves LiDAR authoring
metadata, allowing a later capture to rebuild the wrapper from the existing USD
sensor. Creating a sensor at an already cached path first releases the previous
runtime, preventing duplicate pipelines.

## Named tool

```text
delete_sensor(
  prim_path="/World/Camera",
  post_delete_updates=32
)
```

The success payload contains `lifecycle` evidence and the final `readback` map:

```json
{
  "status": "success",
  "prim_path": "/World/Camera",
  "post_delete_updates": 32,
  "lifecycle": {
    "teardown_method": "_invalidate_sensor",
    "annotators_after": [],
    "writers_after": [],
    "render_product_released": true,
    "cache_evicted": true,
    "metadata_evicted": true
  },
  "readback": {
    "prim_absent": true,
    "actual_prim_absent": true,
    "render_product_absent": true,
    "camera_cache_absent": true,
    "lidar_cache_absent": true,
    "lidar_path_metadata_absent": true,
    "lidar_config_metadata_absent": true
  }
}
```

## Stable errors

| Code | Meaning |
|---|---|
| `SENSOR_PATH_REQUIRED` | `prim_path` is empty |
| `INVALID_POST_DELETE_UPDATES` | Verification window is outside `1..240` or is not an integer |
| `SENSOR_DELETE_REQUIRES_NON_PLAYING` | Timeline is playing |
| `SENSOR_DELETE_STATE_UNAVAILABLE` | Timeline state could not be verified; deletion did not start |
| `SENSOR_NOT_FOUND` | Path is not a managed Camera/LiDAR and has no matching sensor prim type |
| `SENSOR_RELEASE_FAILED` | Runtime teardown failed; the cache reference is retained |
| `SENSOR_PRIM_DELETE_FAILED` | USD prim deletion failed after teardown |
| `SENSOR_DELETE_INCOMPLETE` | A prim, RenderProduct, cache entry, or metadata entry survived the update window |

## Isaac Sim 6.0.1 verification

Run the live scratch harness while the extension is reachable on TCP `8766`:

```powershell
.venv\Scripts\python.exe scripts\verify_sensor_lifecycle_live.py
```

The harness runs two Camera/LiDAR cycles at the same paths. Cycle one deletes
with `delete_sensor`; cycle two deletes with `delete_object`. It requires typed
Camera and LiDAR read-back, exactly one RenderProduct per sensor before each
delete, complete absence after 32 Kit updates, successful same-path recreation,
no duplicate pipeline, and complete scratch cleanup. Before any write, it stops
a playing timeline and refuses a stage containing prims outside the default
Isaac Sim baseline and its dedicated `MCP_Task_1_6` namespace; it never clears
an unrelated user stage.
