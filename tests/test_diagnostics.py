"""Tests for bounded, redacted, command-correlated diagnostic records."""

from isaac_sim_mcp_extension import diagnostics


def setup_function():
    diagnostics.clear()


def teardown_function():
    diagnostics.clear()


def test_records_are_correlated_filterable_and_redacted(monkeypatch):
    monkeypatch.setattr(diagnostics, "_stage_identifier", lambda: "scratch.usda")
    diagnostics.record(
        "authorization=abc123 failed",
        severity="error",
        source="dispatcher",
        command_id="cmd-1",
        command_type="scene.open",
        details={"api_key": "secret-value", "code": "OPEN_FAILED"},
    )
    diagnostics.record("other", command_id="cmd-2")
    records = diagnostics.query(command_id="cmd-1", severity="error")
    assert len(records) == 1
    assert records[0]["message"] == "authorization=[REDACTED] failed"
    assert records[0]["details"]["api_key"] == "[REDACTED]"
    assert records[0]["stage"] == "scratch.usda"


def test_query_and_message_limits_are_enforced():
    diagnostics.record("x" * (diagnostics.MAX_MESSAGE_BYTES * 2), command_id="cmd")
    assert diagnostics.query(count=1)[0]["message"].endswith("... [truncated]")
    try:
        diagnostics.query(count=diagnostics.MAX_QUERY_COUNT + 1)
    except ValueError as exc:
        assert "count must be" in str(exc)
    else:
        raise AssertionError("oversized diagnostic query was accepted")
