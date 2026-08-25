"""Release, installation, and protocol documentation contracts."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_readme_routes_fresh_install_protocol_and_release_gate():
    readme = _text("README.md")
    for link in (
        "docs/INSTALLATION_WINDOWS.md",
        "docs/PROTOCOL_VERSIONING_AND_MIGRATION.md",
        "docs/RELEASE_GATE.md",
        "docs/ALL_TOOLS_TEST_RESULTS.json",
    ):
        assert link in readme
    assert '"isaac-sim-live"' in readme
    assert "https://github.com/Tim0320/IsaacSim-MCP.git" in readme


def test_protocol_versions_and_migration_boundaries_are_explicit():
    protocol = _text("docs/PROTOCOL_VERSIONING_AND_MIGRATION.md")
    for value in (
        "Response envelope | `1.0`",
        "Capability data | `1.1`",
        "Backend matrix | `1.0`",
        "Idempotency ledger",
        "managed artifact",
        "preview=true",
        "Isaac Sim `6.0.1` + Newton",
        "legacy adapter",
    ):
        assert value in protocol


def test_fresh_install_is_secret_free_and_uses_exact_live_route():
    installation = _text("docs/INSTALLATION_WINDOWS.md")
    assert "git clone https://github.com/Tim0320/IsaacSim-MCP.git D:\\Dev\\IsaacSim-MCP" in installation
    assert '"isaac-sim-live"' in installation
    assert "127.0.0.1:8766" in installation
    assert "9904" in installation and "documentation route" in installation
    assert "不需要任何 API key" in installation


def test_release_gate_is_fail_closed_and_contains_no_git_publish_operation():
    script = _text("scripts/release_gate.ps1")
    for gate in (
        "repository identity",
        "worktree policy",
        "publish candidate secret scan",
        "verified repository backup",
        "offline test pyramid",
        "publish candidate format check",
        "read-only Isaac Sim 6.0.1 live matrix",
        "wheel build and clean virtualenv import",
        "worktree preservation and Git review",
    ):
        assert gate in script
    assert 'ExpectedRemote = "https://github.com/Tim0320/IsaacSim-MCP.git"' in script
    assert "& git push" not in script
    assert "& git tag" not in script
    assert "& git merge" not in script


def test_all_tools_check_mode_does_not_rewrite_tracked_artifacts():
    before = {name: _sha256(name) for name in ("docs/ALL_TOOLS_TEST_REPORT.md", "docs/ALL_TOOLS_TEST_RESULTS.json")}
    result = subprocess.run(
        [sys.executable, "scripts/generate_all_tools_report.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"mode": "check"' in result.stdout
    assert before == {name: _sha256(name) for name in before}
