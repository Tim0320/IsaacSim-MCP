"""Transport selection contracts for the MCP server entry point."""

from unittest.mock import MagicMock

import pytest

from isaac_mcp import server


@pytest.mark.parametrize("transport", [None, "stdio"])
def test_main_uses_stdio_by_default(monkeypatch, transport):
    if transport is None:
        monkeypatch.delenv("ISAAC_MCP_TRANSPORT", raising=False)
    else:
        monkeypatch.setenv("ISAAC_MCP_TRANSPORT", transport)

    run = MagicMock()
    monkeypatch.setattr(server.mcp, "run", run)

    server.main()

    run.assert_called_once_with()


@pytest.mark.parametrize("transport", ["http", "streamable-http"])
def test_main_normalizes_http_transports(monkeypatch, transport):
    monkeypatch.setenv("ISAAC_MCP_TRANSPORT", transport)
    run = MagicMock()
    monkeypatch.setattr(server.mcp, "run", run)

    server.main()

    run.assert_called_once_with(transport="streamable-http")


def test_main_rejects_unknown_transport(monkeypatch):
    monkeypatch.setenv("ISAAC_MCP_TRANSPORT", "websocket")
    run = MagicMock()
    monkeypatch.setattr(server.mcp, "run", run)

    with pytest.raises(ValueError, match="Unsupported ISAAC_MCP_TRANSPORT"):
        server.main()

    run.assert_not_called()


@pytest.mark.parametrize(
    ("host", "port", "expected_host", "expected_port"),
    [
        (None, None, "127.0.0.1", 8000),
        ("0.0.0.0", "8123", "0.0.0.0", 8123),
    ],
)
def test_create_mcp_uses_http_environment_settings(
    monkeypatch,
    host,
    port,
    expected_host,
    expected_port,
):
    if host is None:
        monkeypatch.delenv("ISAAC_MCP_HTTP_HOST", raising=False)
    else:
        monkeypatch.setenv("ISAAC_MCP_HTTP_HOST", host)
    if port is None:
        monkeypatch.delenv("ISAAC_MCP_HTTP_PORT", raising=False)
    else:
        monkeypatch.setenv("ISAAC_MCP_HTTP_PORT", port)

    fast_mcp = MagicMock()
    monkeypatch.setattr(server, "FastMCP", fast_mcp)

    server._create_mcp()

    fast_mcp.assert_called_once_with(
        "IsaacSimMCP",
        instructions=server._INSTRUCTIONS,
        lifespan=server.server_lifespan,
        host=expected_host,
        port=expected_port,
        streamable_http_path="/mcp",
    )
