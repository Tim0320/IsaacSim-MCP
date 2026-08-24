# Environment discovery and installation

Recheck all values before acting because paths, versions, and branches can change.

## Portable path contract

| Component | Resolution order | Windows fallback |
| --- | --- | --- |
| MCP repository | `-RepositoryRoot`, `ISAACSIM_MCP_REPO`, upward discovery, canonical fallback, legacy fallback | `D:\Dev\IsaacSim-MCP`; older port: `D:\Dev\isaacsim-mcp-server` |
| Isaac Sim | `-IsaacSimRoot`, `ISAACSIM_ROOT`, fallback | `C:\isaacsim` |
| Isaac Lab | `-IsaacLabRoot`, `ISAACLAB_ROOT`, fallback | `D:\IsaacLab` |
| Extension socket port | `ISAAC_MCP_PORT`, fallback | `8766` |
| Documentation MCP stack | `OMNIVERSE_AGENT_STACK_ROOT`, optional | none |

Use `scripts\check-environment.ps1 -AsJson` when another agent needs structured evidence.

Set `ISAACSIM_MCP_REPO` on machines where the skill is installed globally and the repository uses a different location.

On the maintained Windows research machine, `D:\Dev\IsaacSim-MCP` is the canonical GitHub checkout. The similarly named `D:\Dev\isaacsim-mcp-server` is an older port and must not be selected when the canonical checkout exists.

## Python/runtime rule

Normal system Python does not provide the complete Kit runtime. Run Isaac-bound scripts with:

```powershell
& "$env:ISAACSIM_ROOT\python.bat" <script.py>
```

When `ISAACSIM_ROOT` is unset and the default installation is used:

```powershell
& 'C:\isaacsim\python.bat' <script.py>
```

Some `omni.*` modules require `SimulationApp` or a Kit application to initialize before import. A successful static import does not prove the live stage or extensions are ready.

## Repository launchers

Run these from the repository root:

```powershell
& '.\scripts\run_isaac_sim.ps1'
& '.\scripts\run_mcp_server.ps1'
```

Keep Isaac Sim visible when the user needs its GUI. Use `Start-Process -WindowStyle Hidden` only for non-interactive background helpers.

## Install the skill on another machine

Cloning this repository makes the project-scoped skill available under `.agents\skills`. To install a reusable user-scoped copy:

```powershell
& '.\.agents\skills\omniverse-windows-workspace\scripts\install-skill.ps1'
```

The installer refuses to overwrite an existing copy unless `-Force` is supplied. It never copies credentials.
