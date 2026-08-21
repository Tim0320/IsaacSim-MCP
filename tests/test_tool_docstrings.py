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

"""Substring checks on MCP tool docstrings and the server instruction block."""

import os

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "isaac_mcp", "tools")
SERVER_PY = os.path.join(os.path.dirname(__file__), "..", "isaac_mcp", "server.py")


def _read_tool_source(filename):
    with open(os.path.join(TOOLS_DIR, filename)) as f:
        return f.read()


def _read_server_source():
    with open(SERVER_PY) as f:
        return f.read()


def test_create_object_documents_scale_multiplier():
    src = _read_tool_source("objects.py")
    # scale= is a raw multiplier of the primitive's native size
    assert "native size" in src
    assert "2 m" in src or "2m" in src  # native size of Cube/Sphere/etc
    assert "scale=0.5" in src  # worked example -> 1 m
    assert "size=" in src  # steer to size= for absolute meters


def test_step_simulation_docstring_forbids_play_first():
    src = _read_tool_source("simulation.py")
    assert "Do NOT call play_simulation" in src
    assert "frozen" in src


def test_get_simulation_state_drops_verify_running_claim():
    src = _read_tool_source("simulation.py")
    assert "verify the simulation is running before" not in src


def test_server_instructions_debug_loop_is_step_only():
    src = _read_server_source()
    assert "step-only" in src
    assert "never play" in src.lower() or "do not call play_simulation" in src.lower()


def test_stop_simulation_documents_reset():
    src = _read_tool_source("simulation.py")
    assert "spawn pose" in src
    assert "reset" in src.lower()


def test_reload_script_documents_scriptnode_mode():
    src = _read_tool_source("simulation.py")
    assert "ScriptNode" in src
    assert "recompile" in src.lower()


def test_get_isaac_logs_has_since_last_play_and_nondestructive_default():
    import ast

    src = _read_tool_source("simulation.py")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_isaac_logs":
            defaults = {a.arg: d for a, d in zip(node.args.args[-len(node.args.defaults) :], node.args.defaults)}
            assert "since_last_play" in {a.arg for a in node.args.args}
            # clear defaults to False (non-destructive)
            clear_default = defaults.get("clear")
            assert isinstance(clear_default, ast.Constant) and clear_default.value is False
            return
    raise AssertionError("get_isaac_logs tool not found")


def test_create_action_graph_has_inline_script_param():
    import ast

    src = _read_tool_source("graphs.py")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "create_action_graph":
            arg_names = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            assert "inline_script" in arg_names
            assert "script_file" in src and "recommended" in src.lower()
            return
    raise AssertionError("create_action_graph tool not found")


def test_execute_script_warns_about_live_graph():
    src = _read_tool_source("simulation.py")
    assert "ScriptNode" in src
    assert "silently" in src.lower()
    assert "stop" in src.lower()


def test_spawn_human_documents_script_companions_and_stage_preservation():
    src = _read_tool_source("humans.py")
    assert "execute_script" in src
    assert "reload_script" in src
    assert "does not reopen" in src
    assert "NavMesh" in src


def test_server_instructions_cover_contracts():
    src = _read_server_source()
    assert "resets to spawn" in src.lower() or "spawn state" in src.lower()  # stop (#8)
    assert "[PRINT]" in src  # log capture (#5)
    assert "silently" in src.lower()  # execute_script (#6)
    assert "silent" in src.lower()  # ScriptNode write failures
