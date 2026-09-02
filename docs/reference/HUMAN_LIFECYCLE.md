# Human lifecycle and Behavior Agent control

Item 19 adds typed NVIDIA IRA human lifecycle control for Isaac Sim 6.0.1. The implementation uses the installed `isaacsim.replicator.agent.core` character loader, `omni.anim.behavior.core.IBehaviorAgent`, and `omni.anim.navigation.core`; it does not drive the UI or mutate private runtime caches.

## Named tools

- `spawn_human`: creates one or more IRA characters and records a schema `1.0` MCP ownership marker on each created character root.
- `list_humans`: lists owned and, optionally, external Behavior Agent characters in stable path order.
- `get_human`: returns the character root, BehaviorAgentAPI path, position, facing, velocity, current task and supported behavior settings.
- `delete_human`: previews by default and deletes only the exact MCP-owned character. It may remove its group only when that group is empty.
- `set_human_target`: issues `IBehaviorAgent.move_to` to exactly one point or prim target.
- `set_human_look_at`: issues `IBehaviorAgent.look_at` to exactly one point or prim target.
- `set_human_idle`: issues `IBehaviorAgent.idle`, optionally with one facing target.
- `set_human_behavior`: updates the live enabled state, locomotion speed, allowed NavMesh areas, obstacle avoidance and auto avoidance.
- `get_navmesh_status`: reports NavMesh readiness, bake state, volumes, area names and prerequisites.
- `bake_navmesh`: starts a bounded bake and returns ready/not-ready read-back with native lifecycle diagnostics.

## Dependency-aware acceptance

Human control is one dependent lifecycle, not a set of independent calls. A live acceptance run must preserve this order:

```text
official physics GroundPlane + NavMeshVolume fixture
→ bake_navmesh
→ spawn_human
→ set_human_action / set_human_behavior
→ delete_human
```

`set_human_action` is the consolidated tool surface for target, look-at and idle actions; the corresponding legacy tools are `set_human_target`, `set_human_look_at` and `set_human_idle`. Do not run or grade either action surface before `spawn_human` returns an owned `human_path`.

If `spawn_human` fails, that owned path does not exist. A later action, behavior update or deletion may therefore return `HUMAN_NOT_FOUND`; in an acceptance report these downstream rows are `blocked_by=spawn_human`, not separate defects in `set_human_action`, `set_human_behavior` or `delete_human`. Only grade those tools after successful spawn read-back.

The bake fixture must use a real physics GroundPlane (the verifier authors it through `AddGroundPlaneCommand.execute`) and Navigation Core's `CreateNavMeshVolumeCommand` with an include volume. A visually similar scaled Cube is not GroundPlane/NavMesh evidence and must not be used to mark baking or human navigation as passed.

Volume authoring is asynchronous from Navigation Core's native interface. Allow the documented notice-processing updates before starting the bake, and allow the bounded publication-settle window after the native baking flag clears. Do not assume either a USD-visible volume or a cleared baking flag means `get_navmesh()` has already published its result. Diagnostics retain `reason`, `start_result`, `bake_frames`, `elapsed_seconds`, `settle_frames`, and `cancel_result`. `max_frames` is the native bake-poll cap; the five notice-processing and up to five publication-settle updates are reported separately. `timeout_seconds` bounds the complete operation by wall clock (default 120, maximum 240), with a separately bounded cancellation-confirmation grace period. Native completion at frame 1 without a NavMesh is still a failed bake after the settle window.

## Safety and timeline rules

All new writes default to `preview=true`. Runtime task commands require a playing timeline because task acceptance while stopped is not execution evidence. NavMesh bake and human deletion require a stopped or paused timeline. Control and deletion fail closed for external characters that do not carry the MCP ownership marker; read-only list/get may still describe them.

`speed_mps` is converted to stage units per second using `metersPerUnit`, matching IRA 1.6.8 behavior for Behavior Core 110.1. The response reports the raw runtime speed as `speed_stage_units_per_second` so callers can verify the applied value.

Task responses include the task ID, name, status, running flag and an immediate Behavior Agent read-back. This proves dispatch and runtime acceptance, not target arrival. Arrival must be verified later from `get_human` position/task state.

## Stable errors

- `INVALID_HUMAN_REQUEST`: invalid path, target, duration, speed, area list or bound.
- `HUMAN_NOT_FOUND`: the requested prim does not exist.
- `HUMAN_NOT_OWNED`: a mutation targeted an external human.
- `HUMAN_OWNERSHIP_MISMATCH`: an owned marker's group path does not match the exact human parent.
- `HUMAN_AGENT_NOT_FOUND`: the character has no BehaviorAgentAPI descendant.
- `HUMAN_PREREQUISITE_MISSING`: the runtime agent is not ready or a required runtime state is absent. A spawn blocked by baking returns `blocked_by="bake_navmesh"` plus `navmesh_diagnostics`; dependent action, behavior, and delete checks remain blocked until spawn succeeds.
- `HUMAN_TASK_REJECTED`: Behavior Core rejected the task, usually because initialization is incomplete or a target is not reachable on the NavMesh.
- `TIMELINE_STATE_CONFLICT`: the current timeline state cannot safely perform the operation.
- `NAVMESH_VOLUME_NOT_FOUND`: bake was requested without a NavMeshVolume.
- `NAVMESH_BAKE_FAILED`: bounded baking ended without a usable NavMesh. `readback.reason` distinguishes `start_rejected`, `completed_without_navmesh`, `max_frames_exceeded`, and `timeout`; `bake_frames=1` can mean the native bake completed unsuccessfully on its first update, not that the requested limit was ignored. Frame-limit or wall-clock expiry attempts native bake cancellation and reports its outcome.
- `HUMAN_DELETE_FAILED`: exact deletion or its read-back failed.

## Live validation

`scripts/verify_human_lifecycle_live.py` passed on 2026-08-25 with Isaac Sim `6.0.1-rc.7`, IRA `1.6.8`, and Behavior/Navigation Core `110.1.4`. It proved ready NavMesh baking, schema `1.0` ownership, stopped-state rejection, MoveTo acceptance plus `0.2639` stage-unit position change, LookAt, Idle, exact deletion, fixture/list restoration and stopped timeline. The run left TCP `8766` healthy, no bounded error/crash signatures and no new native dumps. Subsequent hot reloads emitted only the known ext-folder warnings for repository directories that do not contain `extension.toml`.

This is preserved historical evidence, not proof for a newly restarted or modified runtime. The current runtime must rerun the complete dependency chain before its human tools are marked live-passed; a failed spawn blocks the downstream rows as described above.

The verifier uses Navigation Core's official `CreateNavMeshVolumeCommand` and a physics GroundPlane. Navigation Core 110.1 needs five application updates after volume authoring so the native interface receives USD notices. Keep this workflow out of `tests/test_integration.py`, which can accumulate unrelated stage fixtures before teardown.
