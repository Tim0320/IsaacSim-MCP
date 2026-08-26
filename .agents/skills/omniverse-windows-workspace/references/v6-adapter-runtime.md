# IsaacAdapterV6 runtime boundary

Read this reference before changing `adapters/v6.py` or `adapters/v6_runtime/`.

## Authority and public boundary

- `IsaacAdapterV6` is the 64-method explicit facade required by `IsaacAdapterBase` and handlers.
- Handlers must not import `v6_runtime`; do not replace forwarders with `__getattr__`, generated methods, or another dynamic delegation mechanism.
- Preserve public signatures, base-policy calls, stable errors, monkeypatch targets and runtime read-back. Add a policy bridge when a component must call inherited/facade behavior.
- Runtime components may depend on lower-level components in the documented direction; they must not own or strongly reference the facade. Bridges use weak references.

The maintained component/dependency table is in [ARCHITECTURE.md](../../../../ARCHITECTURE.md#isaacadapterv6-runtime-composition). Historical slice evidence is in [the decomposition task](../../../../docs/research/ISAACSIM_MCP_V6_ADAPTER_DECOMPOSITION_TASK.md).

## State ownership

- `RobotRuntime`: articulation cache.
- `MotionRuntime`: trajectories, motion jobs and update subscription. Do not move MCP unified job-manager semantics here.
- `SensorRuntime`: camera/LiDAR wrappers, LiDAR authoring metadata and pending render request.
- `SimulationRuntime`: persistent reload namespaces.
- `MaterialRuntime`, `LightingRuntime` and `AssetRuntime`: cohesive authoring/integration operations with no job state.
- Facade: component composition and cross-domain timeline-stop coordination only.

## Deferred handler domains

Do not create `GraphRuntime`, `Ros2Runtime`, `ReplicatorRuntime` or `HumanRuntime` merely to complete a directory shape. Their raw Isaac calls are currently interleaved with handler-owned stable errors, prerequisites, ownership, job/artifact or workflow orchestration. A Phase F change must first define and test a raw-operation boundary without making handlers depend on V6 internals.

## Change and verification route

1. Identify the single state owner and allowed dependency direction before moving code.
2. Keep facade methods explicit and preserve their exact signatures.
3. Add focused component/facade tests plus the 64-method and handler-boundary contracts.
4. Update `scripts/hot_reload_extension.py` in dependency order when adding a module.
5. Run the full offline suite, generated tool inventory, Ruff/format on changed files and `git diff --check`.
6. For runtime import, lifecycle or mutation changes, make a verified backup, hot reload the extension, run the guarded domain verifier, confirm exact scratch cleanup, timeline/Kit/TCP health, and record live evidence.
