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

"""Parsing for ``isaacsim.core.version.get_version()``.

The one runtime API whose *return shape* differs across the Isaac Sim versions
this extension supports, so it gets one place to be understood:

- **6.0** — typed ``tuple[str, str, str, str, str, str, str, str]`` holding
  ``(core, prerelease, major, minor, patch, pretag, prebuild, buildtag)``, e.g.
  ``("6.0.1", "rc.7", "6", "0", "1", "rc", "7", "release.42383...")``. A missing
  VERSION file yields ``("",) * 8`` — still a tuple, never a string.
- **5.x** — a plain version string.

Both callers previously duplicated this knowledge and both got it wrong; only
the adapter-selection copy was ever corrected, which left
``get_simulation_state`` reporting ``str(tuple)`` — a Python repr — to every MCP
client. Keep the duality here, not at the call sites, so a third caller cannot
repeat it.

Deliberately free of ``carb`` / ``omni`` / ``pxr`` / ``numpy`` imports: adapter
selection runs before any adapter is chosen and must stay importable anywhere.
"""

from __future__ import annotations

import re
from typing import Any


def core_version(value: Any) -> str:
    """Return just the core version ("6.0.1") from whatever get_version() gave."""
    if isinstance(value, (list, tuple)):
        return str(value[0]).strip() if value else ""
    return str(value).strip()


def version_string(value: Any) -> str:
    """Render a human-readable version string for reporting to MCP clients.

    Produces ``"6.0.1-rc.7"`` for a prerelease build and ``"6.0.1"`` for a final
    one, matching the shape 5.x reports natively. Returns ``"unknown"`` rather
    than an empty string when the runtime could not determine a version, so the
    field stays meaningful to a reader.
    """
    core = core_version(value)
    if not core:
        return "unknown"
    if isinstance(value, (list, tuple)) and len(value) > 1:
        prerelease = str(value[1]).strip()
        if prerelease:
            return f"{core}-{prerelease}"
    return core


def major_version(value: Any) -> int:
    """Return the major version as an int, or 0 when it cannot be determined."""
    match = re.match(r"^(\d+)\.", core_version(value))
    return int(match.group(1)) if match else 0
