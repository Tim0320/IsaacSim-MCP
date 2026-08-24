# Isaac Sim 6.0.1 physics parameters

Task 3.1 completes the named `set_physics_params` path for the V6 PhysX
adapter. It authors one USD `PhysicsScene`, verifies the same state through the
Isaac Sim runtime API, and returns success only after both read-backs agree.

## Preconditions and units

| Parameter | Unit / accepted values | Mapping |
|---|---|---|
| `gravity` | exactly three finite numbers, stage distance units per second squared | USD gravity direction and magnitude |
| `time_step` | seconds, `[0.0001, 1.0]` | reciprocal must be an integer `timeStepsPerSecond` value |
| `gpu_enabled` | JSON boolean | `true`: GPU dynamics + `GPU` broadphase; `false`: GPU dynamics off + `MBP` broadphase |

For `time_step`, the adapter also keeps
Stage `timeCodesPerSecond` and `/persistent/simulation/minFrameRate` equal to
`timeStepsPerSecond`, and assigns the single scene as SimulationManager's
default. This follows the established Isaac Sim PhysicsContext contract and
makes later tool initialization preserve the selected rate. The MCP adapter's
`_ensure_physics_world()` deliberately calls `setup_simulation()` without a
hard-coded dt; passing `dt=1/60` there would overwrite every prior setting.

At least one parameter is required. The timeline must be `stopped`; the tool
returns `TIMELINE_NOT_STOPPED` before authoring anything when it is playing or
paused. Multiple `PhysicsScene` prims are rejected because there is no safe,
unambiguous target.

`gpu_enabled` controls only scene-level PhysX GPU dynamics and broadphase. It
does not change the launcher-controlled `/physics/cudaDevice` ordinal. Enabling
GPU dynamics may disable CCD as an Isaac Sim/PhysX side effect; the response
reports that fact explicitly.

## Success response

`PHYSICS_PARAMS_APPLIED` contains:

- `requested` and `applied` fields;
- USD read-back for gravity, steps per second, effective time step, GPU
  dynamics, broadphase and CCD;
- runtime read-back for wrapper/SimulationManager time step, min frame-rate,
  Stage time codes, default scene path, GPU dynamics and broadphase;
- `atomic=true` and `physics_gpu_ordinal_changed=false`.

Input validation happens before any Stage write. If an exception occurs while
applying or verifying a valid request, all touched authored attributes are
restored. `PHYSICS_PARAMS_APPLY_FAILED` means rollback succeeded;
`PHYSICS_PARAMS_ROLLBACK_FAILED` is a partial-state warning and must not be
treated as success.

V5 and Newton do not claim support for `time_step` or `gpu_enabled`. Their
capability response keeps these named arguments explicitly `unsupported`.

## Live verification

```powershell
.\.venv\Scripts\python.exe scripts\verify_physics_params_live.py
```

The verifier first runs a read-only scratch-stage guard. It refuses all Stage
and timeline writes when unrelated content exists. An Isaac-created baseline
`/PhysicsScene` is snapshotted rather than deleted. It then verifies
USD/runtime read-back at 120 Hz, steady-state 12-step physics-clock advancement
of 0.1 s after explicit initialization warm-up, invalid-input atomicity,
active-timeline rejection, the CPU/MBP mapping, and exact restoration of scene
attributes, Stage time codes, min frame-rate and default scene path.
