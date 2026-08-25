# MIT License
# Copyright (c) 2026 whats2000

[CmdletBinding()]
param(
    [switch]$AllowDirty,
    [switch]$SkipBackup,
    [switch]$SkipLive,
    [switch]$SkipPackage,
    [string]$ExpectedRemote = "https://github.com/Tim0320/IsaacSim-MCP.git",
    [string]$IsaacSimRoot = $(if ($env:ISAACSIM_ROOT) { $env:ISAACSIM_ROOT } else { "C:\isaacsim" }),
    [string]$ReportPath
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$ruff = Join-Path $repoRoot ".venv\Scripts\ruff.exe"
$startedAt = [DateTimeOffset]::UtcNow
$steps = [System.Collections.Generic.List[object]]::new()
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("isaacsim-mcp-release-" + [Guid]::NewGuid().ToString("N"))
$initialStatus = $null

function Add-StepResult {
    param([string]$Name, [string]$Status, [string]$Detail)
    $steps.Add([ordered]@{ name = $Name; status = $Status; detail = $Detail })
}

function Invoke-GateStep {
    param([string]$Name, [scriptblock]$Action)
    Write-Host "[RUN ] $Name"
    try {
        $detail = & $Action
        Add-StepResult -Name $Name -Status "pass" -Detail (($detail | Out-String).Trim())
        Write-Host "[PASS] $Name"
    }
    catch {
        Add-StepResult -Name $Name -Status "fail" -Detail $_.Exception.Message
        Write-Host "[FAIL] $Name`: $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

function Invoke-NativeChecked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function Get-WorktreeFingerprint {
    $status = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all) -join "`n"
    $bytes = [Text.Encoding]::UTF8.GetBytes($status)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-PublishFormatCandidates {
    $candidates = [System.Collections.Generic.List[string]]::new()
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    $remoteLine = (& git -C $repoRoot ls-remote origin refs/heads/main | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or -not $remoteLine) {
        throw "could not resolve origin/main for publish candidate format check"
    }
    $remoteSha = ($remoteLine -split "\s+")[0]
    if ($remoteSha -ne $head) {
        & git -C $repoRoot cat-file -e "$remoteSha`^{commit}"
        if ($LASTEXITCODE -ne 0) {
            throw "origin/main commit $remoteSha is not available locally"
        }
        @(& git -C $repoRoot diff --name-only --diff-filter=ACMR "$remoteSha...$head") |
            ForEach-Object { $candidates.Add($_) }
    }

    @(& git -C $repoRoot diff --name-only --diff-filter=ACMR) |
        ForEach-Object { $candidates.Add($_) }
    @(& git -C $repoRoot diff --cached --name-only --diff-filter=ACMR) |
        ForEach-Object { $candidates.Add($_) }
    @(& git -C $repoRoot ls-files --others --exclude-standard) |
        ForEach-Object { $candidates.Add($_) }

    return @($candidates |
        Where-Object { $_ -match '(?i)\.(py|pyi|md)$' -and (Test-Path -LiteralPath (Join-Path $repoRoot $_) -PathType Leaf) } |
        Sort-Object -Unique)
}

function Test-PublishCandidateSecrets {
    $forbiddenNames = @()
    $tracked = @(& git -C $repoRoot ls-files)
    $untracked = @(& git -C $repoRoot ls-files --others --exclude-standard)
    $candidates = @($tracked + $untracked | Sort-Object -Unique)
    foreach ($relative in $candidates) {
        $name = [IO.Path]::GetFileName($relative)
        if (($name -match '^\.env($|\.)' -and $name -ne '.env.example') -or $name -match '(?i)(credential|secret).*(json|toml|ya?ml|txt)$') {
            $forbiddenNames += $relative
        }
    }
    if ($forbiddenNames.Count -gt 0) {
        throw "credential-like publish-candidate filenames: $($forbiddenNames -join ', ')"
    }

    $secretPatterns = @(
        '(?i)nvapi-[A-Za-z0-9_-]{20,}',
        '(?i)(api[_-]?key|access[_-]?token|password|authorization)\s*[:=]\s*["''][A-Za-z0-9_./+=-]{24,}["'']'
    )
    $matches = @()
    foreach ($relative in $candidates) {
        $path = Join-Path $repoRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $extension = [IO.Path]::GetExtension($path).ToLowerInvariant()
        if ($extension -in @('.gif', '.mp4', '.png', '.usd', '.usdc', '.usdz')) { continue }
        try { $content = [IO.File]::ReadAllText($path) } catch { continue }
        foreach ($pattern in $secretPatterns) {
            if ($content -match $pattern) {
                $matches += $relative
                break
            }
        }
    }
    if ($matches.Count -gt 0) {
        throw "possible secret values found in publish candidates: $($matches -join ', ')"
    }
    return "tracked_files=$($tracked.Count); untracked_candidates=$($untracked.Count); credential_findings=0"
}

if (-not $ReportPath) {
    $ReportPath = Join-Path $repoRoot "test_outputs\release_gate_result.json"
}

Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    $initialStatus = Get-WorktreeFingerprint

    Invoke-GateStep "repository identity" {
        $top = (& git rev-parse --show-toplevel).Trim().Replace('\', '/')
        if ($top -ne $repoRoot.Replace('\', '/')) { throw "unexpected repository root: $top" }
        $remote = (& git remote get-url origin).Trim()
        if ($remote -ne $ExpectedRemote) { throw "origin mismatch: $remote" }
        $branch = (& git branch --show-current).Trim()
        $head = (& git rev-parse HEAD).Trim()
        "branch=$branch; head=$head; origin=$remote"
    }

    Invoke-GateStep "worktree policy" {
        $status = @(& git status --short)
        if ($status.Count -gt 0 -and -not $AllowDirty) {
            throw "worktree is dirty; commit/review first or use -AllowDirty for a non-release validation run"
        }
        "dirty_entries=$($status.Count); allow_dirty=$([bool]$AllowDirty)"
    }

    Invoke-GateStep "version and runtime compatibility" {
        if (-not (Test-Path -LiteralPath $python)) { throw "missing virtualenv Python: $python" }
        if (-not (Test-Path -LiteralPath $ruff)) { throw "missing ruff: $ruff" }
        $versionFile = Join-Path $IsaacSimRoot "VERSION"
        if (-not (Test-Path -LiteralPath $versionFile)) { throw "missing Isaac Sim VERSION: $versionFile" }
        $isaacVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
        if (-not $isaacVersion.StartsWith("6.0.1")) { throw "Isaac Sim 6.0.1 required, found $isaacVersion" }
        $serverVersion = & $python -c "import isaac_mcp; print(isaac_mcp.__version__)"
        if ($LASTEXITCODE -ne 0) { throw "could not read server version" }
        $manifest = Get-Content -LiteralPath "isaac.sim.mcp_extension\config\extension.toml" -Raw
        if ($manifest -notmatch 'version\s*=\s*"([^\"]+)"') { throw "extension version missing" }
        if ($serverVersion.Trim() -ne $Matches[1]) { throw "server/extension version mismatch" }
        "package=$($serverVersion.Trim()); isaac_sim=$isaacVersion; response_schema=1.0; capability_schema=1.1"
    }

    Invoke-GateStep "publish candidate secret scan" { Test-PublishCandidateSecrets }

    if (-not $SkipBackup) {
        Invoke-GateStep "verified repository backup" {
            $backup = & (Join-Path $repoRoot "scripts\backup_project.ps1") -Label "release-gate"
            if (-not $backup.RestoreValidated) { throw "backup restore validation failed" }
            "path=$($backup.BackupPath); sha256=$($backup.BundleSha256); compared=$($backup.ComparedFiles)"
        }
    }
    else { Add-StepResult -Name "verified repository backup" -Status "skipped" -Detail "-SkipBackup" }

    Invoke-GateStep "offline test pyramid" {
        Invoke-NativeChecked $python @("-m", "pytest", "-q", "-m", "not live and not windows_launcher and not unix_launcher", "-k", "not test_detect_version_returns_zero_on_failure")
        "pytest offline layers passed"
    }

    Invoke-GateStep "Windows launcher tests" {
        Invoke-NativeChecked $python @("-m", "pytest", "-q", "tests\test_run_isaac_sim_windows.py")
        "PowerShell launcher tests passed"
    }

    Invoke-GateStep "lint and diff integrity" {
        Invoke-NativeChecked $ruff @("check", ".")
        $formatCandidates = @(Get-PublishFormatCandidates)
        if ($formatCandidates.Count -gt 0) {
            Invoke-NativeChecked $ruff (@("format", "--check") + $formatCandidates)
        }
        Invoke-NativeChecked "git" @("diff", "--check")
        "ruff check, publish candidate format check ($($formatCandidates.Count) files), and git diff --check passed"
    }

    if (-not $SkipLive) {
        Invoke-GateStep "read-only Isaac Sim 6.0.1 live matrix" {
            $listener = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
            if (-not $listener) { throw "TCP 8766 is not listening" }
            $jsonLine = & $python "scripts\generate_all_tools_report.py" --live --check
            if ($LASTEXITCODE -ne 0) { throw "live matrix check failed" }
            $matrix = $jsonLine | ConvertFrom-Json
            if ($matrix.tool_count -ne 128) { throw "expected 128 tools, found $($matrix.tool_count)" }
            if ($matrix.counts.fail -and $matrix.counts.fail -ne 0) { throw "live matrix contains failures" }
            "tools=128; pass=$($matrix.counts.pass); blocked=$($matrix.counts.blocked); port_owner=$($listener[0].OwningProcess)"
        }
    }
    else { Add-StepResult -Name "read-only Isaac Sim 6.0.1 live matrix" -Status "skipped" -Detail "-SkipLive" }

    if (-not $SkipPackage) {
        Invoke-GateStep "wheel build and clean virtualenv import" {
            $dist = Join-Path $temporaryRoot "dist"
            Invoke-NativeChecked "uv" @("build", "--wheel", "--out-dir", $dist)
            $wheel = Get-ChildItem -LiteralPath $dist -Filter "*.whl" | Select-Object -First 1
            if (-not $wheel) { throw "wheel was not produced" }
            $venv = Join-Path $temporaryRoot "venv"
            Invoke-NativeChecked $python @("-m", "venv", $venv)
            $freshPython = Join-Path $venv "Scripts\python.exe"
            Invoke-NativeChecked $freshPython @("-m", "pip", "install", "--no-deps", $wheel.FullName)
            $installedVersion = & $freshPython -c "import isaac_mcp; print(isaac_mcp.__version__)"
            if ($LASTEXITCODE -ne 0 -or $installedVersion.Trim() -ne "0.6.0") { throw "fresh wheel import/version failed" }
            "wheel=$($wheel.Name); installed_version=$($installedVersion.Trim())"
        }
    }
    else { Add-StepResult -Name "wheel build and clean virtualenv import" -Status "skipped" -Detail "-SkipPackage" }

    Invoke-GateStep "worktree preservation and Git review" {
        $finalStatus = Get-WorktreeFingerprint
        if ($finalStatus -ne $initialStatus) { throw "release gate changed the worktree" }
        $entries = @(& git status --short)
        "worktree_fingerprint_unchanged=true; review_entries=$($entries.Count); no push/merge/tag performed"
    }
}
catch {
    $gateError = $_.Exception.Message
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
    $report = [ordered]@{
        schema_version = "1.0"
        started_at = $startedAt.ToString("o")
        finished_at = [DateTimeOffset]::UtcNow.ToString("o")
        repository = $repoRoot
        expected_remote = $ExpectedRemote
        allow_dirty = [bool]$AllowDirty
        result = $(if ($gateError) { "fail" } else { "pass" })
        error = $gateError
        steps = $steps
    }
    $reportDirectory = Split-Path -Parent $ReportPath
    if ($reportDirectory) { New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
    Write-Host "Release gate report: $ReportPath"
}

if ($gateError) { throw $gateError }
