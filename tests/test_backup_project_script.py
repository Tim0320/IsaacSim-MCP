"""Windows integration tests for scripts/backup_project.ps1."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "backup_project.ps1"
PWSH = shutil.which("pwsh")

pytestmark = [
    pytest.mark.windows_launcher,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only integration test"),
    pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required"),
]


def _run(command: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=check, capture_output=True, text=True, encoding="utf-8")


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "git",
            "-c",
            f"safe.directory={repository.as_posix()}",
            "-C",
            str(repository),
            *arguments,
        ]
    )


def _create_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    _run(["git", "init", "-b", "main", str(repository)])
    _git(repository, "config", "user.name", "Backup Test")
    _git(repository, "config", "user.email", "backup-test@example.invalid")
    (repository / "tracked.txt").write_bytes(b"base\n")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "initial")
    return repository


def _run_backup(
    repository: Path,
    backup_root: Path,
    *,
    label: str,
    max_untracked_file_bytes: int = 1024 * 1024,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            PWSH or "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-RepositoryPath",
            str(repository),
            "-BackupRoot",
            str(backup_root),
            "-Label",
            label,
            "-MaxUntrackedFileBytes",
            str(max_untracked_file_bytes),
        ],
        check=check,
    )


def _only_backup(backup_root: Path) -> Path:
    backups = [path for path in backup_root.iterdir() if path.is_dir()]
    assert len(backups) == 1
    return backups[0]


def test_clean_repository_creates_verified_bundle_and_manifests(tmp_path: Path) -> None:
    repository = _create_repository(tmp_path)
    backup_root = tmp_path / "backups"

    _run_backup(repository, backup_root, label="clean")

    backup = _only_backup(backup_root)
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git"]["dirty"] is False
    assert manifest["validation"]["bundleVerified"] is True
    assert manifest["validation"]["restoreValidated"] is True
    assert manifest["validation"]["comparedFileCount"] == 1
    assert (backup / "BACKUP_MANIFEST.md").is_file()
    assert not (backup / "BACKUP_FAILED.txt").exists()
    _git(repository, "bundle", "verify", str(backup / "isaacsim-mcp-all.bundle"))
    assert _git(repository, "status", "--porcelain=v1").stdout == ""


def test_dirty_repository_restores_patches_and_safe_untracked_files(tmp_path: Path) -> None:
    repository = _create_repository(tmp_path)
    backup_root = tmp_path / "backups"

    (repository / "tracked.txt").write_bytes(b"staged\n")
    _git(repository, "add", "tracked.txt")
    (repository / "tracked.txt").write_bytes(b"staged\nunstaged\n")
    safe_file = repository / "notes" / "research.txt"
    safe_file.parent.mkdir()
    safe_file.write_bytes(b"safe untracked research\n")
    (repository / ".env").write_text("TOKEN=do-not-copy\n", encoding="utf-8")
    build_file = repository / "build" / "cache.bin"
    build_file.parent.mkdir()
    build_file.write_bytes(b"cache")
    (repository / "large.bin").write_bytes(b"x" * 33)

    _run_backup(repository, backup_root, label="dirty", max_untracked_file_bytes=32)

    backup = _only_backup(backup_root)
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git"]["dirty"] is True
    assert manifest["validation"]["restoreValidated"] is True
    assert manifest["untracked"]["backedUp"] == ["notes/research.txt"]
    excluded = {entry["path"]: entry["reason"] for entry in manifest["untracked"]["excluded"]}
    assert excluded[".env"] == "credential_like_name"
    assert excluded["build/cache.bin"] == "excluded_directory:build"
    assert excluded["large.bin"] == "oversized:33>32"
    assert (backup / "untracked" / "notes" / "research.txt").read_bytes() == safe_file.read_bytes()
    assert not any(path.name == ".env" for path in backup.rglob("*"))
    assert (backup / "staged.patch").stat().st_size > 0
    assert (backup / "unstaged.patch").stat().st_size > 0
    assert (repository / "tracked.txt").read_bytes() == b"staged\nunstaged\n"


def test_backup_root_inside_repository_is_rejected(tmp_path: Path) -> None:
    repository = _create_repository(tmp_path)
    backup_root = repository / "backups"

    result = _run_backup(repository, backup_root, label="unsafe", check=False)

    assert result.returncode != 0
    assert "BackupRoot must be outside the repository" in result.stderr
    assert not backup_root.exists()
