"""Regression tests for the Windows Isaac Sim launcher."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_isaac_sim.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or PWSH is None,
    reason="Windows and PowerShell 7 are required",
)


def _write_batch(path: Path, lines: list[str]) -> None:
    path.write_text("\r\n".join(["@echo off", *lines, ""]), encoding="ascii")


def _fake_isaac_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fake isaac sim"
    root.mkdir()
    (root / "VERSION").write_text("6.0.1\n", encoding="ascii")
    capture = tmp_path / "isaac-argv.txt"
    _write_batch(
        root / "isaac-sim.bat",
        [
            ":capture",
            'if "%~1"=="" goto done',
            '>>"%ISAAC_CAPTURE_FILE%" echo(%~1',
            "shift",
            "goto capture",
            ":done",
            "exit /b %ISAAC_FAKE_EXIT_CODE%",
        ],
    )
    return root, capture


def _fake_nvidia_smi(tmp_path: Path, rows: list[str], *, exit_code: int = 0) -> Path:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    lines = ['>>"%NVIDIA_SMI_CAPTURE_FILE%" echo(%*']
    lines.extend(f"echo {row}" for row in rows)
    lines.append(f"exit /b {exit_code}")
    _write_batch(bin_dir / "nvidia-smi.cmd", lines)
    return bin_dir


def _run_launcher(
    tmp_path: Path,
    arguments: list[str] | None = None,
    *,
    gpu_rows: list[str] | None = None,
    gpu_exit_code: int = 0,
    physics_gpu_env: str | None = None,
    exit_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    isaac_root, isaac_capture = _fake_isaac_root(tmp_path)
    nvidia_smi_capture = tmp_path / "nvidia-smi-argv.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "ISAAC_CAPTURE_FILE": str(isaac_capture),
            "ISAAC_FAKE_EXIT_CODE": str(exit_code),
            "NVIDIA_SMI_CAPTURE_FILE": str(nvidia_smi_capture),
        }
    )
    if physics_gpu_env is None:
        environment.pop("ISAAC_PHYSICS_GPU", None)
    else:
        environment["ISAAC_PHYSICS_GPU"] = physics_gpu_env
    if gpu_rows is not None:
        fake_bin = _fake_nvidia_smi(tmp_path, gpu_rows, exit_code=gpu_exit_code)
        environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        [
            PWSH or "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-IsaacSimRoot",
            str(isaac_root),
            *(arguments or []),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    return result, isaac_capture, nvidia_smi_capture


def _captured_arguments(capture: Path) -> list[str]:
    if not capture.exists():
        return []

    # cmd.exe treats ``=`` as a batch positional-argument separator. Recombine
    # Kit setting name/value pairs so assertions reflect the logical argv that
    # isaac-sim.bat forwards to Kit.
    raw_arguments = capture.read_text(encoding="utf-8").splitlines()
    arguments: list[str] = []
    index = 0
    while index < len(raw_arguments):
        argument = raw_arguments[index]
        if argument.startswith("--/") and "=" not in argument and index + 1 < len(raw_arguments):
            arguments.append(f"{argument}={raw_arguments[index + 1]}")
            index += 2
            continue
        arguments.append(argument)
        index += 1
    return arguments


def _physics_arguments(capture: Path) -> list[str]:
    return [argument for argument in _captured_arguments(capture) if argument.startswith("--/physics/cudaDevice=")]


@pytest.mark.parametrize(
    ("arguments", "physics_gpu_env", "gpu_rows", "expected"),
    [
        (
            ["-PhysicsGpu", "4", "--/physics/cudaDevice=7"],
            "3",
            ["0, Enabled", "1, Disabled"],
            7,
        ),
        (["-PhysicsGpu", "4"], "3", ["0, Enabled"], 4),
        ([], "3", ["0, Enabled"], 3),
        ([], None, ["0, Disabled", "1, Enabled"], 1),
    ],
)
def test_gpu_selection_priority(
    tmp_path: Path,
    arguments: list[str],
    physics_gpu_env: str | None,
    gpu_rows: list[str],
    expected: int,
) -> None:
    result, capture, _ = _run_launcher(
        tmp_path,
        arguments,
        physics_gpu_env=physics_gpu_env,
        gpu_rows=gpu_rows,
    )

    assert result.returncode == 0, result.stderr
    assert _physics_arguments(capture) == [f"--/physics/cudaDevice={expected}"]


@pytest.mark.parametrize(
    "gpu_rows",
    [
        ["0, Disabled", "1, Disabled"],
        ["0, Enabled", "1, Enabled"],
    ],
    ids=["no-display-active-gpu", "multiple-display-active-gpus"],
)
def test_ambiguous_display_gpu_falls_back_to_zero_with_warning(tmp_path: Path, gpu_rows: list[str]) -> None:
    result, capture, _ = _run_launcher(tmp_path, gpu_rows=gpu_rows)

    assert result.returncode == 0, result.stderr
    assert _physics_arguments(capture) == ["--/physics/cudaDevice=0"]
    output = f"{result.stdout}\n{result.stderr}".upper()
    assert "WARNING" in output
    assert "GPU 0" in output


def test_gpu_probe_failure_falls_back_to_zero_and_uses_expected_query(tmp_path: Path) -> None:
    result, capture, probe_capture = _run_launcher(
        tmp_path,
        gpu_rows=[],
        gpu_exit_code=23,
    )

    assert result.returncode == 0, result.stderr
    assert _physics_arguments(capture) == ["--/physics/cudaDevice=0"]
    output = f"{result.stdout}\n{result.stderr}".upper()
    assert "WARNING" in output and "GPU 0" in output
    probe_arguments = probe_capture.read_text(encoding="utf-8")
    assert "--query-gpu=index,display_active" in probe_arguments
    assert "--format=csv,noheader,nounits" in probe_arguments


def test_raw_duplicate_cuda_device_uses_last_value_and_passes_it_once(tmp_path: Path) -> None:
    result, capture, _ = _run_launcher(
        tmp_path,
        [
            "--/renderer/multiGpu/enabled=false",
            "--/physics/cudaDevice=1",
            "--/physics/cudaDevice=6",
        ],
        gpu_rows=["0, Enabled"],
    )

    assert result.returncode == 0, result.stderr
    captured = _captured_arguments(capture)
    assert _physics_arguments(capture) == ["--/physics/cudaDevice=6"]
    assert "--/renderer/multiGpu/enabled=false" in captured


def test_minus_one_is_preserved_with_stop_crash_warning(tmp_path: Path) -> None:
    result, capture, _ = _run_launcher(tmp_path, ["-PhysicsGpu", "-1"])

    assert result.returncode == 0, result.stderr
    assert _physics_arguments(capture) == ["--/physics/cudaDevice=-1"]
    output = f"{result.stdout}\n{result.stderr}"
    assert "WARNING" in output.upper()
    assert "PhysXGpu_64.dll" in output
    assert "Stop" in output


@pytest.mark.parametrize(
    ("arguments", "physics_gpu_env"),
    [
        (["-PhysicsGpu", "-2"], None),
        (["-PhysicsGpu", "not-an-integer"], None),
        ([], "-2"),
        ([], "not-an-integer"),
        (["--/physics/cudaDevice=-2"], None),
        (["--/physics/cudaDevice=not-an-integer"], None),
    ],
    ids=[
        "parameter-below-minus-one",
        "parameter-not-integer",
        "environment-below-minus-one",
        "environment-not-integer",
        "raw-below-minus-one",
        "raw-not-integer",
    ],
)
def test_invalid_gpu_is_rejected_before_launch(
    tmp_path: Path, arguments: list[str], physics_gpu_env: str | None
) -> None:
    result, capture, _ = _run_launcher(
        tmp_path,
        arguments,
        physics_gpu_env=physics_gpu_env,
    )

    assert result.returncode != 0
    assert not capture.exists()


def test_other_arguments_and_launcher_exit_code_are_preserved(tmp_path: Path) -> None:
    result, capture, _ = _run_launcher(
        tmp_path,
        ["-Port", "9123", "-PhysicsGpu", "2", "--/app/window/title=Regression Test"],
        exit_code=37,
    )

    assert result.returncode == 37
    captured = _captured_arguments(capture)
    assert "--/exts/isaac.sim.mcp/server.port=9123" in captured
    assert "--/physics/cudaDevice=2" in captured
    assert "--/app/window/title=Regression Test" in captured
