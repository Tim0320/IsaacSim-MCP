# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Runtime capability discovery MCP tool."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from mcp.server.fastmcp import FastMCP

from isaac_mcp import __version__
from isaac_mcp.runtime_status import IsaacRuntimeUnavailableError
from isaac_mcp.runtime_status import get_runtime_status as read_runtime_status
from isaac_mcp.tool_inventory import tool_count
from isaac_mcp.tool_profiles import CONSOLIDATED_REPLACEMENTS, VALID_TOOL_PROFILES

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    @mcp.tool("get_capabilities")
    def get_capabilities() -> str:
        """Discover the live Isaac Sim MCP runtime and its explicit limitations.

        Returns the Isaac Sim version, selected adapter, active physics backend,
        adapter-owned PhysX/Newton matrix, extension states, sensor warm-up
        policy, feature flags, and unsupported arguments. This query is
        read-only and works while the USD stage is still starting.
        """
        try:
            conn = get_connection()
            result = conn.send_command("system.get_capabilities")
            tool_profile = str(getattr(mcp, "tool_profile", "legacy"))
            result.setdefault("data", {})["mcp_server"] = {
                "name": "isaacsim-mcp-server",
                "version": __version__,
                "transport": "stdio_to_tcp",
                "live_control_port": conn.port,
                "tool_profile": tool_profile,
                "public_tool_count": tool_count(tool_profile),
                "available_tool_profiles": sorted(VALID_TOOL_PROFILES),
                "consolidated_replacements": CONSOLIDATED_REPLACEMENTS if tool_profile == "consolidated" else {},
            }
            return json.dumps(result, indent=2, sort_keys=True)
        except IsaacRuntimeUnavailableError as exc:
            return json.dumps(exc.to_response(), indent=2, sort_keys=True)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}, indent=2, sort_keys=True)

    @mcp.tool("get_runtime_status")
    def get_runtime_status() -> str:
        """Read supervisor, crash, restart, and protocol-health state without requiring Isaac Sim.

        This local diagnostic remains available when the extension socket is
        closed. It never starts, stops, or mutates Isaac Sim and never replays a
        failed command.
        """
        runtime = read_runtime_status()
        return json.dumps(
            {
                "status": "success",
                "code": "RUNTIME_STATUS_READ",
                "message": "Read Isaac Sim runtime supervisor status",
                "data": {"runtime": runtime},
            },
            indent=2,
            sort_keys=True,
        )
