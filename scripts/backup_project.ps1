# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

<#
.SYNOPSIS
Creates and verifies a recoverable Git project backup without changing the repository.

.DESCRIPTION
The backup contains a complete Git bundle, staged and unstaged binary patches,
an allowlisted snapshot of untracked files, current Git LFS working files, file
hashes, and machine-readable/human-readable manifests. Credential-like files,
cache/build directories, and oversized untracked files are never copied.

The script clones the bundle into a new temporary directory, reapplies the dirty
snapshot, and compares every included working-tree file by SHA-256. Any failure
marks the backup as failed and exits with an error.
#>

[CmdletBinding()]
param(
    [string]$RepositoryPath,
    [string]$BackupRoot = "E:\碩士論文\backups\isaacsim-mcp",
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    [string]$Label = "manual",
    [ValidateRange(1, [long]::MaxValue)]
    [long]$MaxUntrackedFileBytes = 104857600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$gitExecutable = (Get-Command git -ErrorAction Stop).Source

function Write-Utf8File {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [AllowEmptyString()] [string]$Content = ""
    )

    [System.IO.File]::WriteAllText($Path, $Content, $script:utf8NoBom)
}

function Redact-SensitiveText {
    param([AllowEmptyString()] [string]$Text = "")

    $redacted = $Text
    $redacted = [regex]::Replace(
        $redacted,
        "(?i)(https?://)[^/@\s]+@",
        '$1***@'
    )
    $redacted = [regex]::Replace(
        $redacted,
        "(?i)(ghp_|github_pat_|glpat-|AKIA)[A-Za-z0-9_-]+",
        '$1[REDACTED]'
    )
    return $redacted
}

function Invoke-Git {
    param(
        [Parameter(Mandatory)] [string]$WorkingDirectory,
        [Parameter(Mandatory)] [string[]]$GitArguments,
        [switch]$AllowFailure
    )

    $safeDirectory = ([System.IO.Path]::GetFullPath($WorkingDirectory)).Replace("\", "/")
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $script:gitExecutable
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    foreach ($argument in @("-c", "safe.directory=$safeDirectory", "-C", $WorkingDirectory) + $GitArguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    $process.Dispose()

    $result = [pscustomobject]@{
        ExitCode = $exitCode
        StdOut  = $stdout
        StdErr  = $stderr
    }
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $displayArgs = $GitArguments -join " "
        $displayError = (Redact-SensitiveText $stderr).Trim()
        throw "git $displayArgs failed with exit code ${exitCode}: $displayError"
    }
    return $result
}

function Split-NulList {
    param([AllowEmptyString()] [string]$Value = "")

    if (-not $Value) {
        return @()
    }
    return @($Value.Split([char]0, [System.StringSplitOptions]::RemoveEmptyEntries))
}

function Test-PathInside {
    param(
        [Parameter(Mandatory)] [string]$Candidate,
        [Parameter(Mandatory)] [string]$Parent
    )

    $candidateFull = [System.IO.Path]::GetFullPath($Candidate).TrimEnd("\", "/")
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd("\", "/")
    return $candidateFull.Equals($parentFull, [System.StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith(
            $parentFull + [System.IO.Path]::DirectorySeparatorChar,
            [System.StringComparison]::OrdinalIgnoreCase
        )
}

function Get-UntrackedExclusionReason {
    param(
        [Parameter(Mandatory)] [string]$RelativePath,
        [Parameter(Mandatory)] [long]$Length,
        [Parameter(Mandatory)] [long]$MaximumBytes
    )

    $normalized = $RelativePath.Replace("\", "/")
    $lower = $normalized.ToLowerInvariant()
    $segments = $lower.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries)
    $excludedDirectories = @(
        ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
        ".ruff_cache", ".mypy_cache", "node_modules", "build", "dist",
        "logs", "log", "test_outputs", "results", "local_cache", "mcp_cache"
    )
    foreach ($segment in $segments) {
        if ($excludedDirectories -contains $segment) {
            return "excluded_directory:$segment"
        }
    }

    $name = [System.IO.Path]::GetFileName($lower)
    $extension = [System.IO.Path]::GetExtension($lower)
    $secretNames = @(
        ".npmrc", ".pypirc", ".netrc", "credentials.json", "secrets.json",
        "id_rsa", "id_ed25519", ".mcp.json"
    )
    if (($name -eq ".env") -or ($name.StartsWith(".env.") -and $name -ne ".env.example")) {
        return "credential_like_name"
    }
    if ($secretNames -contains $name) {
        return "credential_like_name"
    }
    if ($name -like "mcp-inspector*.json") {
        return "credential_like_name"
    }
    if (@(".pem", ".key", ".pfx", ".p12", ".jks", ".keystore") -contains $extension) {
        return "credential_like_extension:$extension"
    }
    if ($Length -gt $MaximumBytes) {
        return "oversized:${Length}>${MaximumBytes}"
    }
    return $null
}

function Copy-RelativeFile {
    param(
        [Parameter(Mandatory)] [string]$SourceRoot,
        [Parameter(Mandatory)] [string]$DestinationRoot,
        [Parameter(Mandatory)] [string]$RelativePath
    )

    $nativeRelativePath = $RelativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
    $source = Join-Path $SourceRoot $nativeRelativePath
    $destination = Join-Path $DestinationRoot $nativeRelativePath
    $destinationParent = Split-Path -Parent $destination
    if (-not (Test-Path -LiteralPath $destinationParent)) {
        [void](New-Item -ItemType Directory -Path $destinationParent -Force)
    }
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

function Get-FileState {
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [string[]]$RelativePaths
    )

    $states = [System.Collections.Generic.List[object]]::new()
    foreach ($relativePath in @($RelativePaths | Sort-Object -Unique)) {
        $nativeRelativePath = $relativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
        $absolutePath = Join-Path $Root $nativeRelativePath
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            $states.Add([pscustomobject]@{
                    path   = $relativePath
                    exists = $false
                    bytes  = 0
                    sha256 = $null
                })
            continue
        }
        $item = Get-Item -LiteralPath $absolutePath
        $states.Add([pscustomobject]@{
                path   = $relativePath
                exists = $true
                bytes  = $item.Length
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $absolutePath).Hash
            })
    }
    return @($states)
}

function Compare-FileState {
    param(
        [Parameter(Mandatory)] [object[]]$Expected,
        [Parameter(Mandatory)] [object[]]$Actual
    )

    if ($Expected.Count -ne $Actual.Count) {
        throw "Restore validation file count mismatch: expected $($Expected.Count), actual $($Actual.Count)."
    }
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        $left = $Expected[$index]
        $right = $Actual[$index]
        if ($left.path -cne $right.path -or $left.exists -ne $right.exists -or
            $left.bytes -ne $right.bytes -or $left.sha256 -cne $right.sha256) {
            throw "Restore validation mismatch at '$($left.path)'."
        }
    }
}

function Get-FileStateMismatches {
    param(
        [Parameter(Mandatory)] [object[]]$Expected,
        [Parameter(Mandatory)] [object[]]$Actual
    )

    if ($Expected.Count -ne $Actual.Count) {
        throw "Restore validation file count mismatch: expected $($Expected.Count), actual $($Actual.Count)."
    }
    $mismatches = [System.Collections.Generic.List[string]]::new()
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        $left = $Expected[$index]
        $right = $Actual[$index]
        if ($left.path -cne $right.path -or $left.exists -ne $right.exists -or
            $left.bytes -ne $right.bytes -or $left.sha256 -cne $right.sha256) {
            $mismatches.Add($left.path)
        }
    }
    return @($mismatches)
}

if (-not $RepositoryPath) {
    $RepositoryPath = Join-Path $PSScriptRoot ".."
}
if (-not (Test-Path -LiteralPath $RepositoryPath -PathType Container)) {
    throw "Repository path not found: $RepositoryPath"
}

$repositoryProbe = Invoke-Git -WorkingDirectory $RepositoryPath -GitArguments @("rev-parse", "--show-toplevel")
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryProbe.StdOut.Trim())
$backupRootFull = [System.IO.Path]::GetFullPath($BackupRoot)
if (Test-PathInside -Candidate $backupRootFull -Parent $repositoryRoot) {
    throw "BackupRoot must be outside the repository: $backupRootFull"
}
[void](New-Item -ItemType Directory -Path $backupRootFull -Force)

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$backupDirectory = Join-Path $backupRootFull "$timestamp-$Label"
if (Test-Path -LiteralPath $backupDirectory) {
    throw "Refusing to overwrite existing backup: $backupDirectory"
}
[void](New-Item -ItemType Directory -Path $backupDirectory)

$bundlePath = Join-Path $backupDirectory "isaacsim-mcp-all.bundle"
$stagedPatchPath = Join-Path $backupDirectory "staged.patch"
$unstagedPatchPath = Join-Path $backupDirectory "unstaged.patch"
$untrackedSnapshotRoot = Join-Path $backupDirectory "untracked"
$lfsSnapshotRoot = Join-Path $backupDirectory "tracked-lfs"
$trackedOverrideRoot = Join-Path $backupDirectory "tracked-overrides"
$hashesPath = Join-Path $backupDirectory "file_hashes.json"
$manifestJsonPath = Join-Path $backupDirectory "manifest.json"
$manifestMarkdownPath = Join-Path $backupDirectory "BACKUP_MANIFEST.md"
$failurePath = Join-Path $backupDirectory "BACKUP_FAILED.txt"
$validationRoot = $null

try {
    $head = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("rev-parse", "HEAD")).StdOut.Trim()
    $branch = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("branch", "--show-current")).StdOut.Trim()
    if (-not $branch) {
        $branch = "(detached)"
    }
    $status = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
            "status", "--porcelain=v1", "--untracked-files=all"
        )).StdOut.TrimEnd()
    $remoteText = Redact-SensitiveText (
        Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("remote", "-v")
    ).StdOut.TrimEnd()
    $submoduleText = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
            "submodule", "status", "--recursive"
        )).StdOut.TrimEnd()
    if ($submoduleText) {
        throw "Submodules are present. Refusing to create a backup that cannot prove complete submodule history restoration."
    }

    $lfsVersionResult = Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("lfs", "version") -AllowFailure
    $lfsAvailable = $lfsVersionResult.ExitCode -eq 0
    $lfsVersion = if ($lfsAvailable) { $lfsVersionResult.StdOut.Trim() } else { "unavailable" }
    $lfsStatus = ""
    $lfsFiles = @()
    if ($lfsAvailable) {
        $lfsStatus = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("lfs", "status")).StdOut.TrimEnd()
        $lfsFiles = @(
            (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("lfs", "ls-files", "-n")).StdOut -split "`r?`n" |
                Where-Object { $_ }
        )
    }

    $trackedFiles = Split-NulList (
        Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @("ls-files", "-z", "--cached")
    ).StdOut
    $untrackedFiles = Split-NulList (
        Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
            "ls-files", "-z", "--others", "--exclude-standard"
        )
    ).StdOut

    $backedUntracked = [System.Collections.Generic.List[string]]::new()
    $excludedUntracked = [System.Collections.Generic.List[object]]::new()
    foreach ($relativePath in $untrackedFiles) {
        $absolutePath = Join-Path $repositoryRoot $relativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            $excludedUntracked.Add([pscustomobject]@{ path = $relativePath; reason = "not_a_regular_file" })
            continue
        }
        $length = (Get-Item -LiteralPath $absolutePath).Length
        $reason = Get-UntrackedExclusionReason -RelativePath $relativePath -Length $length -MaximumBytes $MaxUntrackedFileBytes
        if ($reason) {
            $excludedUntracked.Add([pscustomobject]@{ path = $relativePath; reason = $reason })
            continue
        }
        Copy-RelativeFile -SourceRoot $repositoryRoot -DestinationRoot $untrackedSnapshotRoot -RelativePath $relativePath
        $backedUntracked.Add($relativePath)
    }

    foreach ($relativePath in $lfsFiles) {
        $absolutePath = Join-Path $repositoryRoot $relativePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            throw "Tracked Git LFS working file is missing: $relativePath"
        }
        Copy-RelativeFile -SourceRoot $repositoryRoot -DestinationRoot $lfsSnapshotRoot -RelativePath $relativePath
    }

    $stagedPatch = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
            "diff", "--cached", "--binary", "--full-index", "--no-ext-diff"
        )).StdOut
    $unstagedPatch = (Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
            "diff", "--binary", "--full-index", "--no-ext-diff"
        )).StdOut
    Write-Utf8File -Path $stagedPatchPath -Content $stagedPatch
    Write-Utf8File -Path $unstagedPatchPath -Content $unstagedPatch

    [void](Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
            "bundle", "create", $bundlePath, "--all"
        ))
    $bundleVerify = Invoke-Git -WorkingDirectory $repositoryRoot -GitArguments @(
        "bundle", "verify", $bundlePath
    )

    $statePaths = @($trackedFiles + $backedUntracked.ToArray() | Sort-Object -Unique)
    $expectedState = Get-FileState -Root $repositoryRoot -RelativePaths $statePaths
    Write-Utf8File -Path $hashesPath -Content ($expectedState | ConvertTo-Json -Depth 4)

    $validationRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
        "isaacsim-mcp-backup-verify-" + [guid]::NewGuid().ToString("N")
    )
    [void](New-Item -ItemType Directory -Path $validationRoot)
    $restoreRoot = Join-Path $validationRoot "restored"
    $previousLfsSkipSmudge = [Environment]::GetEnvironmentVariable("GIT_LFS_SKIP_SMUDGE", "Process")
    try {
        $env:GIT_LFS_SKIP_SMUDGE = "1"
        [void](Invoke-Git -WorkingDirectory $validationRoot -GitArguments @(
                "clone", "--quiet", $bundlePath, $restoreRoot
            ))
    }
    finally {
        if ($null -eq $previousLfsSkipSmudge) {
            Remove-Item Env:GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue
        }
        else {
            $env:GIT_LFS_SKIP_SMUDGE = $previousLfsSkipSmudge
        }
    }

    if ($stagedPatch.Length -gt 0) {
        [void](Invoke-Git -WorkingDirectory $restoreRoot -GitArguments @(
                "apply", "--index", "--binary", $stagedPatchPath
            ))
    }
    if ($unstagedPatch.Length -gt 0) {
        [void](Invoke-Git -WorkingDirectory $restoreRoot -GitArguments @(
                "apply", "--binary", $unstagedPatchPath
            ))
    }
    foreach ($relativePath in $backedUntracked) {
        Copy-RelativeFile -SourceRoot $untrackedSnapshotRoot -DestinationRoot $restoreRoot -RelativePath $relativePath
    }
    foreach ($relativePath in $lfsFiles) {
        Copy-RelativeFile -SourceRoot $lfsSnapshotRoot -DestinationRoot $restoreRoot -RelativePath $relativePath
    }

    $actualState = Get-FileState -Root $restoreRoot -RelativePaths $statePaths
    $trackedOverrides = [System.Collections.Generic.List[string]]::new()
    $initialMismatches = Get-FileStateMismatches -Expected $expectedState -Actual $actualState
    foreach ($relativePath in $initialMismatches) {
        if ($trackedFiles -notcontains $relativePath) {
            throw "Restore validation mismatch at non-tracked path '$relativePath'."
        }
        $expectedEntry = $expectedState | Where-Object { $_.path -ceq $relativePath } | Select-Object -First 1
        if (-not $expectedEntry.exists) {
            throw "Restore validation expected tracked path '$relativePath' to be absent."
        }
        # Git filters and core.autocrlf can produce checkout bytes that differ
        # from the current worktree while `git diff` remains clean. Preserve
        # only those exact-byte differences as explicit tracked overrides.
        Copy-RelativeFile -SourceRoot $repositoryRoot -DestinationRoot $trackedOverrideRoot -RelativePath $relativePath
        Copy-RelativeFile -SourceRoot $trackedOverrideRoot -DestinationRoot $restoreRoot -RelativePath $relativePath
        $trackedOverrides.Add($relativePath)
    }
    $actualState = Get-FileState -Root $restoreRoot -RelativePaths $statePaths
    Compare-FileState -Expected $expectedState -Actual $actualState

    $bundleItem = Get-Item -LiteralPath $bundlePath
    $bundleHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundlePath).Hash
    $createdAt = (Get-Date).ToString("o")
    $manifest = [ordered]@{
        schemaVersion = 1
        createdAt = $createdAt
        label = $Label
        repositoryPath = $repositoryRoot
        backupPath = $backupDirectory
        git = [ordered]@{
            head = $head
            branch = $branch
            dirty = [bool]$status
            status = $status
            remotes = $remoteText
            submodules = $submoduleText
            lfs = [ordered]@{
                available = $lfsAvailable
                version = $lfsVersion
                status = $lfsStatus
                trackedFiles = @($lfsFiles)
                note = "Current LFS working files are copied; the Git bundle does not embed historical LFS objects."
            }
        }
        artifacts = [ordered]@{
            bundle = [ordered]@{
                file = "isaacsim-mcp-all.bundle"
                bytes = $bundleItem.Length
                sha256 = $bundleHash
                verified = $true
            }
            stagedPatch = [ordered]@{ file = "staged.patch"; bytes = $stagedPatch.Length }
            unstagedPatch = [ordered]@{ file = "unstaged.patch"; bytes = $unstagedPatch.Length }
            fileHashes = "file_hashes.json"
            trackedOverrides = [ordered]@{
                directory = "tracked-overrides"
                files = @($trackedOverrides)
            }
        }
        untracked = [ordered]@{
            gitIgnoredFilesIncluded = $false
            maxFileBytes = $MaxUntrackedFileBytes
            backedUp = @($backedUntracked)
            excluded = @($excludedUntracked)
        }
        validation = [ordered]@{
            bundleVerified = $true
            restoreValidated = $true
            comparedFileCount = $expectedState.Count
            trackedOverrideCount = $trackedOverrides.Count
            temporaryRestoreRemoved = $true
        }
    }
    Write-Utf8File -Path $manifestJsonPath -Content ($manifest | ConvertTo-Json -Depth 8)

    $statusDisplay = if ($status) { "dirty" } else { "clean" }
    $markdown = @"
# IsaacSim MCP project backup

- Created: ``$createdAt``
- Repository: ``$repositoryRoot``
- Branch: ``$branch``
- HEAD: ``$head``
- Worktree: ``$statusDisplay``
- Bundle: ``isaacsim-mcp-all.bundle``
- Bundle bytes: ``$($bundleItem.Length)``
- Bundle SHA-256: ``$bundleHash``
- Bundle verify: passed
- Restore and SHA-256 comparison: passed, ``$($expectedState.Count)`` files checked
- Backed-up untracked files: ``$($backedUntracked.Count)``
- Excluded untracked files: ``$($excludedUntracked.Count)``
- Git LFS tracked files copied: ``$($lfsFiles.Count)``
- Exact-byte tracked overrides: ``$($trackedOverrides.Count)``

The backup never includes Git-ignored files. Credential-like, cache/build, and oversized
untracked files are excluded and listed by reason in ``manifest.json``. Restore into a new
empty directory; do not overwrite a newer working tree.
"@
    Write-Utf8File -Path $manifestMarkdownPath -Content $markdown

    [pscustomobject]@{
        BackupPath = $backupDirectory
        BundlePath = $bundlePath
        BundleSha256 = $bundleHash
        Head = $head
        Worktree = $statusDisplay
        RestoreValidated = $true
        ComparedFiles = $expectedState.Count
        BackedUntrackedFiles = $backedUntracked.Count
        ExcludedUntrackedFiles = $excludedUntracked.Count
        TrackedOverrideFiles = $trackedOverrides.Count
    }
}
catch {
    $safeFailure = Redact-SensitiveText $_.Exception.Message
    Write-Utf8File -Path $failurePath -Content $safeFailure
    throw
}
finally {
    if ($validationRoot -and (Test-Path -LiteralPath $validationRoot)) {
        $temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $validationFull = [System.IO.Path]::GetFullPath($validationRoot)
        $leaf = Split-Path -Leaf $validationFull
        if ((Test-PathInside -Candidate $validationFull -Parent $temporaryRoot) -and
            $leaf.StartsWith("isaacsim-mcp-backup-verify-", [System.StringComparison]::Ordinal)) {
            Remove-Item -LiteralPath $validationFull -Recurse -Force
        }
        else {
            throw "Refusing to remove unexpected validation directory: $validationFull"
        }
    }
}
