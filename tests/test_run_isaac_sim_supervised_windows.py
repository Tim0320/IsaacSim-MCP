"""Windows integration tests for the bounded Isaac Sim supervisor launcher."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_isaac_sim_supervised.ps1"
PWSH = shutil.which("pwsh")

pytestmark = [
    pytest.mark.windows_launcher,
    pytest.mark.skipif(os.name != "nt" or PWSH is None, reason="Windows and PowerShell 7 are required"),
]


def _fake_isaac_root(tmp_path: Path, exit_code: int) -> Path:
    root = tmp_path / "fake isaac sim"
    root.mkdir()
    (root / "VERSION").write_text("6.0.1\n", encoding="ascii")
    (root / "isaac-sim.bat").write_text(f"@echo off\r\nexit /b {exit_code}\r\n", encoding="ascii")
    return root


def _run(tmp_path: Path, exit_code: int) -> tuple[subprocess.CompletedProcess[str], dict]:
    state_file = tmp_path / "runtime state.json"
    result = subprocess.run(
        [
            PWSH or "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-IsaacSimRoot",
            str(_fake_isaac_root(tmp_path, exit_code)),
            "-StateFile",
            str(state_file),
            "-MaxRestarts",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "ISAAC_PHYSICS_GPU": "0"},
    )
    return result, json.loads(state_file.read_text(encoding="utf-8"))


def test_normal_exit_stops_without_restart(tmp_path):
    result, state = _run(tmp_path, 0)

    assert result.returncode == 0, result.stderr
    assert state["state"] == "stopped"
    assert state["reason"] == "normal_exit"
    assert state["restart_count"] == 0


def test_abnormal_exit_publishes_crash_evidence(tmp_path):
    result, state = _run(tmp_path, 37)

    assert result.returncode == 37
    assert state["state"] == "recovery_failed"
    assert state["availability_code"] == "ISAAC_RUNTIME_CRASHED"
    assert state["last_crash"]["exit_code"] == 37
