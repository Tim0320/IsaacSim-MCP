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

"""Verify stop() performs a physics reset (AST) — live behaviour is in smoke_test.py."""

import ast
import os

ADAPTERS = os.path.join(
    os.path.dirname(__file__),
    "..",
    "isaac.sim.mcp_extension",
    "isaac_sim_mcp_extension",
    "adapters",
)


def _stop_body_src(filename):
    with open(os.path.join(ADAPTERS, filename)) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "stop":
            return ast.get_source_segment(open(os.path.join(ADAPTERS, filename)).read(), node)
    return ""


def test_v6_stop_resets_physics():
    src = _stop_body_src("v6.py")
    assert "reset" in src.lower()
    assert "stop()" in src  # still stops the timeline first


def test_v6_arm_reset_point_lands_the_transition_before_returning():
    """The restore point must exist when _arm_reset_point returns, not a tick later.

    Arming queues timeline.play() + pause(), and timeline transitions are
    tick-driven. Without pumping once, step() returns before PhysX has a
    restore point, so a stop_simulation issued promptly finds nothing to
    restore and silently keeps the stepped pose -- measured on 6.0.1 as a cube
    stuck at z=-3.32 instead of its spawn z=2.0, deterministically, while any
    delay before the stop masked it.
    """
    import sys
    import types
    from unittest.mock import MagicMock

    calls = []

    timeline = MagicMock()
    timeline.is_stopped.return_value = True
    timeline.play.side_effect = lambda: calls.append("play")
    timeline.pause.side_effect = lambda: calls.append("pause")

    fake_timeline_mod = types.ModuleType("omni.timeline")
    fake_timeline_mod.get_timeline_interface = lambda: timeline

    app = MagicMock()
    app.update.side_effect = lambda: calls.append("update")
    fake_app_mod = types.ModuleType("omni.kit.app")
    fake_app_mod.get_app = lambda: app

    # Import before swapping: the package __init__ pulls omni.ext, which the
    # conftest stub provides. _arm_reset_point imports omni.timeline /
    # omni.kit.app at call time, so the swap only has to cover the call.
    from isaac_sim_mcp_extension.adapters.v6_runtime.physics import PhysicsRuntime

    fake_omni = types.ModuleType("omni")
    fake_kit = types.ModuleType("omni.kit")
    fake_omni.kit = fake_kit
    fake_omni.timeline = fake_timeline_mod
    fake_kit.app = fake_app_mod

    keys = ("omni", "omni.kit", "omni.kit.app", "omni.timeline")
    saved = {k: sys.modules.get(k) for k in keys}
    sys.modules["omni"] = fake_omni
    sys.modules["omni.kit"] = fake_kit
    sys.modules["omni.kit.app"] = fake_app_mod
    sys.modules["omni.timeline"] = fake_timeline_mod
    try:
        PhysicsRuntime._arm_reset_point(object.__new__(PhysicsRuntime))
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    assert calls[:2] == ["play", "pause"], f"expected play then pause, got {calls}"
    assert "update" in calls, "transition was never pumped, so it lands a tick late (or never)"
    assert calls.index("update") > calls.index("pause"), "must pump after pause, not between play and pause"


def test_v5_stop_stops_the_timeline_and_does_not_call_world_reset():
    """V5 stop() must leave the timeline STOPPED.

    timeline.stop() already restores rigid bodies / articulations to their spawn
    pose (verified live on 5.1: a cube dropped from z=2 to z=0.1 returned to
    exactly z=2 after stop_simulation). World.reset() is not needed for that and
    actively breaks stop: it re-starts the timeline on a later frame, so
    stop_simulation left the sim "playing" and step_simulation then refused to
    run, making the step-only debug loop unusable.
    """
    src = _stop_body_src("v5.py")
    # Ignore comments: only executable code counts.
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "stop()" in code
    assert "world.reset()" not in code, "World.reset() re-starts the timeline; stop must leave the sim stopped"


def test_ensure_physics_world_recovers_from_stale_world():
    """A World cached across prim deletion must not wedge every physics tool.

    clear_scene deletes the prims the cached World was built against. The next
    initialize_physics() then dereferences dead handles and raises "Accessed
    schema on invalid prim", which used to break play, step, execute_script,
    reload_script, get_joint_config and create_action_graph until Kit restarted.
    """
    import ast
    import os

    base = os.path.join(ADAPTERS, "base.py")
    with open(base) as f:
        text = f.read()
    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_ensure_physics_world":
            src = ast.get_source_segment(text, node)
    assert src, "_ensure_physics_world not found"
    assert "clear_instance" in src, "must drop the stale World and rebuild instead of propagating the error"


def test_clear_scene_invalidates_cached_world():
    import os

    scene = os.path.join(
        os.path.dirname(__file__), "..", "isaac.sim.mcp_extension", "isaac_sim_mcp_extension", "handlers", "scene.py"
    )
    with open(scene) as f:
        text = f.read()
    assert "clear_instance" in text, "clear_scene must invalidate the World it just orphaned"


def test_ensure_physics_world_never_wedges_the_tool_surface():
    """A best-effort pre-warm must not raise: it is called by nearly every tool.

    If it propagates, play, step, execute_script, reload_script, get_joint_config
    and create_action_graph all fail at once and the session is unusable until
    Kit restarts. Report and continue instead, so callers that genuinely need
    physics fail with their own specific error.
    """
    import ast
    import os

    base = os.path.join(ADAPTERS, "base.py")
    with open(base) as f:
        text = f.read()
    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_ensure_physics_world":
            src = ast.get_source_segment(text, node)
    assert src
    # The recovery path must end in a report, not a bare re-raise.
    assert "continuing without it" in src, "recovery must degrade gracefully rather than wedge every tool"


def test_recovery_resyncs_simulation_manager_scene_cache():
    """The stale handle lives in SimulationManager, not World.

    SimulationManager caches PhysxSceneAPI per prim path. Deleting a
    PhysicsScene does not reliably evict the entry, so after clear_scene the
    path can be valid again (the scene was re-created) while the cached API
    still points at the deleted prim. Reading it raises "Accessed schema on
    invalid prim". Verified live: get_physics_dt() raised before re-applying the
    schema from the live stage and returned 1/60 afterwards.
    """
    import ast
    import os

    base = os.path.join(ADAPTERS, "base.py")
    with open(base) as f:
        text = f.read()
    assert "_resync_physics_scene_cache" in text, "recovery must rebuild SimulationManager's scene cache"

    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_ensure_physics_world":
            src = ast.get_source_segment(text, node)
    assert "_resync_physics_scene_cache" in src, "resync must run on the recovery path"


def test_physics_warm_skipped_without_a_scene():
    """Initialising physics before a PhysicsScene exists poisons the session.

    The simulation view is built with no articulation data and is not rebuilt
    when a scene is added later, so SingleArticulation.initialize() fails with
    "'NoneType' object has no attribute 'link_names'" for the rest of the
    process — create_robot then silently drops joint_names/num_dof/warnings.
    Any tool can warm physics, so this depends purely on call order.
    """
    import ast
    import os

    base = os.path.join(ADAPTERS, "base.py")
    with open(base) as f:
        text = f.read()
    assert "_stage_has_physics_scene" in text
    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_ensure_physics_world":
            src = ast.get_source_segment(text, node)
    assert "_stage_has_physics_scene" in src, "must skip warming when the stage has no PhysicsScene"
