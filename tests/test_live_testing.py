"""Offline contract tests for the destructive live-test guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from isaac_mcp.live_testing import ScratchRun, ScratchStageGuardError


class FakeConnection:
    def __init__(self, stage_path: str, timeline_state: str = "stopped", namespace_exists: bool = False):
        self.stage_path = stage_path
        self.timeline_state = timeline_state
        self.namespace_exists = namespace_exists

    def send_command(self, command: str, params=None):
        if command == "scene.get_info":
            return {"status": "success", "data": {"stage_path": self.stage_path}}
        if command == "simulation.get_state":
            return {"status": "success", "data": {"timeline_state": self.timeline_state}}
        if command == "scene.get_prim_info":
            prim_path = params["prim_path"]
            if self.namespace_exists:
                return {"status": "success"}
            return {"status": "error", "code": "COMMAND_FAILED", "message": f"Prim not found: {prim_path}"}
        if command == "objects.delete":
            self.namespace_exists = False
            return {"status": "success"}
        raise AssertionError(command)


def test_guard_accepts_exact_stopped_scratch_stage_and_unique_namespace(tmp_path: Path):
    stage = tmp_path / "run.usda"
    run = ScratchRun.validate(
        FakeConnection(str(stage)),
        expected_stage_path=str(stage),
        scratch_root=str(tmp_path),
        run_id="a" * 32,
    )
    assert run.namespace == f"/World/MCP_Live_{'a' * 32}"


@pytest.mark.parametrize(
    ("actual", "expected", "state", "message"),
    [
        ("", "run.usda", "stopped", "anonymous"),
        ("other.usda", "run.usda", "stopped", "does not match"),
        ("run.usda", "run.usda", "playing", "timeline must be stopped"),
    ],
)
def test_guard_refuses_unproven_stage(tmp_path: Path, actual: str, expected: str, state: str, message: str):
    actual_path = str(tmp_path / actual) if actual else ""
    with pytest.raises(ScratchStageGuardError, match=message):
        ScratchRun.validate(
            FakeConnection(actual_path, state),
            expected_stage_path=str(tmp_path / expected),
            scratch_root=str(tmp_path),
            run_id="b" * 32,
        )


def test_guard_refuses_stage_outside_scratch_root(tmp_path: Path):
    outside = tmp_path.parent / "outside.usda"
    with pytest.raises(ScratchStageGuardError, match="outside"):
        ScratchRun.validate(
            FakeConnection(str(outside)),
            expected_stage_path=str(outside),
            scratch_root=str(tmp_path),
            run_id="c" * 32,
        )


def test_cleanup_deletes_only_run_namespace_and_reads_back_absence(tmp_path: Path):
    connection = FakeConnection(str(tmp_path / "run.usda"), namespace_exists=True)
    run = ScratchRun(stage_path=tmp_path / "run.usda", scratch_root=tmp_path, namespace=f"/World/MCP_Live_{'d' * 32}")
    assert run.cleanup(connection) == {"namespace": run.namespace, "prim_absent": True}


def test_guard_does_not_treat_transport_error_as_prim_absence(tmp_path: Path):
    connection = FakeConnection(str(tmp_path / "run.usda"))
    connection.send_command = lambda command, params=None: (
        {"status": "success", "data": {"stage_path": str(tmp_path / "run.usda")}}
        if command == "scene.get_info"
        else {"status": "success", "data": {"timeline_state": "stopped"}}
        if command == "simulation.get_state"
        else {"status": "error", "code": "CONNECTION_ERROR", "message": "socket closed"}
    )
    with pytest.raises(ScratchStageGuardError, match="could not prove prim absent"):
        ScratchRun.validate(
            connection,
            expected_stage_path=str(tmp_path / "run.usda"),
            scratch_root=str(tmp_path),
            run_id="e" * 32,
        )
