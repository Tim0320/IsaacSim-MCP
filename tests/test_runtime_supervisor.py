"""Tests for bounded Isaac Sim restart supervision."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from isaac_mcp.runtime_supervisor import SupervisorConfig, run_supervisor


class _FakeProcess:
    def __init__(self, polls):
        self._polls = deque(polls)

    def poll(self):
        if len(self._polls) > 1:
            return self._polls.popleft()
        return self._polls[0]


def _config(tmp_path: Path, **overrides) -> SupervisorConfig:
    values = {
        "repository_root": tmp_path,
        "isaac_sim_root": tmp_path / "isaacsim",
        "state_file": tmp_path / "runtime-state.json",
        "port": 8766,
        "max_restarts": 3,
        "restart_window_seconds": 300.0,
        "backoff_seconds": 0.01,
        "health_interval_seconds": 0.01,
        "health_timeout_seconds": 0.01,
    }
    values.update(overrides)
    return SupervisorConfig(**values)


def test_nonzero_exit_restarts_and_preserves_last_crash(tmp_path):
    processes = deque([_FakeProcess([None, 23]), _FakeProcess([None, 0])])
    states = []
    health = deque(
        [
            {"responding": False},
            {"responding": True, "checked_at": "2026-08-27T11:00:00Z"},
            {"responding": True, "checked_at": "2026-08-27T11:00:01Z"},
        ]
    )

    result = run_supervisor(
        _config(tmp_path),
        launch_process=lambda _command: processes.popleft(),
        health_probe=lambda **_kwargs: health.popleft(),
        sleep=lambda _seconds: None,
        write_state=lambda _path, state: states.append(state.copy()),
    )

    assert result == 0
    assert [state["state"] for state in states].count("restart_backoff") == 1
    assert states[-1]["state"] == "stopped"
    assert states[-1]["last_crash"]["exit_code"] == 23
    assert states[-1]["restart_count"] == 1


def test_zero_exit_is_normal_and_never_restarts(tmp_path):
    launches = []
    states = []

    result = run_supervisor(
        _config(tmp_path),
        launch_process=lambda command: launches.append(command) or _FakeProcess([0]),
        health_probe=lambda **_kwargs: {"responding": False},
        sleep=lambda _seconds: None,
        write_state=lambda _path, state: states.append(state.copy()),
    )

    assert result == 0
    assert len(launches) == 1
    assert states[-1]["state"] == "stopped"
    assert states[-1]["reason"] == "normal_exit"


def test_restart_budget_fails_closed(tmp_path):
    states = []

    result = run_supervisor(
        _config(tmp_path, max_restarts=1),
        launch_process=lambda _command: _FakeProcess([31]),
        health_probe=lambda **_kwargs: {"responding": False},
        sleep=lambda _seconds: None,
        write_state=lambda _path, state: states.append(state.copy()),
    )

    assert result == 31
    assert states[-1]["state"] == "recovery_failed"
    assert states[-1]["availability_code"] == "ISAAC_RUNTIME_CRASHED"
    assert states[-1]["last_crash"]["exit_code"] == 31


def test_alive_but_unresponsive_process_is_reported_without_termination(tmp_path):
    states = []

    result = run_supervisor(
        _config(tmp_path),
        launch_process=lambda _command: _FakeProcess([None, 0]),
        health_probe=lambda **_kwargs: {
            "responding": False,
            "checked_at": "2026-08-27T11:00:00Z",
            "error": "health probe timed out",
        },
        sleep=lambda _seconds: None,
        write_state=lambda _path, state: states.append(state.copy()),
    )

    assert result == 0
    assert any(state["state"] == "starting" for state in states)
    assert all(state["state"] != "restart_backoff" for state in states)


def test_existing_healthy_runtime_is_not_launched_again(tmp_path):
    launches = []
    states = []

    result = run_supervisor(
        _config(tmp_path),
        launch_process=lambda command: launches.append(command),
        health_probe=lambda **_kwargs: {
            "responding": True,
            "checked_at": "2026-08-27T11:00:00Z",
        },
        sleep=lambda _seconds: None,
        write_state=lambda _path, state: states.append(state.copy()),
    )

    assert result == 2
    assert launches == []
    assert states[-1]["state"] == "external_runtime_detected"
    assert states[-1]["supervised"] is False


def test_occupied_but_unresponsive_runtime_port_is_not_launched_over(tmp_path):
    launches = []
    states = []

    result = run_supervisor(
        _config(tmp_path),
        launch_process=lambda command: launches.append(command),
        health_probe=lambda **_kwargs: {
            "responding": False,
            "port_open": True,
            "checked_at": "2026-08-27T11:00:00Z",
            "error": "protocol health timed out",
        },
        sleep=lambda _seconds: None,
        write_state=lambda _path, state: states.append(state.copy()),
    )

    assert result == 2
    assert launches == []
    assert states[-1]["state"] == "external_runtime_unresponsive"
    assert states[-1]["reason"] == "runtime_port_in_use_but_unresponsive"
