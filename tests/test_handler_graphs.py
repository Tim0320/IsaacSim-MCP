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

"""Structural tests for the action-graph handler inline_script path."""

import ast
import os

HANDLERS = os.path.join(
    os.path.dirname(__file__),
    "..",
    "isaac.sim.mcp_extension",
    "isaac_sim_mcp_extension",
    "handlers",
)


def _handler_src():
    with open(os.path.join(HANDLERS, "graphs.py")) as f:
        return f.read()


def test_create_action_graph_accepts_inline_script_param():
    tree = ast.parse(_handler_src())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "create_action_graph":
            arg_names = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            assert "inline_script" in arg_names
            return
    raise AssertionError("create_action_graph not found")


def test_inline_script_sets_script_and_disables_usepath():
    src = _handler_src()
    # inline path builds the same OnPlaybackTick -> ScriptNode pair and sets script inline
    assert "inline_script" in src
    assert "inputs:script" in src
    assert "inputs:usePath" in src


def test_force_recompile_helper_exists_and_is_reused():
    tree = ast.parse(_handler_src())
    func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "force_recompile_scriptnode" in func_names
    # edit_action_graph delegates to the shared helper rather than inlining it
    assert _handler_src().count("force_recompile_scriptnode(") >= 2


def test_reload_script_scans_scriptnodes_by_scriptpath():
    implementations = (
        os.path.join("v6_runtime", "simulation.py"),
        "v5.py",
    )
    for fname in implementations:
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "isaac.sim.mcp_extension",
            "isaac_sim_mcp_extension",
            "adapters",
            fname,
        )
        with open(path) as f:
            src = f.read()
        assert "inputs:scriptPath" in src  # reload matches nodes by their file
        assert "force_recompile_scriptnode" in src  # and recompiles them


def test_action_graph_evaluator_defaults_to_execution():
    """A push graph evaluates every application update, ignoring the timeline.

    create_action_graph wires OnPlaybackTick -> ScriptNode, so a push evaluator
    bypasses exactly the gating it just built. Measured on 6.0.1 with the
    timeline stopped: the push graph's ScriptNode ran past 5000 ticks while an
    otherwise identical execution graph stayed frozen and only advanced during
    play. A controller left running re-commands the robot and silently discards
    the caller's set_joint_positions during the step-only debug loop.
    """
    import ast
    import os

    for rel in (
        os.path.join("isaac.sim.mcp_extension", "isaac_sim_mcp_extension", "handlers", "graphs.py"),
        os.path.join("isaac_mcp", "tools", "graphs.py"),
    ):
        path = os.path.join(os.path.dirname(__file__), "..", rel)
        with open(path) as f:
            tree = ast.parse(f.read())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_action_graph":
                defaults = {}
                args = node.args.args[-len(node.args.defaults) :] if node.args.defaults else []
                for arg, default in zip(args, node.args.defaults):
                    if isinstance(default, ast.Constant):
                        defaults[arg.arg] = default.value
                assert defaults.get("evaluator") == "execution", (
                    f"{rel}: evaluator defaults to {defaults.get('evaluator')!r}, must be 'execution'"
                )
                found = True
        assert found, f"create_action_graph not found in {rel}"
