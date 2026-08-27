"""Transport selection and HTTP security contracts for the MCP server."""

import asyncio
from unittest.mock import MagicMock

import pytest
from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request

from isaac_mcp import server


def _host_validation_status(settings, host, origin=None):
    headers = [(b"host", host.encode("ascii"))]
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/mcp",
            "headers": headers,
        }
    )
    response = asyncio.run(TransportSecurityMiddleware(settings).validate_request(request))
    return None if response is None else response.status_code


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000", "[::1]", "[::1]:8000"],
)
def test_default_http_hosts_are_allowed(monkeypatch, host):
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)

    settings = server._transport_security_settings()

    assert settings.enable_dns_rebinding_protection is True
    assert _host_validation_status(settings, host) is None


def test_default_local_http_origin_is_allowed(monkeypatch):
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)

    settings = server._transport_security_settings()

    assert _host_validation_status(settings, "localhost:8000", "http://localhost:8000") is None


def test_configured_external_http_host_is_allowed(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "your-device.your-tailnet.ts.net")

    settings = server._transport_security_settings()

    assert _host_validation_status(settings, "your-device.your-tailnet.ts.net") is None
    assert _host_validation_status(settings, "your-device.your-tailnet.ts.net:443") is None


def test_unconfigured_external_http_host_is_rejected(monkeypatch):
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)

    settings = server._transport_security_settings()

    assert _host_validation_status(settings, "untrusted.example.com") == 421


@pytest.mark.parametrize("allowed_hosts", ["*", "*.ts.net", ".ts.net", "localhost,*.ts.net"])
def test_http_host_wildcards_are_rejected(monkeypatch, allowed_hosts):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", allowed_hosts)

    with pytest.raises(ValueError, match="exact host values"):
        server._transport_security_settings()


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
        transport_security=server._transport_security_settings(),
    )
