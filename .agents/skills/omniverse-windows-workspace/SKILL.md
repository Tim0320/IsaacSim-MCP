---
name: omniverse-windows-workspace
description: Operate, develop, diagnose, and maintain a Windows NVIDIA Omniverse and Isaac Sim MCP workspace. Use whenever a request mentions Omniverse, Isaac Sim, Isaac Lab, OpenUSD, USD, pxr, omni, Kit, OmniUI, physics or material authoring, stage composition, OmniGraph or ScriptNode, ROS 2, Replicator SDG, IRA humans or Behavior Agents, robot or factory simulation, NVIDIA assets, VS Code MCP, the live Isaac Sim extension socket, headless SimulationApp, or importing omni without opening the GUI. Routes documentation questions separately from live scene control, selects the Isaac runtime for local code, and preserves credentials, scenes, and unrelated Git changes.
---

# Omniverse Windows Workspace

Use the installed Windows baseline and choose the correct execution path before changing anything.

## Start every task

1. Run `scripts/check-environment.ps1` from this skill directory.
2. Read [references/mcp-routing.md](references/mcp-routing.md) before choosing an MCP server or launcher.
3. Read [references/environment.md](references/environment.md) when paths, versions, Python runtimes, or installation portability matter.
4. Read [references/isaacsim-mcp-1x.md](references/isaacsim-mcp-1x.md) when the request involves Camera, LiDAR, artifacts, sensor deletion, tasks 1.1 through 1.6, or the completed IsaacSim-MCP 1.x research baseline.
5. Read [references/isaacsim-mcp-2x.md](references/isaacsim-mcp-2x.md) when the request involves Robot joint state/commands, Drive configuration, IK/trajectory jobs, grippers, mobile bases, or tasks 2.1 through 2.4.
6. Read [references/isaacsim-mcp-3x.md](references/isaacsim-mcp-3x.md) when the request involves physics parameters, backend capability state, rigid bodies, colliders, joints, physics materials, Stage lifecycle, USD composition, variants, semantics, typed attributes, or tasks 3.1 through 3.5.
7. Read [references/isaacsim-mcp-4x.md](references/isaacsim-mcp-4x.md) when the request involves Action Graph lifecycle, ScriptNode configure/reload, ROS 2 workflows, Replicator SDG jobs, IRA humans, Behavior Agents, NavMesh, or tasks 4.1 through 4.4.
8. Inspect current files, Git state, and processes. Treat detected values as evidence and examples as fallbacks.

Do not reinstall Isaac Sim, Isaac Lab, CUDA, Docker, or MCP dependencies merely because a process is stopped or a tool is unavailable. Diagnose the existing installation first.

## Route the request

- For NVIDIA API lookup, examples, extensions, settings, or UI patterns, use configured NVIDIA documentation MCP services.
- For creating, editing, querying, simulating, or deleting objects in a running Isaac Sim stage, use this repository's stdio MCP server and the live Isaac Sim extension socket.
- For repository code, launchers, adapters, or MCP defects, resolve the repository root from the skill location and preserve unrelated uncommitted changes.
- For Isaac Lab environments, training, managers, tasks, or wrappers, resolve `ISAACLAB_ROOT` and verify its current version and Git state before editing.
- For `import omni`, `pxr`, or `isaacsim`, use the Isaac Sim `python.bat` or a Kit application runtime. Do not test those imports with a generic system Python.

## IsaacSim-MCP 1.x baseline

Tasks 1.1 through 1.6 are the completed Camera, LiDAR, artifact transport, and sensor lifecycle baseline for Isaac Sim 6.0.1. Use the 1.x reference as the navigation index, then read the linked contract and verifier for the requested capability. Do not rely on a short summary when changing a response schema, runtime lifecycle, transfer limit, or live verification rule.

Treat the recorded 2026-08-23 live results as historical evidence. Recheck the current Git checkout, `get_capabilities`, Isaac Sim version, extension command count, live port, physics GPU selection, and scratch stage before claiming current verification.

## IsaacSim-MCP 2.x baseline

Tasks 2.1 through 2.4 are the completed Robot-control baseline for Isaac Sim 6.0.1: atomic joint state/commands, stopped-timeline Drive configuration, bounded Lula motion jobs, and explicit-profile gripper/mobile-base commands. Start with the 2.x reference for the numbering map, invariants, known runtime hazards, and recorded acceptance evidence. Then read the linked contract and live verifier for the requested capability.

Treat every recorded 2.x result as historical evidence. Before a current support claim, confirm the canonical checkout, 68-command registry, PhysX backend, required extensions, TCP `8766`, active-display physics GPU, empty scratch Stage, target/measured-state read-back, owned-fixture cleanup, Kit survival, run-scoped logs, and native dumps. If a run reports a CUDA device mismatch, external-memory failure, GPU page fault, or `ERROR_DEVICE_LOST`, discard that runtime and restart before rerunning 2.4, then 2.3.

## IsaacSim-MCP 3.x baseline

Tasks 3.1 through 3.5 are the completed Physics and USD-authoring baseline for Isaac Sim 6.0.1: physics-scene parameters, fail-closed PhysX/Newton capability discovery, typed body/collider/joint authoring, physics materials, and guarded Stage/layer/composition operations. Start with the 3.x reference for the numbering map, cross-task invariants, exact contracts, verifier routes, and destructive-integration warning.

Treat recorded 3.x results as historical evidence. Recheck the current checkout, command registry, capability matrix, active backend, physics GPU selection, stopped timeline, scratch guard, read-back/rollback, fixture cleanup, Kit/TCP health, run-scoped log, and native dumps before claiming current support. Never promote Newton from `untested` or `unsupported` using shared USD schemas or import success.

## IsaacSim-MCP 4.x baseline

Tasks 4.1 through 4.4 are the completed integration-lifecycle baseline for Isaac Sim 6.0.1: guarded OmniGraph and ScriptNode control, typed ROS 2 publisher graphs, bounded Replicator SDG jobs, and ownership-scoped IRA human/Behavior Agent control. Start with the 4.x reference for the numbering map, prerequisites, timeline/preview rules, ownership boundaries, verifier routes, and live-evidence limits.

Treat recorded 4.x command counts and live results as historical evidence. Recheck the current checkout, `get_capabilities`, required extension versions, timeline state, owned scratch namespace, response read-back/rollback, fixture and artifact cleanup, Kit/TCP health, run-scoped logs, and native dumps before claiming current support. Clock subscriber evidence does not prove asset-specific ROS 2 publishers; task acceptance does not prove a human reached its target; a deterministic SDG trace does not promise cross-machine renderer hashes.

## Live scene workflow

1. Resolve `ISAACSIM_ROOT`, defaulting to `C:\isaacsim` when it is not configured.
2. Confirm this repository's virtual environment and launchers exist.
3. Start Isaac Sim with `scripts\run_isaac_sim.ps1` when the configured extension port is closed. Keep the GUI visible when the user needs to inspect it.
4. Start the stdio MCP through `scripts\run_mcp_server.ps1` only when the client has not started it automatically.
5. Verify the extension listener before sending scene-control commands.
6. Prefer exposed MCP tools for live stage changes and verify the resulting stage state.

Never claim a scene edit succeeded from code generation alone. Verify through an MCP query, USD inspection, repository verifier, or visible stage evidence.

## Safety and preservation

- Keep `NVIDIA_API_KEY`, `NGC_API_KEY`, `ARK_API_KEY`, and other credentials out of source files, MCP JSON, reports, logs, and skill resources.
- Inspect `git status` before editing the MCP repository or Isaac Lab; never discard unrelated changes.
- Do not use a documentation MCP response as evidence that a live stage was modified.
- Treat a successful Python import as runtime evidence only. It does not prove the Isaac Sim stage or extension is ready.
- Keep 1.x live tests inside their dedicated scratch namespaces. Refuse or isolate a stage containing unrelated user prims before destructive verification.
- Keep 2.x live tests inside their dedicated scratch namespaces. Run each verifier's read-only guard before Stop, clear, fixture creation, or command writes; only delete verifier-owned robot and physics prims.
- Keep 3.x writes inside verifier-owned scratch namespaces or explicit filesystem scratch roots. Preserve existing PhysicsScene and Stage root/session layers with snapshot/restore. Do not run `tests/test_integration.py` as part of an offline suite while live TCP `8766` is reachable.
- Keep 4.x writes inside exact MCP-owned graph, job, workflow, human, artifact, and scratch namespaces. Honor preview/timeline prerequisites, never mutate external humans or graphs, and use only the dedicated 4.x verifiers for live acceptance. Do not substitute `tests/test_integration.py` while TCP `8766` is reachable.
- Obtain explicit authorization before publishing, deleting, or overwriting external or material data.

## Finish with evidence

Report the runtime used, the MCP route selected, exact commands or tools executed, files or scene objects changed, and the verification result. State any unavailable process, key, port, or tool directly.
