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

"""V5 get_physics_state must read velocity from a source that actually has it."""

import ast
import os

V5 = os.path.join(
    os.path.dirname(__file__),
    "..",
    "isaac.sim.mcp_extension",
    "isaac_sim_mcp_extension",
    "adapters",
    "v5.py",
)


def _func_src(name):
    with open(V5) as f:
        text = f.read()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node)
    raise AssertionError(f"{name} not found in v5.py")


def test_velocity_not_read_from_rigidbody_transformation():
    """get_rigidbody_transformation() returns only {position, rotation, ret_val}.

    Reading velocity from it silently yields [0, 0, 0] for every body, so a
    falling object looks identical to one at rest. Verified live: a cube moving
    at 15 m/s reported zero velocity through that call.
    """
    code = "\n".join(line.split("#", 1)[0] for line in _func_src("get_physics_state").splitlines())
    assert "get_rigidbody_transformation" not in code, (
        "get_rigidbody_transformation has no velocity keys — velocity would always read zero"
    )


def test_velocity_read_from_physics_attributes():
    code = _func_src("get_physics_state")
    assert "physics:velocity" in code
    assert "physics:angularVelocity" in code


def test_angular_velocity_converted_to_radians():
    """USD stores angularVelocity in deg/s; this API reports radians elsewhere."""
    code = _func_src("get_physics_state")
    assert "radians" in code, "angular velocity must be converted from USD deg/s to rad/s"


def test_v6_does_not_use_usd_velocity_attributes():
    """V6 must keep reading the physics-tensors view, not USD attributes.

    physics:velocity is only written back by PhysX. Isaac Sim 6.0 can run the
    Newton backend, which keeps state in its own buffers, so the USD attribute
    may be stale or zero there. The tensor view is backend-neutral.
    """
    import ast
    import os

    v6_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "isaac.sim.mcp_extension",
        "isaac_sim_mcp_extension",
        "adapters",
        "v6_runtime",
        "physics.py",
    )
    with open(v6_path) as f:
        text = f.read()
    tree = ast.parse(text)
    src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_physics_state":
            src = ast.get_source_segment(text, node)
    assert src, "V6 PhysicsRuntime.get_physics_state not found"
    assert "physics:velocity" not in src, "V6/Newton must not read PhysX USD write-back attributes"
    assert "get_velocities" in src, "V6 should read velocities from the physics tensors view"


def test_v5_warns_when_usd_writeback_disabled():
    """A disabled write-back setting must be reported, not silently read as zero."""
    code = _func_src("get_physics_state")
    assert "updateVelocitiesToUsd" in code
    assert "velocity_warning" in code
