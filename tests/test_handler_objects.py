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

"""Behavioural tests for the objects command handler (mock adapter)."""

from unittest.mock import MagicMock

from isaac_sim_mcp_extension.handlers import objects

# create_object must normalize non-canonical type casing before create_prim.
# Verified live against Isaac Sim 6.0.1: object_type="cube" produced a typeless
# prim (type "cube", no actual_size); "Cube" produced a real UsdGeom.Cube.


def test_create_normalizes_lowercase_type_to_canonical():
    adapter = MagicMock()
    objects.create(adapter, object_type="cube", prim_path="/World/x")

    # create_prim is called first, before any later step can fail — assert it
    # received the canonical "Cube", not "cube".
    _args, kwargs = adapter.create_prim.call_args
    assert kwargs.get("prim_type") == "Cube"


def test_create_leaves_canonical_and_unknown_types_untouched():
    for given, expected in (("Cube", "Cube"), ("SPHERE", "Sphere"), ("Xform", "Xform")):
        adapter = MagicMock()
        objects.create(adapter, object_type=given, prim_path="/World/x")
        _args, kwargs = adapter.create_prim.call_args
        assert kwargs.get("prim_type") == expected
