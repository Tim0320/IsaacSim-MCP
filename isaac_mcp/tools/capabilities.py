# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Runtime capability discovery MCP tool."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from mcp.server.fastmcp import FastMCP

from isaac_mcp import __version__

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    @mcp.tool("get_capabilities")
    def get_capabilities() -> str:
        """Discover the live Isaac Sim MCP runtime and its explicit limitations.

        Returns the Isaac Sim version, selected adapter, active physics backend,
        extension states, sensor warm-up policy, feature flags, and unsupported
        arguments. This query is read-only and works while the USD stage is
        still starting.
        """
        try:
            conn = get_connection()
            result = conn.send_command("system.get_capabilities")
            result["mcp_server"] = {
                "name": "isaacsim-mcp-server",
                "version": __version__,
                "transport": "stdio_to_tcp",
                "live_control_port": conn.port,
            }
            return json.dumps(result, indent=2, sort_keys=True)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}, indent=2, sort_keys=True)
