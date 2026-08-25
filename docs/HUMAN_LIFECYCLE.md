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
- `bake_navmesh`: starts a bounded bake and returns ready/not-ready read-back.

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
- `HUMAN_PREREQUISITE_MISSING`: the runtime agent is not ready or a required runtime state is absent.
- `HUMAN_TASK_REJECTED`: Behavior Core rejected the task, usually because initialization is incomplete or a target is not reachable on the NavMesh.
- `TIMELINE_STATE_CONFLICT`: the current timeline state cannot safely perform the operation.
- `NAVMESH_VOLUME_NOT_FOUND`: bake was requested without a NavMeshVolume.
- `NAVMESH_BAKE_FAILED`: bounded baking ended without a usable NavMesh.
- `HUMAN_DELETE_FAILED`: exact deletion or its read-back failed.

## Live validation

`scripts/verify_human_lifecycle_live.py` passed on 2026-08-25 with Isaac Sim `6.0.1-rc.7`, IRA `1.6.8`, and Behavior/Navigation Core `110.1.4`. It proved ready NavMesh baking, schema `1.0` ownership, stopped-state rejection, MoveTo acceptance plus `0.2639` stage-unit position change, LookAt, Idle, exact deletion, fixture/list restoration and stopped timeline. The run left TCP `8766` healthy, no bounded error/crash signatures and no new native dumps. Subsequent hot reloads emitted only the known ext-folder warnings for repository directories that do not contain `extension.toml`.

The verifier uses Navigation Core's official `CreateNavMeshVolumeCommand` and a physics ground. Navigation Core 110.1 needs five application updates after volume authoring so the native interface receives USD notices. A scaled Cube is not accepted as equivalent live bake evidence. Keep this workflow out of `tests/test_integration.py`, which can accumulate unrelated stage fixtures before teardown.
