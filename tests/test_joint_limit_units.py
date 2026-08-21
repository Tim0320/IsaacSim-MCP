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

"""Joint limits must reach the caller in the same units as joint positions.

Values captured from a live Franka FR3 (Isaac Sim 5.1.0 and 6.0.1 report the
same raw numbers): revolute limits arrive from USD in degrees while every
position in the payload is radians, and prismatic limits are already in metres.
"""

import ast
import math
import os

from isaac_sim_mcp_extension.adapters.units import METERS, RADIANS, limit_units, normalize_limit

# Real FR3 values, straight off the wire.
FR3_JOINT1_DEG = 157.20242309570312  # == 2.7437 rad, the documented limit
FR3_JOINT1_RAD = 2.7437
FR3_FINGER_UPPER_M = 0.03999999910593033

ADAPTERS = os.path.join(
    os.path.dirname(__file__), "..", "isaac.sim.mcp_extension", "isaac_sim_mcp_extension", "adapters"
)


def test_revolute_limits_convert_to_radians():
    assert normalize_limit(FR3_JOINT1_DEG, "revolute") == math.radians(FR3_JOINT1_DEG)
    assert abs(normalize_limit(FR3_JOINT1_DEG, "revolute") - FR3_JOINT1_RAD) < 1e-4
    assert limit_units("revolute") == RADIANS


def test_prismatic_limits_are_left_alone():
    """The gripper case: converting metres as if degrees yields 0.0007 m."""
    assert normalize_limit(FR3_FINGER_UPPER_M, "prismatic") == FR3_FINGER_UPPER_M
    assert limit_units("prismatic") == METERS


def test_unauthored_limit_stays_none_rather_than_zero():
    """None must not become 0.0 — that reads as a joint pinned shut."""
    assert normalize_limit(None, "revolute") is None
    assert normalize_limit("nonsense", "revolute") is None


def test_infinite_limit_is_preserved():
    assert normalize_limit(float("inf"), "revolute") == float("inf")


def _source(filename):
    with open(os.path.join(ADAPTERS, filename)) as f:
        return f.read()


def test_neither_adapter_returns_a_raw_usd_limit():
    """Both adapters, both reporting surfaces, must go through units.py.

    get_joint_config and get_robot_info read the same USD attributes; when only
    one of them converted, the two tools disagreed about the same joint.
    """
    for filename in ("v5.py", "v6.py"):
        src = _source(filename)
        assert "from .units import" in src, f"{filename} does not use the shared units helper"
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in ("get_joint_config", "get_robot_joint_info"):
                continue
            body = ast.get_source_segment(src, node) or ""
            if "LimitAttr" not in body:
                continue
            assert "normalize_limit" in body, f"{filename}:{node.name} returns a raw USD limit"
            assert '"degrees"' not in body, f"{filename}:{node.name} still advertises degrees"
