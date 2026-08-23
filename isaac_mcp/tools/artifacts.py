"""Managed artifact MCP tools."""

import json
from typing import TYPE_CHECKING, Callable

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    @mcp.tool("get_artifact_info")
    def get_artifact_info(handle: str) -> str:
        """Get size, type, hash, expiry, and producer metadata for a managed artifact."""
        return json.dumps(get_connection().send_command("artifacts.info", {"handle": handle}), indent=2)

    @mcp.tool("read_artifact")
    def read_artifact(handle: str, offset: int = 0, length: int = 256 * 1024) -> str:
        """Read one bounded base64 chunk from a managed artifact."""
        params = {"handle": handle, "offset": offset, "length": length}
        return json.dumps(get_connection().send_command("artifacts.read", params), indent=2)

    @mcp.tool("delete_artifact")
    def delete_artifact(handle: str) -> str:
        """Delete one managed artifact after validating its opaque handle."""
        return json.dumps(get_connection().send_command("artifacts.delete", {"handle": handle}), indent=2)

    @mcp.tool("cleanup_artifacts")
    def cleanup_artifacts() -> str:
        """Delete expired managed artifacts and report reclaimed capacity."""
        return json.dumps(get_connection().send_command("artifacts.cleanup", {}), indent=2)
