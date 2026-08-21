# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

[CmdletBinding()]
param(
    [int]$Port = $(if ($env:ISAAC_MCP_PORT) { [int]$env:ISAAC_MCP_PORT } else { 8766 }),
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ServerArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$installedCli = Join-Path $repoRoot ".venv\Scripts\isaacsim-mcp-server.exe"

$env:ISAAC_MCP_PORT = $Port.ToString()

if (Test-Path -LiteralPath $installedCli) {
    & $installedCli @ServerArgs
    exit $LASTEXITCODE
}

if (Test-Path -LiteralPath $python) {
    Push-Location $repoRoot
    try {
        & $python -m isaac_mcp.server @ServerArgs
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

throw "isaacsim-mcp-server was not found. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ."
