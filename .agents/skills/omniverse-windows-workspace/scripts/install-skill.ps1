[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$DestinationRoot,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path -Parent $PSScriptRoot
$skillName = Split-Path -Leaf $skillRoot

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        Join-Path $env:USERPROFILE '.codex\skills'
    }
    else {
        Join-Path $env:CODEX_HOME 'skills'
    }
}

$destination = Join-Path $DestinationRoot $skillName
if (Test-Path -LiteralPath $destination) {
    if (-not $Force) {
        throw "Destination already exists: $destination. Re-run with -Force to replace it."
    }
    if ($PSCmdlet.ShouldProcess($destination, 'Remove existing skill')) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
}

if ($PSCmdlet.ShouldProcess($destination, 'Install skill')) {
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    Copy-Item -LiteralPath $skillRoot -Destination $destination -Recurse
}

Write-Output "Installed $skillName to $destination"
