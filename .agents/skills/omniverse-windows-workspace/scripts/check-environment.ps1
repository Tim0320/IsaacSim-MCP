[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$IsaacSimRoot,
    [string]$IsaacLabRoot,
    [switch]$AsJson
)

$ErrorActionPreference = 'Continue'

function Get-VersionText {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return (Get-Content -LiteralPath $Path -TotalCount 1).Trim()
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 300)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($pending)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Find-McpRepository {
    param([string]$StartPath)
    $candidate = $StartPath
    while (-not [string]::IsNullOrWhiteSpace($candidate)) {
        $serverPath = Join-Path $candidate 'isaac_mcp\server.py'
        $projectPath = Join-Path $candidate 'pyproject.toml'
        if ((Test-Path -LiteralPath $serverPath -PathType Leaf) -and (Test-Path -LiteralPath $projectPath -PathType Leaf)) {
            return $candidate
        }
        $parent = Split-Path -Parent $candidate
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $candidate) { break }
        $candidate = $parent
    }
    return $null
}

$skillRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($env:ISAACSIM_MCP_REPO)) {
        $RepositoryRoot = $env:ISAACSIM_MCP_REPO
    }
    else {
        $RepositoryRoot = Find-McpRepository -StartPath $skillRoot
    }
}
if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    foreach ($fallbackRoot in @('D:\Dev\IsaacSim-MCP', 'D:\Dev\isaacsim-mcp-server')) {
        if (Test-Path -LiteralPath $fallbackRoot -PathType Container) {
            $RepositoryRoot = $fallbackRoot
            break
        }
    }
}
if ([string]::IsNullOrWhiteSpace($IsaacSimRoot)) {
    $IsaacSimRoot = if ([string]::IsNullOrWhiteSpace($env:ISAACSIM_ROOT)) { 'C:\isaacsim' } else { $env:ISAACSIM_ROOT }
}
if ([string]::IsNullOrWhiteSpace($IsaacLabRoot)) {
    $IsaacLabRoot = if ([string]::IsNullOrWhiteSpace($env:ISAACLAB_ROOT)) { 'D:\IsaacLab' } else { $env:ISAACLAB_ROOT }
}

$socketPort = 8766
$configuredPort = 0
if ([int]::TryParse($env:ISAAC_MCP_PORT, [ref]$configuredPort) -and $configuredPort -ge 1 -and $configuredPort -le 65535) {
    $socketPort = $configuredPort
}

$documentationPorts = @(9901, 9902, 9903, 9904)
$ports = [ordered]@{}
foreach ($port in @($socketPort) + $documentationPorts) {
    $ports[$port.ToString()] = Test-TcpPort -HostName '127.0.0.1' -Port $port
}

$stackRoot = $env:OMNIVERSE_AGENT_STACK_ROOT
$repositoryExists = -not [string]::IsNullOrWhiteSpace($RepositoryRoot) -and (Test-Path -LiteralPath $RepositoryRoot -PathType Container)
$result = [ordered]@{
    repository = [ordered]@{
        root = $RepositoryRoot
        exists = $repositoryExists
        venvPython = $repositoryExists -and (Test-Path -LiteralPath (Join-Path $RepositoryRoot '.venv\Scripts\python.exe') -PathType Leaf)
        isaacLauncher = $repositoryExists -and (Test-Path -LiteralPath (Join-Path $RepositoryRoot 'scripts\run_isaac_sim.ps1') -PathType Leaf)
        mcpLauncher = $repositoryExists -and (Test-Path -LiteralPath (Join-Path $RepositoryRoot 'scripts\run_mcp_server.ps1') -PathType Leaf)
    }
    isaacSim = [ordered]@{
        root = $IsaacSimRoot
        exists = Test-Path -LiteralPath $IsaacSimRoot -PathType Container
        version = Get-VersionText -Path (Join-Path $IsaacSimRoot 'VERSION')
        python = Test-Path -LiteralPath (Join-Path $IsaacSimRoot 'python.bat') -PathType Leaf
    }
    isaacLab = [ordered]@{
        root = $IsaacLabRoot
        exists = Test-Path -LiteralPath $IsaacLabRoot -PathType Container
        version = Get-VersionText -Path (Join-Path $IsaacLabRoot 'VERSION')
    }
    portableStack = [ordered]@{
        root = $stackRoot
        configured = -not [string]::IsNullOrWhiteSpace($stackRoot)
        exists = -not [string]::IsNullOrWhiteSpace($stackRoot) -and (Test-Path -LiteralPath $stackRoot -PathType Container)
    }
    liveSocketPort = $socketPort
    ports = $ports
    keysConfigured = [ordered]@{
        NVIDIA_API_KEY = -not [string]::IsNullOrWhiteSpace($env:NVIDIA_API_KEY)
        NGC_API_KEY = -not [string]::IsNullOrWhiteSpace($env:NGC_API_KEY)
        ARK_API_KEY = -not [string]::IsNullOrWhiteSpace($env:ARK_API_KEY)
    }
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 8
    exit 0
}

Write-Output "Repository: $($result.repository.root) exists=$($result.repository.exists) venv=$($result.repository.venvPython) launchers=$($result.repository.isaacLauncher)/$($result.repository.mcpLauncher)"
Write-Output "Isaac Sim: root=$($result.isaacSim.root) exists=$($result.isaacSim.exists) version=$($result.isaacSim.version) python.bat=$($result.isaacSim.python)"
Write-Output "Isaac Lab: root=$($result.isaacLab.root) exists=$($result.isaacLab.exists) version=$($result.isaacLab.version)"
Write-Output "Portable stack: configured=$($result.portableStack.configured) root=$($result.portableStack.root) exists=$($result.portableStack.exists)"
foreach ($entry in $result.ports.GetEnumerator()) { Write-Output "Port $($entry.Key): open=$($entry.Value)" }
Write-Output "Keys configured: NVIDIA=$($result.keysConfigured.NVIDIA_API_KEY) NGC=$($result.keysConfigured.NGC_API_KEY) ARK=$($result.keysConfigured.ARK_API_KEY)"
exit 0
