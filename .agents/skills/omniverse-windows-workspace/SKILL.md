---
name: omniverse-windows-workspace
description: Operate, develop, diagnose, and maintain a Windows NVIDIA Omniverse and Isaac Sim MCP workspace. Use whenever a request mentions Omniverse, Isaac Sim, Isaac Lab, OpenUSD, USD, pxr, omni, Kit, OmniUI, robot or factory simulation, NVIDIA assets, VS Code MCP, the live Isaac Sim extension socket, headless SimulationApp, or importing omni without opening the GUI. Routes documentation questions separately from live scene control, selects the Isaac runtime for local code, and preserves credentials, scenes, and unrelated Git changes.
---

# Omniverse Windows Workspace

Use the installed Windows baseline and choose the correct execution path before changing anything.

## Start every task

1. Run `scripts/check-environment.ps1` from this skill directory.
2. Read [references/mcp-routing.md](references/mcp-routing.md) before choosing an MCP server or launcher.
3. Read [references/environment.md](references/environment.md) when paths, versions, Python runtimes, or installation portability matter.
4. Read [references/isaacsim-mcp-1x.md](references/isaacsim-mcp-1x.md) when the request involves Camera, LiDAR, artifacts, sensor deletion, tasks 1.1 through 1.6, or the completed IsaacSim-MCP 1.x research baseline.
5. Inspect current files, Git state, and processes. Treat detected values as evidence and examples as fallbacks.

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
- Obtain explicit authorization before publishing, deleting, or overwriting external or material data.

## Finish with evidence

Report the runtime used, the MCP route selected, exact commands or tools executed, files or scene objects changed, and the verification result. State any unavailable process, key, port, or tool directly.
