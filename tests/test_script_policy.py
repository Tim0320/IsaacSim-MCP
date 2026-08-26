"""Fail-closed contract tests for the script escape hatch."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from isaac_sim_mcp_extension.execution_guard import (
    BoundedTextBuffer,
    ScriptExecutionTimeout,
    ScriptOutputLimitExceeded,
    cooperative_deadline,
)
from isaac_sim_mcp_extension.handlers import simulation
from isaac_sim_mcp_extension.script_policy import SCRIPT_POLICY, ScriptPolicy


@pytest.fixture(autouse=True)
def restore_policy():
    previous = SCRIPT_POLICY.policy
    yield
    SCRIPT_POLICY.policy = previous


def _policy(**overrides):
    defaults = dict(
        enabled=True,
        allowed_roots=(str(Path(__file__).resolve().parents[1]),),
        default_timeout_s=1.0,
        max_timeout_s=10.0,
        default_output_bytes=64,
        max_output_bytes=1024,
        max_code_bytes=1024,
        allow_background=False,
    )
    defaults.update(overrides)
    return ScriptPolicy(**defaults)


def test_disabled_policy_rejects_before_adapter_execution():
    SCRIPT_POLICY.policy = _policy(enabled=False)
    adapter = MagicMock()

    result = simulation.execute_script(adapter, code="result = 42")

    assert result["code"] == "SCRIPT_EXECUTION_DISABLED"
    assert result["applied"] is False
    adapter.execute_script.assert_not_called()


def test_cwd_escape_and_background_scheduling_fail_closed(tmp_path: Path):
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()

    SCRIPT_POLICY.policy = _policy(allowed_roots=(str(allowed_root),))
    adapter = MagicMock()

    cwd = simulation.execute_script(adapter, code="result = 1", cwd=str(outside_root))
    background = simulation.execute_script(
        adapter, code="import threading\nthreading.Thread(target=lambda: None).start()"
    )

    assert cwd["code"] == "SCRIPT_POLICY_DENIED"
    assert background["code"] == "SCRIPT_POLICY_DENIED"
    adapter.execute_script.assert_not_called()


def test_limits_are_validated_then_forwarded_and_audited_without_source():
    SCRIPT_POLICY.policy = _policy()
    adapter = MagicMock(return_value=None)
    adapter.execute_script.return_value = {"status": "success", "stdout": "ok\n", "stderr": ""}

    result = simulation.execute_script(
        adapter,
        code="print('secret-shaped source is not logged')",
        timeout_s=2.0,
        max_output_bytes=128,
    )
    audit = simulation.get_script_audit(count=1)

    assert result["status"] == "success"
    adapter.execute_script.assert_called_once_with(
        "print('secret-shaped source is not logged')", cwd=None, timeout_s=2.0, max_output_bytes=128
    )
    record = audit["data"]["records"][0]
    assert record["outcome"] == "success"
    assert len(record["target_sha256"]) == 64
    assert "secret-shaped" not in str(record)


def test_bounded_output_stops_the_writer_at_the_cap():
    output = BoundedTextBuffer(4)
    with pytest.raises(ScriptOutputLimitExceeded):
        output.write("12345")
    assert len(output.getvalue().encode("utf-8")) <= 4


def test_cooperative_deadline_stops_python_bytecode():
    started = time.monotonic()
    with pytest.raises(ScriptExecutionTimeout), cooperative_deadline(0.01):
        while True:
            pass
    assert time.monotonic() - started < 1.0
