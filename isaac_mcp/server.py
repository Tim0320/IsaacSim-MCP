# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Isaac Sim MCP Server — entry point.

Registers all tools from tools/ submodules and starts the FastMCP server.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from isaac_mcp.connection import get_isaac_connection, reset_isaac_connection
from isaac_mcp.tool_profiles import resolve_tool_profile
from isaac_mcp.tools import register_all_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("IsaacMCPServer")


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle."""
    try:
        logger.info("IsaacMCP server starting up")
        try:
            get_isaac_connection()
            logger.info("Successfully connected to Isaac on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Isaac on startup: {e}")
        yield {}
    finally:
        reset_isaac_connection()
        logger.info("IsaacMCP server shut down")


_INSTRUCTIONS = """\
Isaac Sim integration through the Model Context Protocol.

## MCP Tools vs Scripts / Action Graphs

MCP tools operate BETWEEN frames (editor-level): scene setup, inspection, stepping, joint control, diagnostics.
Scripts/Action Graphs operate WITHIN frames (runtime-level): control loops, IK, state machines.

## Workflow

### Scene Setup
1. get_scene_info → 2. create_physics_scene → 3. create_robot / create_object → 4. get_prim_info (verify sizes)
- create_robot: call list_available_robots first for exact keys (lowercase, no spaces, e.g. "frankafr3")
- Always get_prim_info to query actual positions/sizes BEFORE writing controller scripts

### Debug Loop (step-only — never play)
The debug loop is step-only: set_joint_positions + step_simulation with
observe_prims/observe_joints on a FROZEN timeline. Do NOT call play_simulation
while debugging — step errors if the timeline is already playing. If issues:
get_joint_config, get_physics_state, get_isaac_logs.
play_simulation is ONLY for a final continuous run / ScriptNode demo.
Two separate debug modes: MCP loop = step on a frozen timeline (no graph);
ScriptNode/Action-Graph = play + get_isaac_logs (graphs tick only while playing
and cannot be stepped). Do not mix them.

### Controller Development
Write .py file → reload_script → step_simulation to debug → edit & reload →
play_simulation only for the final continuous run.

### ScriptNode (Action Graph)
create_action_graph(script_file="/path/to/controller.py") wires OnPlaybackTick → ScriptNode.

**ScriptNode rules:**
1. MUST define setup(db) and compute(db) — never use legacy mode (no compute = broken exec scoping)
2. Use module-level globals + `global` keyword in compute() for persistent state
3. Subscribe to timeline STOP event to reset state (or Stop→Play leaves stale objects)
4. WARMUP pattern: skip ~30 frames in compute() before calling World.initialize_physics() + robot.initialize()
5. ScriptNode fires once during create_action_graph — objects created then go stale at Play

See demo/franka_pick_place.py for a complete working example.

### Tool Priority
Prefer named tools over execute_script: spawn_human, list_nvidia_assets,
spawn_nvidia_asset, get_joint_positions, get_prim_info, get_physics_state,
get_joint_config, get_isaac_logs, create_action_graph, edit_action_graph.
spawn_human uses NVIDIA IRA 1.x on Isaac Sim 6.0+, preserves the current stage,
and requires a baked NavMesh. Its explicit auto_create_navmesh_volume option can
author the include volume; use reload_script for reusable human interaction logic.

### Contracts (silent-failure map)
- step_simulation is authoritative and freezes the timeline; it errors if the
  timeline is already playing. Never play during the debug loop (see Debug Loop).
- stop_simulation resets the scene to spawn state (state at first Play).
- get_isaac_logs shows carb.log_*/omni.log WARN+ERROR plus captured stdout
  tagged [PRINT]; plain print() outside execute_script/reload_script may not
  appear. Defaults are non-destructive and scoped to the current run.
- execute_script can silently disturb a live Action Graph / ScriptNode that
  controls the same articulation — stop the graph first.
- ScriptNode physics contract: physics must be initialised before articulation
  writes take effect; such write failures are SILENT (not raised). Follow the
  WARMUP pattern (skip ~30 frames, then World.initialize_physics() +
  robot.initialize()).
"""

_CONSOLIDATED_INSTRUCTIONS = """

## Consolidated tool profile

This server exposes conversation-oriented merged tools. Use action selectors:
query_prim, semantic_labels, typed_attribute, physics_body_config,
collision_group, physics_joint, control_timeline, robot_library,
control_gripper, control_mobile_base_velocity, motion_job,
capture_camera_output, material_definition, material_binding, light_config,
query_human, set_human_action, create_ros2_publisher, sdg_job_control,
job_control, query_action_graph, action_graph_connection, and
script_node_source. get_joint_state and set_joint_command remain canonical.
Do not call the replaced legacy names because they are intentionally hidden.
"""


_LOCAL_HTTP_HOSTS = (
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "[::1]",
    "[::1]:*",
)
_LOCAL_HTTP_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)


def _transport_security_settings() -> TransportSecuritySettings:
    """Build FastMCP DNS-rebinding protection settings from exact host values."""
    allowed_hosts = list(_LOCAL_HTTP_HOSTS)
    configured_hosts = os.getenv("MCP_ALLOWED_HOSTS", "")

    for value in configured_hosts.split(","):
        host = value.strip()
        if not host:
            continue
        if "*" in host or host.startswith(".") or "://" in host or "/" in host:
            raise ValueError(
                "MCP_ALLOWED_HOSTS must contain comma-separated exact host values without schemes, paths, or wildcards"
            )

        allowed_hosts.append(host)
        if ":" not in host or (host.startswith("[") and host.endswith("]")):
            allowed_hosts.append(f"{host}:*")

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=list(_LOCAL_HTTP_ORIGINS),
    )


def _create_mcp() -> FastMCP:
    """Create the MCP server with Streamable HTTP settings from the environment."""
    profile = resolve_tool_profile()
    return FastMCP(
        "IsaacSimMCP",
        instructions=_INSTRUCTIONS + (_CONSOLIDATED_INSTRUCTIONS if profile == "consolidated" else ""),
        lifespan=server_lifespan,
        host=os.getenv("ISAAC_MCP_HTTP_HOST", "127.0.0.1"),
        port=int(os.getenv("ISAAC_MCP_HTTP_PORT", "8000")),
        streamable_http_path="/mcp",
        transport_security=_transport_security_settings(),
    )


mcp = _create_mcp()

register_all_tools(mcp, get_isaac_connection)


def main():
    transport = os.getenv("ISAAC_MCP_TRANSPORT", "stdio").strip().lower()
    profile = resolve_tool_profile()

    if transport == "stdio":
        logger.info("Starting MCP using stdio transport with %s tool profile", profile)
        mcp.run()
    elif transport in {"http", "streamable-http"}:
        logger.info(
            "Starting MCP using Streamable HTTP at http://%s:%s%s with %s tool profile",
            mcp.settings.host,
            mcp.settings.port,
            mcp.settings.streamable_http_path,
            profile,
        )
        mcp.run(transport="streamable-http")
    else:
        raise ValueError(
            f"Unsupported ISAAC_MCP_TRANSPORT: {transport!r}; expected 'stdio', 'http', or 'streamable-http'"
        )


if __name__ == "__main__":
    main()
