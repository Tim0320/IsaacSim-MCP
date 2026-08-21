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

"""Behavioural unit tests for the simulation command handlers (mock adapter)."""

from unittest.mock import MagicMock

from isaac_sim_mcp_extension.handlers import simulation as sim


def test_step_refuses_when_timeline_playing():
    adapter = MagicMock()
    adapter.get_simulation_state.return_value = {"timeline_state": "playing"}

    result = sim.step(adapter, num_steps=5)

    assert result["status"] == "error"
    assert "running" in result["message"].lower()
    adapter.step.assert_not_called()


def test_step_runs_when_paused_and_reports_state():
    adapter = MagicMock()
    adapter.get_simulation_state.return_value = {"timeline_state": "paused"}
    adapter.step.return_value = {"stepped": 3}

    result = sim.step(adapter, num_steps=3)

    assert result["status"] == "success"
    assert result["timeline_state"] == "paused"
    assert result["stepped"] == 3
    adapter.step.assert_called_once()


def test_step_runs_when_stopped():
    adapter = MagicMock()
    adapter.get_simulation_state.return_value = {"timeline_state": "stopped"}
    adapter.step.return_value = {"stepped": 1}

    result = sim.step(adapter, num_steps=1)

    assert result["status"] == "success"
    adapter.step.assert_called_once()


# ── Stepping must not evaluate Action Graphs ────────────────────────────────


def test_step_suspends_action_graphs():
    """Stepping runs the timeline, which fires OnPlaybackTick.

    Without suspension a ScriptNode controller re-commands the robot on every
    stepped frame, silently discarding the caller's set_joint_positions —
    observed on 5.1, where the drive targets came back as RMPflow's output
    instead of the commanded values, with no error raised anywhere. Verified
    after the fix: all nine FR3 targets survive a 60-frame step.
    """
    import ast
    import os

    v5 = os.path.join(
        os.path.dirname(__file__),
        "..",
        "isaac.sim.mcp_extension",
        "isaac_sim_mcp_extension",
        "adapters",
        "v5.py",
    )
    with open(v5) as f:
        text = f.read()
    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "step":
            src = ast.get_source_segment(text, node)
    assert src, "v5 step() not found"
    assert "_graphs_suspended" in src, "step must suspend Action Graphs while it runs the timeline"


def test_graph_suspension_restores_state():
    """Graphs must come back on, including when the step raises, and graphs the
    caller had already disabled must be left alone."""
    import ast
    import os

    base = os.path.join(
        os.path.dirname(__file__),
        "..",
        "isaac.sim.mcp_extension",
        "isaac_sim_mcp_extension",
        "adapters",
        "base.py",
    )
    with open(base) as f:
        text = f.read()
    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_graphs_suspended":
            src = ast.get_source_segment(text, node)
    assert src, "_graphs_suspended not found"
    assert "finally:" in src, "restoration must survive an exception"
    assert "set_disabled(False)" in src
    assert "is_disabled()" in src, "already-disabled graphs must not be re-enabled"


# ── set_physics_params ───────────────────────────────────────────────────────


class _GravityAdapter:
    def __init__(self):
        self.calls = []

    def create_physics_scene(self, gravity=None, scene_name="PhysicsScene"):
        self.calls.append(gravity)
        return "/World/" + scene_name


def test_set_physics_forwards_gravity_to_the_adapter():
    """Gravity used to be accepted and dropped: asking for Mars [0,0,-3.72] on
    6.0.1 still measured -4.7415 m/s after 30 frames, i.e. Earth."""
    from isaac_sim_mcp_extension.handlers.simulation import set_physics

    adapter = _GravityAdapter()
    result = set_physics(adapter, gravity=[0, 0, -3.72])

    assert result["status"] == "success"
    assert adapter.calls == [[0, 0, -3.72]]


def test_set_physics_reports_parameters_it_cannot_apply():
    """time_step and gpu_enabled are in the signature but unimplemented.

    They were swallowed under a blanket "Physics parameters updated", so a
    caller could set a time step, be told it worked, and silently run the whole
    session at the default rate.
    """
    from isaac_sim_mcp_extension.handlers.simulation import set_physics

    result = set_physics(_GravityAdapter(), time_step=1.0 / 240.0, gpu_enabled=True)

    assert result["status"] == "error"
    assert "time_step" in result["message"]
    assert "gpu_enabled" in result["message"]


def test_set_physics_rejects_an_empty_request():
    from isaac_sim_mcp_extension.handlers.simulation import set_physics

    result = set_physics(_GravityAdapter())

    assert result["status"] == "error"
