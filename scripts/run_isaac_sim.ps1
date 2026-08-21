# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

[CmdletBinding()]
param(
    [string]$IsaacSimRoot = $env:ISAACSIM_ROOT,
    [int]$Port = $(if ($env:ISAAC_MCP_PORT) { [int]$env:ISAAC_MCP_PORT } else { 8766 }),
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$IsaacArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$extensionManifest = Join-Path $repoRoot "isaac.sim.mcp_extension\config\extension.toml"
$extensionId = "isaac.sim.mcp_extension"

if (-not (Test-Path -LiteralPath $extensionManifest)) {
    throw "Extension manifest not found: $extensionManifest"
}

if (-not $IsaacSimRoot) {
    $candidates = @(
        "C:\isaacsim"
    )
    $IsaacSimRoot = $candidates | Where-Object {
        (Test-Path -LiteralPath (Join-Path $_ "isaac-sim.bat")) -or
        (Test-Path -LiteralPath (Join-Path $_ "Scripts\isaacsim.exe"))
    } | Select-Object -First 1
}

if (-not $IsaacSimRoot -or -not (Test-Path -LiteralPath $IsaacSimRoot)) {
    throw "Isaac Sim 6.0.1 was not found. Set ISAACSIM_ROOT to its install or Python environment root."
}

$IsaacSimRoot = (Resolve-Path -LiteralPath $IsaacSimRoot).Path
$batchLauncher = Join-Path $IsaacSimRoot "isaac-sim.bat"
$pipLauncher = Join-Path $IsaacSimRoot "Scripts\isaacsim.exe"
$versionFile = Join-Path $IsaacSimRoot "VERSION"
$pipAppFile = Join-Path $IsaacSimRoot "Lib\site-packages\isaacsim\apps\isaacsim.exp.full.kit"
$version = $null

if (Test-Path -LiteralPath $versionFile) {
    $version = (Get-Content -LiteralPath $versionFile -TotalCount 1).Trim()
}
elseif (Test-Path -LiteralPath $pipAppFile) {
    $versionLine = Select-String -LiteralPath $pipAppFile -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($versionLine) {
        $version = $versionLine.Matches[0].Groups[1].Value
    }
}

if (-not $version -or $version -notmatch '^6\.0\.1(?:\.|-|$)') {
    $displayVersion = if ($version) { $version } else { "unknown" }
    throw "Isaac Sim 6.0.1 is required for this Windows port baseline; found $displayVersion at $IsaacSimRoot."
}

$launcher = if (Test-Path -LiteralPath $batchLauncher) {
    $batchLauncher
}
elseif (Test-Path -LiteralPath $pipLauncher) {
    $pipLauncher
}
else {
    throw "Isaac Sim launcher not found under: $IsaacSimRoot"
}

Write-Host "Isaac Sim: $version"
Write-Host "Launcher: $launcher"
Write-Host "Extension: $extensionId"
Write-Host "TCP port: $Port"

& $launcher `
    --ext-folder $repoRoot `
    --enable $extensionId `
    "--/exts/isaac.sim.mcp/server.port=$Port" `
    @IsaacArgs
exit $LASTEXITCODE
