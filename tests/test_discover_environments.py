# MIT License
#
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

"""Environment discovery must not report thumbnails as environments.

Measured on Isaac Sim 6.0.1: list_environments returned 36 entries of which 8
were ".thumbs" folders — "grid_.thumbs", "hospital_.thumbs", "office_.thumbs"
and friends — each pointing at a "<name>.thumb.usd" preview rather than a
loadable environment. Same defect the robot walk had, fixed there in 1b6710f.
"""

from __future__ import annotations

import sys
import types

import pytest


class _Entry:
    def __init__(self, name):
        self.relative_path = name


def _fake_client(tree):
    class _Result:
        OK = "OK"

    mod = types.SimpleNamespace(Result=_Result)

    def _list(path):
        key = path.rstrip("/") + "/"
        if key not in tree:
            return ("MISSING", [])
        return (_Result.OK, [_Entry(n) for n in tree[key]])

    mod.list = _list
    return mod


def _run(monkeypatch, tree, cls_name):
    import importlib

    fake = _fake_client(tree)
    monkeypatch.setitem(sys.modules, "omni.client", fake)
    monkeypatch.setattr(sys.modules["omni"], "client", fake, raising=False)

    native = types.SimpleNamespace(get_assets_root_path=lambda: "ROOT")
    monkeypatch.setitem(sys.modules, "isaacsim.storage.native", native)
    if "isaacsim" in sys.modules:
        storage = getattr(sys.modules["isaacsim"], "storage", None)
        if storage is not None:
            monkeypatch.setattr(storage, "native", native, raising=False)

    module = "v5" if cls_name.endswith("V5") else "v6"
    mod = importlib.import_module(f"isaac_sim_mcp_extension.adapters.{module}")
    return getattr(mod, cls_name)().discover_environments()


# Each guard has to be independently necessary, or a mutation that deletes one
# is masked by the other:
#   * Grid/.cache/ holds a plain .usd  -> only the hidden-directory rule stops it
#   * Hospital/hospital.thumb.usd      -> only the .thumb.usd rule stops it
#   * Grid/.thumbs/ holds a .thumb.usd -> either rule would stop it
TREE = {
    "ROOT/Isaac/Environments/": [".hidden/", "Grid/", "Hospital/"],
    "ROOT/Isaac/Environments/.hidden/": ["secret.usd"],
    "ROOT/Isaac/Environments/Grid/": [".thumbs/", ".cache/", "default_environment.usd"],
    "ROOT/Isaac/Environments/Grid/.thumbs/": ["default_environment.thumb.usd"],
    "ROOT/Isaac/Environments/Grid/.cache/": ["scratch.usd"],
    "ROOT/Isaac/Environments/Hospital/": ["hospital.thumb.usd", "hospital.usd", "Props/"],
    "ROOT/Isaac/Environments/Hospital/Props/": ["Cube.usd"],
    "ROOT/NVIDIA/Assets/Scenes/Templates/": [],
}


@pytest.mark.parametrize("cls_name", ["IsaacAdapterV5", "IsaacAdapterV6"], ids=["v5", "v6"])
def test_thumbnail_folders_are_not_environments(cls_name):
    mp = pytest.MonkeyPatch()
    try:
        envs = _run(mp, TREE, cls_name)
    finally:
        mp.undo()

    assert not [k for k in envs if "." in k.replace("_", "")], envs
    assert not [k for k in envs if ".thumbs" in k or ".cache" in k or ".hidden" in k], envs
    assert not [v for v in envs.values() if v["asset_path"].endswith(".thumb.usd")], envs
    # A hidden directory holding a plain .usd is only caught by the hidden-dir
    # rule; a .thumb.usd beside a real asset only by the file rule.
    assert not [v for v in envs.values() if "/.cache/" in v["asset_path"]], envs
    assert envs["hospital"]["asset_path"].endswith("hospital.usd"), envs["hospital"]
    assert "grid" in envs
    assert "hospital" in envs


@pytest.mark.parametrize("cls_name", ["IsaacAdapterV5", "IsaacAdapterV6"], ids=["v5", "v6"])
def test_real_subdirectories_are_still_discovered(cls_name):
    """The hidden-directory filter must not drop legitimate nested environments."""
    mp = pytest.MonkeyPatch()
    try:
        envs = _run(mp, TREE, cls_name)
    finally:
        mp.undo()

    assert "hospital_props" in envs, envs
