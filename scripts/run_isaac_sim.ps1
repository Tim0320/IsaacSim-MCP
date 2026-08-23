# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

[CmdletBinding()]
param(
    [string]$IsaacSimRoot = $env:ISAACSIM_ROOT,
    [int]$Port = $(if ($env:ISAAC_MCP_PORT) { [int]$env:ISAAC_MCP_PORT } else { 8766 }),
    [string]$PhysicsGpu,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$IsaacArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$extensionManifest = Join-Path $repoRoot "isaac.sim.mcp_extension\config\extension.toml"
$extensionId = "isaac.sim.mcp_extension"

function ConvertTo-PhysicsGpuOrdinal {
    param(
        [AllowEmptyString()]
        [string]$Value,
        [string]$Source
    )

    $ordinal = 0
    if (-not [int]::TryParse($Value, [ref]$ordinal) -or $ordinal -lt -1) {
        throw "Invalid physics GPU '$Value' from $Source. Use an integer ordinal >= 0, or -1 for Isaac Sim auto-selection."
    }
    return $ordinal
}

# IMPORTANT ISAAC SIM 6.0.1 CRASH GUARD:
# On multi-GPU systems, leaving /physics/cudaDevice at -1 can move PhysX between
# CUDA contexts and crash in PhysXGpu_64.dll when Timeline Stop is processed.
# Resolve the current primary display GPU to an explicit ordinal every launch.
# Do not remove this as a redundant default; -1 remains opt-in and is warned.
$filteredIsaacArgs = [System.Collections.Generic.List[string]]::new()
$rawPhysicsGpu = $null
foreach ($argument in @($IsaacArgs)) {
    if ($argument -match '^--/physics/cudaDevice=(.*)$') {
        $rawPhysicsGpu = $Matches[1]
        continue
    }
    $filteredIsaacArgs.Add($argument)
}

$physicsGpuSource = $null
if ($null -ne $rawPhysicsGpu) {
    $effectivePhysicsGpu = ConvertTo-PhysicsGpuOrdinal $rawPhysicsGpu "raw Kit argument"
    $physicsGpuSource = "raw Kit argument"
}
elseif ($PSBoundParameters.ContainsKey("PhysicsGpu")) {
    $effectivePhysicsGpu = ConvertTo-PhysicsGpuOrdinal $PhysicsGpu "-PhysicsGpu"
    $physicsGpuSource = "-PhysicsGpu"
}
elseif (-not [string]::IsNullOrWhiteSpace($env:ISAAC_PHYSICS_GPU)) {
    $effectivePhysicsGpu = ConvertTo-PhysicsGpuOrdinal $env:ISAAC_PHYSICS_GPU "ISAAC_PHYSICS_GPU"
    $physicsGpuSource = "ISAAC_PHYSICS_GPU"
}
else {
    $activeDisplayGpuOrdinals = @()
    $nvidiaSmi = Get-Command "nvidia-smi" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($nvidiaSmi) {
        try {
            $gpuRows = @(& $nvidiaSmi.Source --query-gpu=index,display_active --format=csv,noheader,nounits 2>$null)
            $gpuProbeSucceeded = $LASTEXITCODE -eq 0
        }
        catch {
            $gpuRows = @()
            $gpuProbeSucceeded = $false
        }
        if ($gpuProbeSucceeded) {
            foreach ($row in $gpuRows) {
                $columns = "$row".Split(",")
                if ($columns.Count -ge 2 -and $columns[1].Trim() -ieq "Enabled") {
                    $ordinal = 0
                    if ([int]::TryParse($columns[0].Trim(), [ref]$ordinal) -and $ordinal -ge 0) {
                        $activeDisplayGpuOrdinals += $ordinal
                    }
                }
            }
        }
    }

    if ($activeDisplayGpuOrdinals.Count -eq 1) {
        $effectivePhysicsGpu = $activeDisplayGpuOrdinals[0]
        $physicsGpuSource = "active display GPU"
    }
    else {
        $effectivePhysicsGpu = 0
        $physicsGpuSource = "safe fallback"
        Write-Warning "Could not identify exactly one active display GPU; using explicit GPU 0. Override with -PhysicsGpu or ISAAC_PHYSICS_GPU."
    }
}

if ($effectivePhysicsGpu -eq -1) {
    Write-Warning "Isaac Sim 6.0.1 multi-GPU risk: /physics/cudaDevice=-1 can crash in PhysXGpu_64.dll during Timeline Stop. Prefer a fixed GPU ordinal."
}

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
Write-Host "Physics CUDA device: $effectivePhysicsGpu ($physicsGpuSource)"

& $launcher `
    --ext-folder $repoRoot `
    --enable $extensionId `
    "--/exts/isaac.sim.mcp/server.port=$Port" `
    "--/physics/cudaDevice=$effectivePhysicsGpu" `
    @filteredIsaacArgs
exit $LASTEXITCODE
