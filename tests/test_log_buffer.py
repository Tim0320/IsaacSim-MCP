# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Unit tests for the get_isaac_logs buffer selection logic."""

from isaac_sim_mcp_extension.handlers import simulation as sim


def test_select_logs_since_last_play_filters_to_current_run():
    buf = ["a", "b", "c", "d"]
    # Play happened after 'b' -> boundary index 2
    assert sim._select_logs(buf, boundary=2, since_last_play=True, count=100) == ["c", "d"]


def test_select_logs_all_when_not_scoped():
    buf = ["a", "b", "c", "d"]
    assert sim._select_logs(buf, boundary=2, since_last_play=False, count=100) == ["a", "b", "c", "d"]


def test_select_logs_respects_count():
    buf = ["a", "b", "c", "d"]
    assert sim._select_logs(buf, boundary=0, since_last_play=True, count=2) == ["c", "d"]


def test_get_logs_default_is_non_destructive(monkeypatch):
    monkeypatch.setattr(sim, "_log_buffer", ["x", "y"], raising=False)
    monkeypatch.setattr(sim, "_play_boundary", 0, raising=False)
    monkeypatch.setattr(sim, "_ensure_log_listener", lambda: None)
    # No Kit log file in scope: this test covers the [PRINT] buffer path only.
    monkeypatch.setattr(sim, "get_kit_log_path", lambda: None)
    result = sim.get_logs(adapter=None)  # defaults: clear=False
    assert result["logs"] == ["x", "y"]
    assert sim._log_buffer == ["x", "y"]  # buffer intact


def test_append_and_mark_boundary_scopes_new_run(monkeypatch):
    monkeypatch.setattr(sim, "_log_buffer", [], raising=False)
    monkeypatch.setattr(sim, "_play_boundary", 0, raising=False)
    monkeypatch.setattr(sim, "_ensure_log_listener", lambda: None)
    sim.append_log("[PRINT] old")
    sim.mark_play_boundary()
    sim.append_log("[PRINT] new")
    result = sim.get_logs(adapter=None, since_last_play=True)
    assert result["logs"] == ["[PRINT] new"]


def test_legacy_print_buffer_is_redacted_before_storage(monkeypatch):
    monkeypatch.setattr(sim, "_log_buffer", [], raising=False)
    monkeypatch.setattr(sim, "_play_boundary", 0, raising=False)
    sim.append_log("[PRINT] token=must-not-remain")
    assert sim._log_buffer == ["[PRINT] token=[REDACTED]"]


def test_no_python_log_consumer_is_installed():
    """Regression guard for the Isaac Sim 5.1 deadlock.

    A carb/omni.log message consumer is invoked on whatever thread emitted the
    message. omni.physx emits warnings from native TBB worker threads during a
    physics load while the calling thread holds the GIL inside the native call,
    so a Python consumer deadlocks kit permanently (reproduced: spawning a
    Franka FR3, which logs invalid-inertia warnings, wedges kit forever).
    WARN/ERROR must come from Kit's log file instead.
    """
    import inspect

    src = inspect.getsource(sim)
    assert "add_message_consumer" not in src, "Python log consumer reintroduced — deadlocks physics load on 5.1"
    assert "set_channel_enabled" not in src, "global log-channel override reintroduced"


def test_get_logs_reads_kit_log_file_for_warnings(monkeypatch, tmp_path):
    """WARN/ERROR are sourced from Kit's session log file."""
    log = tmp_path / "kit_test.log"
    log.write_text(
        "2026-01-01T00:00:00Z [1ms] [Info] [x] boring\n"
        "2026-01-01T00:00:00Z [2ms] [Warning] [omni.physx.plugin] invalid inertia tensor\n"
        "2026-01-01T00:00:00Z [3ms] [Error] [omni.kit] something failed\n"
    )
    monkeypatch.setattr(sim, "_log_buffer", [], raising=False)
    monkeypatch.setattr(sim, "_play_boundary", 0, raising=False)
    monkeypatch.setattr(sim, "_kit_log_play_offset", 0, raising=False)
    monkeypatch.setattr(sim, "_ensure_log_listener", lambda: None)
    monkeypatch.setattr(sim, "get_kit_log_path", lambda: str(log))

    result = sim.get_logs(adapter=None)
    assert result["status"] == "success"
    assert any("invalid inertia tensor" in entry for entry in result["logs"])
    assert any("something failed" in entry for entry in result["logs"])
    assert not any("boring" in entry for entry in result["logs"]), "Info lines must be filtered out"
