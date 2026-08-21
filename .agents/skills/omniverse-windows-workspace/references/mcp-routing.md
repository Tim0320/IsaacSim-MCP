# MCP routing

Select the route from the requested outcome.

| Route | Endpoint/process | Use for | Do not use as evidence for |
| --- | --- | --- | --- |
| NVIDIA documentation | configured streamable HTTP MCP services | `omni.ui`, Kit, OpenUSD, Isaac Sim APIs and examples | live stage changes |
| Isaac Sim live | this repository's stdio MCP plus extension TCP socket | create, query, edit, simulate, and delete stage objects | documentation service health |

The stdio MCP server communicates with the Isaac Sim extension over TCP. `ISAAC_MCP_PORT` selects the socket and defaults to `8766`.

## Live MCP client baseline

Use the repository virtual environment so the client can launch the server without activating a shell:

```json
{
  "mcpServers": {
    "isaac-sim-live": {
      "command": "<repository>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "isaac_mcp.server"],
      "env": {
        "ISAAC_MCP_PORT": "8766"
      }
    }
  }
}
```

Store machine-specific absolute paths in the MCP client's local configuration, never in this portable skill.

## Documentation MCP rule

Documentation MCP endpoints are optional and deployment-specific. Discover their configured URLs from the current workspace or client instead of assuming fixed ports. If a local `kit-usd-agents` stack uses ports `9901` through `9904`, keep its Isaac documentation service distinct from `isaac-sim-live`.

Check streamable HTTP MCP health with a JSON-RPC `initialize` request to `/mcp` and an `Accept` header containing both `application/json` and `text/event-stream`. A plain `GET /health` is not equivalent.

## Live-control fallback

If `isaac-sim-live` tools are absent:

1. Inspect the current client's MCP configuration without exposing secrets.
2. Confirm the configured Python executable and `-m isaac_mcp.server` command exist.
3. Restart or open a new client task after adding MCP configuration because tool discovery usually occurs at task startup.
4. Confirm the Isaac Sim extension socket is listening before scene operations.
5. Do not substitute documentation tools for live control.
