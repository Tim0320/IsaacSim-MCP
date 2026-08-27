"""Runtime-supervisor state and MCP recovery-envelope contracts."""

from __future__ import annotations

import json

from isaac_mcp import runtime_status


def test_missing_state_file_is_reported_as_unmanaged(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=tmp_path / "missing.json")

    assert result["state"] == "unmanaged"
    assert result["supervised"] is False
    assert result["runtime_responding"] is False
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"


def test_supervisor_crash_state_is_bounded_and_exposed(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "restart_backoff",
                "supervised": True,
                "attempt": 2,
                "max_restarts": 3,
                "next_restart_at": "2026-08-27T11:00:05Z",
                "last_crash": {
                    "occurred_at": "2026-08-27T11:00:03Z",
                    "exit_code": 17,
                    "was_ready": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=state_file)
    response = runtime_status.runtime_unavailable_response(result, command_id="cmd-1")

    assert result["availability_code"] == "ISAAC_RUNTIME_RECOVERING"
    assert result["last_crash"]["exit_code"] == 17
    assert response["status"] == "error"
    assert response["code"] == "ISAAC_RUNTIME_RECOVERING"
    assert response["command_id"] == "cmd-1"
    assert response["data"]["runtime"]["next_restart_at"].endswith("Z")
    assert response["readback"]["required"] is True
    assert "do_not_replay_write" in response["data"]["runtime"]["recommended_actions"]


def test_live_health_overrides_stale_crash_state(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "crashed",
                "supervised": True,
                "last_crash": {"exit_code": 9},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_status,
        "probe_runtime_health",
        lambda **_kwargs: {"responding": True, "checked_at": "2026-08-27T11:01:00Z"},
    )

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "ready"
    assert result["runtime_responding"] is True
    assert result["availability_code"] == "ISAAC_RUNTIME_READY"
    assert result["last_crash"]["exit_code"] == 9


def test_invalid_state_file_fails_closed_without_echoing_contents(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text("token=do-not-echo", encoding="utf-8")
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "diagnostic_unavailable"
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert "do-not-echo" not in json.dumps(result)


def test_stale_ready_state_becomes_unresponsive_when_protocol_probe_fails(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps({"schema_version": "1.0", "state": "ready", "supervised": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_status,
        "probe_runtime_health",
        lambda **_kwargs: {"responding": False, "error": "probe timed out"},
    )

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "unresponsive"
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert "inspect_unresponsive_runtime" in result["recommended_actions"]
    assert "start_supervised_isaac_runtime" not in result["recommended_actions"]
