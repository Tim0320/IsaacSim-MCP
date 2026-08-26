# Robot joint drive configuration contract

`set_joint_drive_config` is the typed Isaac Sim 6.x write surface for
articulation drive gains, effort/velocity limits, and drive mode.

## Request

Required:

- `prim_path`: articulation root USD path.
- At least one of `stiffness`, `damping`, `max_force`, `max_velocity`, or
  `drive_type`.

Optional subset selector:

- `joint_names`: exact, case-sensitive names in caller order.
- `joint_indices`: zero-based DOF indices in caller order.

The selectors are mutually exclusive. Omitting both selects every DOF. Empty,
duplicate, unknown, non-integer, or out-of-range selectors are rejected before
the adapter write.

Numeric fields are one finite, non-negative float32-representable value applied
to every selected DOF. Booleans, NaN, infinity, negative values, and values
larger than `3.4028234663852886e38` are rejected. `drive_type` is `force` or
`acceleration`.

## Units

| Field | Revolute | Prismatic |
|---|---|---|
| `stiffness` | newton-meters/radian | newtons/meter |
| `damping` | newton-meter-seconds/radian | newton-seconds/meter |
| `max_force` | newton-meters | newtons |
| `max_velocity` | radians/second | meters/second |

The stopped-timeline setter authors `UsdPhysics.DriveAPI` and
`PhysxSchema.PhysxJointAPI` directly. Read-back uses the V6 experimental
Articulation API, which converts angular USD attributes stored per degree into
runtime per-radian values. Responses therefore never expose raw per-degree
gains as if they were SI gains.

## Lifecycle and atomicity

The timeline must be `stopped`. The handler validates the complete request,
backend, selector, and all values before applying any field.

The adapter snapshots every selected field before writing. If an apply call
fails, it restores already-written fields in reverse order. A successful
rollback returns `JOINT_DRIVE_CONFIG_FAILED` with `applied=false`. A rollback
failure returns `JOINT_DRIVE_ROLLBACK_FAILED`, `status=partial`,
`applied=null`, and must be treated as an unknown live state.

A successful write immediately reads back all selected fields. If the write
succeeds but read-back fails, the response is `JOINT_DRIVE_READBACK_FAILED`,
`status=partial`, and `applied=true`.

## Backend matrix

| Field | PhysX | Newton |
|---|---|---|
| stiffness/damping | supported and live verified | USD DriveAPI path, unverified |
| max force | supported and live verified | USD DriveAPI path, unverified |
| drive type | supported and live verified | USD DriveAPI path, unverified |
| max velocity | supported through `PhysxJointAPI` | unsupported |

`get_capabilities` reports this matrix from the current backend. Newton fields
must remain unverified until a dedicated Newton live run passes.

## Stable validation codes

- `EMPTY_JOINT_DRIVE_CONFIG`
- `INVALID_JOINT_DRIVE_VALUE`
- `INVALID_JOINT_DRIVE_TYPE`
- `JOINT_SELECTOR_CONFLICT`
- `EMPTY_JOINT_SELECTOR`
- `DUPLICATE_JOINT_SELECTOR`
- `JOINT_NOT_FOUND`
- `INVALID_JOINT_INDEX`
- `JOINT_INDEX_OUT_OF_RANGE`
- `JOINT_DRIVE_TIMELINE_ACTIVE`
- `JOINT_DRIVE_FIELD_UNSUPPORTED`
- `JOINT_DRIVE_CONFIG_UNSUPPORTED`
- `JOINT_DRIVE_CONFIG_FAILED`
- `JOINT_DRIVE_ROLLBACK_FAILED`
- `JOINT_DRIVE_READBACK_FAILED`

## Verification

Run against a visible Isaac Sim 6.0.1 instance using the repository extension:

```powershell
uv run python scripts/verify_robot_joint_drive_config_live.py
```

The verifier refuses a non-scratch stage, uses a dedicated Franka prim, and
checks before/after values, invalid-value and invalid-name atomicity,
active-timeline rejection, and full cleanup. Current support evidence must also
include separate post-run process/port, log, active-display GPU, and native-dump
checks.
