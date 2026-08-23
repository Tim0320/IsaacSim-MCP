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

"""Shared pytest fixtures and runtime-stub injection.

Isaac Sim ships its own Python environment with ``carb``, ``omni``, ``pxr``,
and ``isaacsim`` packages.  When running unit tests outside that environment
these modules are unavailable.  This conftest pre-populates ``sys.modules``
with lightweight stubs so tests that import ``isaac_sim_mcp_extension.*`` do
not fail on the first ``import carb`` in the package ``__init__``.
"""

from __future__ import annotations

import sys
import types


def _make_stub(name: str, **attrs) -> types.ModuleType:
    """Create a minimal module stub with optional attributes."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _install_isaac_stubs() -> None:
    """Install carb / omni / pxr stubs into sys.modules if not already present."""
    # ── carb ─────────────────────────────────────────────────────────────────
    if "carb" not in sys.modules:
        carb_mod = _make_stub("carb")
        carb_settings = _make_stub("carb.settings")
        carb_settings.get_settings = lambda: _make_stub("_carb_settings_instance")
        carb_mod.settings = carb_settings  # type: ignore[attr-defined]
        sys.modules["carb"] = carb_mod
        sys.modules["carb.settings"] = carb_settings

    # ── omni ─────────────────────────────────────────────────────────────────
    # Build omni.* stubs.  Python resolves ``omni.ext`` as
    # ``sys.modules["omni"].ext``, so each sub-module must also be set as an
    # attribute on its parent module.
    if "omni" not in sys.modules:
        omni_mod = _make_stub("omni")
        sys.modules["omni"] = omni_mod
    else:
        omni_mod = sys.modules["omni"]

    if "omni.ext" not in sys.modules:

        class _IExt:
            def __init__(self):
                pass

        omni_ext = _make_stub("omni.ext", IExt=_IExt)
        sys.modules["omni.ext"] = omni_ext
        omni_mod.ext = omni_ext  # type: ignore[attr-defined]

    if "omni.usd" not in sys.modules:
        omni_usd = _make_stub("omni.usd")
        sys.modules["omni.usd"] = omni_usd
        omni_mod.usd = omni_usd  # type: ignore[attr-defined]

    if "omni.kit" not in sys.modules:
        omni_kit = _make_stub("omni.kit")
        sys.modules["omni.kit"] = omni_kit
        omni_mod.kit = omni_kit  # type: ignore[attr-defined]
    else:
        omni_kit = sys.modules["omni.kit"]

    if "omni.kit.commands" not in sys.modules:
        omni_kit_cmds = _make_stub("omni.kit.commands")
        sys.modules["omni.kit.commands"] = omni_kit_cmds
        omni_kit.commands = omni_kit_cmds  # type: ignore[attr-defined]

    if "omni.kit.app" not in sys.modules:
        omni_kit_app = _make_stub("omni.kit.app")
        sys.modules["omni.kit.app"] = omni_kit_app
        omni_kit.app = omni_kit_app  # type: ignore[attr-defined]

    if "omni.timeline" not in sys.modules:
        omni_timeline = _make_stub("omni.timeline")
        sys.modules["omni.timeline"] = omni_timeline
        omni_mod.timeline = omni_timeline  # type: ignore[attr-defined]

    if "omni.client" not in sys.modules:
        omni_client = _make_stub("omni.client")
        sys.modules["omni.client"] = omni_client
        omni_mod.client = omni_client  # type: ignore[attr-defined]

    # ── numpy ─────────────────────────────────────────────────────────────────
    # base.py uses numpy for type annotations in abstract method signatures.
    # Isaac Sim ships its own numpy; stub it for unit-test environments.
    if "numpy" not in sys.modules:
        np_stub = _make_stub("numpy")
        np_stub.ndarray = type("ndarray", (), {})  # type: ignore[attr-defined]
        # asarray is used by v6.py set_joint_positions to give wp.array an
        # unambiguous shape descriptor.  The stub returns its first argument
        # unchanged so the production call-path stays exercisable in tests.
        np_stub.asarray = lambda *args, **kwargs: args[0]  # type: ignore[attr-defined]
        # Dtype sentinels used as the `dtype` keyword argument in np.asarray
        # calls.  The stub asarray ignores them, but the attribute lookup must
        # not raise AttributeError.
        np_stub.float32 = "float32"  # type: ignore[attr-defined]
        np_stub.int32 = "int32"  # type: ignore[attr-defined]
        np_stub.uint8 = "uint8"  # type: ignore[attr-defined]
        np_stub.uint64 = "uint64"  # type: ignore[attr-defined]

        # v6.get_lidar_point_cloud stacks the decoded x/y/z arrays into (N, 3).
        # Enough of a stand-in to exercise that path: a list of rows with
        # .shape, .tolist() and indexing, plus an .astype that is a no-op.
        class _Rows(list):
            @property
            def shape(self):
                return (len(self), len(self[0]) if self else 0)

            def astype(self, _dtype):
                return self

            def tolist(self):
                return [list(row) for row in self]

        class _Row(list):
            def tolist(self):
                return list(self)

        def _stack(arrays, axis=0):
            if axis in (-1, 1):
                return _Rows(_Row(vals) for vals in zip(*arrays))
            return _Rows(_Row(a) for a in arrays)

        np_stub.stack = _stack  # type: ignore[attr-defined]

        def _zeros(shape, dtype=None):
            rows = shape[0] if isinstance(shape, tuple) else shape
            cols = shape[1] if isinstance(shape, tuple) and len(shape) > 1 else 0
            return _Rows(_Row([0] * cols) for _ in range(rows))

        np_stub.zeros = _zeros  # type: ignore[attr-defined]
        sys.modules["numpy"] = np_stub

    # ── pxr ──────────────────────────────────────────────────────────────────
    if "pxr" not in sys.modules:
        sys.modules["pxr"] = _make_stub("pxr")

    for pxr_sub in ("Usd", "UsdGeom", "UsdPhysics", "UsdShade", "Gf", "Sdf", "Tf"):
        key = f"pxr.{pxr_sub}"
        if key not in sys.modules:
            sys.modules[key] = _make_stub(key)


# Install stubs at collection time so that any test module importing
# ``isaac_sim_mcp_extension`` does not get an ImportError.
_install_isaac_stubs()
