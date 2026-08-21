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

"""Joint-limit units.

USD stores a revolute joint's limits in **degrees**, while every joint position
this API reads or writes is in **radians** — ``set_joint_positions``,
``get_joint_positions`` and the drive targets the adapters convert explicitly.
Passing the USD value straight through therefore puts two different units in one
payload: measured on a Franka FR3, joint 1 reported ``limits=[-157.2, 157.2]``
next to ``actual_position=0.5``, where the real limit is ±2.7437 rad. An agent
clamping a target to those limits commands 25 revolutions.

Prismatic limits are already in stage units (metres) and must be left alone —
converting them turns a 0.04 m gripper stroke into 0.0007. That asymmetry is the
whole reason this lives in one place: the naive fix is a one-line sweep that
silently breaks every gripper.

Both adapters and both reporting surfaces (``get_joint_config`` and
``get_robot_info``) go through here, so a third caller cannot reintroduce the
split.
"""

from __future__ import annotations

import math
from typing import Any, Optional

RADIANS = "radians"
METERS = "meters"


def limit_units(joint_type: Optional[str]) -> str:
    """Unit that this joint's limits are reported in."""
    return METERS if (joint_type or "").lower() == "prismatic" else RADIANS


def normalize_limit(value: Any, joint_type: Optional[str]) -> Optional[float]:
    """Convert one raw USD limit into the unit the rest of the API speaks.

    Revolute limits are converted degrees -> radians; prismatic limits are
    returned unchanged because USD already stores them in stage units. ``None``
    (an unauthored limit) stays ``None`` rather than becoming 0.0, which would
    read as a joint pinned shut.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isinf(number) or math.isnan(number):
        # An unlimited (continuous) revolute joint authors +-inf; converting is
        # meaningless but harmless, so keep the sentinel intact for the caller.
        return number
    if limit_units(joint_type) == METERS:
        return number
    return math.radians(number)
