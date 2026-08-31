---
name: omniverse-windows-workspace
description: Develop, diagnose, test, and release this Windows Isaac Sim MCP project. Use for repository code, MCP tools, Isaac Sim or Kit runtime work, USD/physics/robot/sensor integrations, live Stage control, capability research, or the project 1.x–6.x evidence baseline. Classifies the task before loading runtime checks or detailed references.
---

# Omniverse Windows Workspace

Classify the request first. Load only the checks and references that can change the result.

## Choose the task route

| Task type | First action | Environment check |
|---|---|---|
| Documentation, architecture, research review, schema explanation | Read the requested source and [authority rules](../../../docs/reference/AUTHORITY.md). | Do not run by default. |
| Repository code, offline tests, refactor, docs generation | Inspect Git root/status and relevant files; preserve unrelated changes. | Run only if the change depends on Isaac/Kit imports, installed paths, GPU, ports, or live evidence. |
| Live Stage query or mutation | Read [MCP routing](references/mcp-routing.md), then run `scripts/check-environment.ps1`. | Required. Verify the listener and read back every mutation. |
| Launcher, installation, runtime, GPU, extension, or port diagnosis | Read [environment](references/environment.md) and [MCP routing](references/mcp-routing.md), then run the environment check. | Required. |
| Release or GitHub publish | Read the [6.x reference](references/isaacsim-mcp-6x.md) and release documentation; verify exact Git identity and backup first. | Required only when the gate or claim includes live/runtime verification. |
| Isaac Lab | Keep it separate from this Isaac Sim MCP repository; resolve its root and current version before editing. | Required for runtime work. |

The environment check reports state; it does not authorize installation, process changes, Stage writes, or publishing. Do not reinstall Isaac Sim, Isaac Lab, CUDA, Docker, or dependencies merely because a process is stopped.

## Load the relevant capability reference

- [1.x](references/isaacsim-mcp-1x.md): Camera, LiDAR, artifacts, and sensor lifecycle.
- [2.x](references/isaacsim-mcp-2x.md): robot joints, drives, motion, grippers, mobile bases, and articulation/physics-tensor lifecycle recovery.
- [3.x](references/isaacsim-mcp-3x.md): physics parameters, backend capability, authoring, materials, and Stage composition.
- [4.x](references/isaacsim-mcp-4x.md): OmniGraph, ScriptNode, ROS 2, Replicator SDG, humans, Behavior Agents, and NavMesh.
- [5.x](references/isaacsim-mcp-5x.md): script policy, command governance, idempotency, jobs, transport, and diagnostics.
- [6.x](references/isaacsim-mcp-6x.md): test layers, scratch-stage safety, profile-aware generated inventory, evidence reports, migration, release gates, and publishing.
- [V6 adapter runtime](references/v6-adapter-runtime.md): read before changing `IsaacAdapterV6`, `v6_runtime`, component state ownership, hot reload order, or the deferred Graph/ROS2/Replicator/Human boundary.

These references contain dated acceptance evidence. They do not replace current `get_capabilities` output or a guarded live verifier.

## Repository and capability authority

- Resolve the repository from this skill location. Do not infer it from a similar repository name.
- Public tool names/count come from `@mcp.tool(...)` decorators, `isaac_mcp.tool_profiles`, and `isaac_mcp.tool_inventory`, not README prose. Read [Tool profiles](../../../docs/reference/TOOL_PROFILES.md) before adding, removing, merging, or hiding public tools.
- Package version comes from `isaac_mcp.__version__`; extension copies must pass parity tests.
- Current backend, extension, command registry, and support state come from `get_capabilities` on the active runtime.
- Reports under `docs/research/` are historical snapshots. Registry presence alone is not a live pass.

Read [docs/reference/AUTHORITY.md](../../../docs/reference/AUTHORITY.md) before changing public tools, versions, capabilities, or evidence generation.

For stale articulation wrappers, invalid physics tensor entities, same-path robot replacement, joint name/value mismatch, or `PhysicsDriveAPI` instance errors, read [Robot runtime lifecycle](../../../docs/reference/ROBOT_RUNTIME_LIFECYCLE.md) and the [V6 adapter runtime reference](references/v6-adapter-runtime.md) before editing.

## Live workflow

1. Confirm the configured Isaac Sim root and version with the environment check.
2. Confirm this repository's virtual environment and launchers exist.
3. Start Isaac Sim with `scripts/run_isaac_sim.ps1` only when live work requires it and the extension port is closed.
4. Verify the loopback extension listener before sending commands.
5. Use named tools before governed script escape hatches.
6. Verify write results with operation-specific read-back, cleanup, Kit/TCP health, and relevant log or dump evidence.

Documentation MCP services answer API questions. Only this repository's `isaac-sim-live` route through TCP `8766` controls the running Stage.

## Safety invariants

- Keep credentials out of source, MCP JSON, reports, logs, skill resources, and commits.
- Preserve unrelated Git changes, user USD files, Stage contents, generated assets, and external processes.
- Keep destructive verification inside an exact scratch Stage and verifier-owned namespaces. Refuse ambiguous or user-owned targets.
- Do not infer Newton support from V6 imports or shared USD schemas. Follow the active backend matrix and fail closed.
- Use explicit physics GPU selection policy on multi-GPU Windows hosts; do not silently restore `/physics/cudaDevice=-1`.
- Do not run legacy destructive integration tests while a user Stage is reachable on TCP `8766`.
- Obtain explicit authorization before push, merge, tag, release, deletion, or material external overwrite.

## Finish with evidence

Report the selected route, files or Stage objects changed, runtime used when relevant, and validation results. State whether evidence is current live verification, offline contract evidence, or a historical research snapshot.
