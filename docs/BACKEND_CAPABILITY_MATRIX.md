# PhysX / Newton backend capability matrix

This contract applies to Isaac Sim 6.0.1 and capability schema `1.1`. The
matrix is returned at `data.backend_matrix` by `get_capabilities`.

## Why the matrix exists

`IsaacAdapterV6` contains code paths shared by PhysX and Newton. Shared code is
not proof that both backends work. Every backend-sensitive feature therefore
has independent support and verification state.

The adapter owns the matrix and the runtime guards. The capability handler only
projects the active backend into `feature_flags`, so discovery and apply paths
cannot maintain conflicting backend rules.

## Record schema

```json
{
  "physx_supported": true,
  "newton_supported": null,
  "untested": ["newton"],
  "backends": {
    "physx": {
      "state": "supported",
      "verification": "verified",
      "evidence": "Isaac Sim 6.0.1 guarded PhysX live matrix"
    },
    "newton": {
      "state": "untested",
      "verification": "untested",
      "reason": "No Isaac Sim 6.0.1 Newton live acceptance evidence"
    }
  }
}
```

`newton_supported` uses three values:

| Value | Meaning |
|---|---|
| `true` | The same feature passed a guarded Newton live acceptance run. |
| `false` | The implementation is known to require a PhysX-only API or runtime path. |
| `null` | Support is unclaimed because the Newton live matrix has not passed. |

Clients must treat `null`, `untested`, `unsupported`, and an unlisted backend as
fail-closed. A V6 adapter, enabled extension, successful import, or shared code
path does not upgrade an item to `supported`.

## Isaac Sim 6.0.1 matrix

| Feature | PhysX | Newton |
|---|---|---|
| `simulation.timeline` | supported / verified | untested |
| `simulation.step` | supported / verified | untested |
| `simulation.reset` | supported / verified | untested |
| `physics.state` | supported / verified | untested |
| `physics.gravity` | supported / verified | untested |
| `physics.time_step` | supported / verified | unsupported, PhysX runtime/schema path |
| `physics.gpu_enabled` | supported / verified | unsupported, PhysX runtime/schema path |
| `sensor.camera` | supported / verified | untested |
| `sensor.lidar` | supported / verified | untested |
| `sensor.lifecycle` | supported / verified | untested |
| `robot.joint_state` | supported / verified | untested |
| `robot.joint_command` | supported / verified | untested |
| `robot.joint_drive_config` | supported / verified | untested |
| `robot.joint_drive_config.max_velocity` | supported / verified | unsupported, `PhysxJointAPI` |
| `motion.ik_and_planning` | supported / verified | untested |
| `robot.gripper_profiles` | supported / verified | untested |
| `robot.mobile_base_profiles` | supported / verified | untested |

The PhysX verification column summarizes the guarded Task 1.x, 2.x, and 3.1
live runs. Feature-specific fixtures, read-back, cleanup, process, GPU, log, and
native-dump evidence remain in their individual contract documents.

No Newton feature is marked supported in this matrix. The three explicit
unsupported rows are implementation facts; the other fourteen rows remain
untested and may only be promoted after a dedicated Newton scratch live run.

## Runtime guard

Adapter code calls `require_backend_capability(feature)` before a known
backend-specific operation. It raises `NotImplementedError` for `untested`,
`unsupported`, unknown, or unlisted active backends. Handlers convert this into
their stable `unsupported` response instead of applying a partial write.

Current guarded operations include:

- `physics.time_step`
- `physics.gpu_enabled`
- `robot.joint_drive_config.max_velocity`

## Live verifier

Run against the live-control route on TCP `8766`:

```powershell
uv run python scripts/verify_backend_capability_matrix_live.py
```

The verifier is read-only. It checks the capability and matrix schema versions,
all 17 rows, active PhysX projection, Newton fail-closed states, and unchanged
scene/simulation snapshots.
