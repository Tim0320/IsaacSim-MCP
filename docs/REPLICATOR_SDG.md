# Replicator synthetic-data jobs

Task 4.3 adds a bounded, typed control plane around Isaac Sim 6.0.1
`omni.replicator.core` without exposing arbitrary Python as the normal path.

## Public lifecycle

1. `get_replicator_status` reports extension/orchestrator state, retained and
   active jobs, writer/trigger ownership, supported annotations, and limits.
2. `create_sdg_job` validates a camera, writer settings, trigger count, seed,
   annotations, resolution, and typed randomizers. It defaults to preview.
3. `start_sdg_job` schedules a background coroutine and returns immediately.
4. `get_sdg_job_status` reports `configured`, `starting`, `running`,
   `cancelling`, `finalizing`, or a terminal `completed|cancelled|error` state.
5. `cancel_sdg_job` requests cancellation at the next completed-frame boundary.
6. `get_sdg_manifest` is available only after terminal cleanup.
7. `delete_sdg_job` removes a terminal/configured record and can delete all
   managed data and manifest artifacts.

All writes default to `preview=true`. At most 32 jobs may be retained, one job
may run at a time, and one job is limited to 1,000 frames, 4096 pixels on either
axis, 16,777,216 total pixels, 32 randomizer records and 128 prims per record.

## Writer and annotations

The first contract intentionally fixes `writer.name=BasicWriter` and
`trigger.mode=manual`. Live-supported annotations are RGB and colorized
semantic, instance, and instance-ID segmentation. The handler calls
`step_async` once per frame; the MCP request itself never blocks for the full
capture loop.

Isaac Sim 6.0.1's BasicWriter NumPy backend passes the removed `fix_imports`
argument for bounding boxes and other NumPy outputs in this runtime. Those
annotations are reported as unavailable and rejected before job creation;
partial JSON metadata is not accepted as a successful bbox export. Distance,
occlusion, normals, motion vectors and camera parameters also remain
unavailable until individually live-verified.

Every raw output is ingested into the common managed artifact store, then the
temporary job directory is removed. The terminal manifest records:

- requested/completed frames and terminal state;
- each file's managed handle, relative producer path, format, bytes and SHA-256;
- file and unique-frame counts per requested annotation;
- typed normalized configuration and exact randomization trace;
- a SHA-256 of the sorted randomization trace;
- writer, render-product and trigger cleanup read-back.

## Deterministic randomization

`seed` is applied to Replicator and to a job-local Python RNG. `transform`
records accept position, rotation and scale min/max vectors. `light` records
accept intensity scalar and color vector ranges. Target prims must be below
`/World`, and the exact USD attributes must already exist. Their original
values are captured once and restored on completion, cancellation, or error.

The deterministic promise covers normalized configuration and the generated
randomization trace. GPU renderer output hashes are recorded for integrity but
are not treated as cross-machine bitwise determinism.

## Cancellation and cleanup

Cancellation is cooperative at a completed-frame boundary. Terminal state is
not published until writer detach, render-product destruction, attribute
restore, artifact ingestion, and manifest creation finish. Status then reports:

```json
{
  "cleanup": {
    "writer_detached": true,
    "render_product_destroyed": true,
    "trigger_removed": true
  }
}
```

The handler also restores the prior `/omni/replicator/captureOnPlay` setting.
Only handler-owned writer/render-product state is torn down; unrelated scene
prims and Replicator resources are not scanned or deleted.

## Verification

Run only against a disposable live stage namespace:

```powershell
.\.venv\Scripts\python.exe scripts\verify_replicator_sdg_live.py
```

The Isaac Sim 6.0.1 run on 2026-08-25 used Replicator `1.13.27`. Two seed-4317
jobs each produced two RGB and semantic-segmentation frames with identical
trace/hash. A 100-frame job cancelled at a bounded frame boundary with all three
cleanup flags true. Finally the scratch prim was absent, the job registry was
empty, and the timeline remained stopped.

Do not substitute `tests/test_integration.py`: when TCP 8766 is live, that broad
suite creates Camera/LiDAR/robot fixtures without equivalent teardown.
