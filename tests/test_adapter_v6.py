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

"""Tests for the V6 adapter and version-aware dispatcher."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture
def fake_v5(monkeypatch):
    mod = types.ModuleType("isaac_sim_mcp_extension.adapters.v5")

    class _V5:
        pass

    mod.IsaacAdapterV5 = _V5
    monkeypatch.setitem(sys.modules, "isaac_sim_mcp_extension.adapters.v5", mod)
    return _V5


@pytest.fixture
def fake_v6(monkeypatch):
    mod = types.ModuleType("isaac_sim_mcp_extension.adapters.v6")

    class _V6:
        pass

    mod.IsaacAdapterV6 = _V6
    monkeypatch.setitem(sys.modules, "isaac_sim_mcp_extension.adapters.v6", mod)
    return _V6


def test_get_adapter_returns_v5_when_version_5(fake_v5, fake_v6):
    from isaac_sim_mcp_extension.adapters import get_adapter

    with patch("isaac_sim_mcp_extension.adapters._detect_isaacsim_major_version", return_value=5):
        adapter = get_adapter()
    assert isinstance(adapter, fake_v5)


def test_get_adapter_returns_v6_when_version_6(fake_v5, fake_v6):
    from isaac_sim_mcp_extension.adapters import get_adapter

    with patch("isaac_sim_mcp_extension.adapters._detect_isaacsim_major_version", return_value=6):
        adapter = get_adapter()
    assert isinstance(adapter, fake_v6)


def test_get_adapter_falls_back_to_v5_when_detection_fails(fake_v5, fake_v6):
    from isaac_sim_mcp_extension.adapters import get_adapter

    with patch("isaac_sim_mcp_extension.adapters._detect_isaacsim_major_version", return_value=0):
        adapter = get_adapter()
    assert isinstance(adapter, fake_v5)


def test_detect_version_reads_isaacsim_core_version(monkeypatch):
    """When isaacsim.core.version.get_version returns a 6.x string, detection returns 6."""
    fake_version_mod = types.ModuleType("isaacsim.core.version")
    fake_version_mod.get_version = lambda: "6.0.0-rc.59+release.41464.5f2772bc.gl"
    fake_core_mod = types.ModuleType("isaacsim.core")
    fake_isaac_mod = types.ModuleType("isaacsim")
    monkeypatch.setitem(sys.modules, "isaacsim", fake_isaac_mod)
    monkeypatch.setitem(sys.modules, "isaacsim.core", fake_core_mod)
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", fake_version_mod)

    # Module already loaded in earlier tests; force a fresh import path
    import importlib

    import isaac_sim_mcp_extension.adapters as adapters_mod

    importlib.reload(adapters_mod)
    assert adapters_mod._detect_isaacsim_major_version() == 6


def test_detect_version_returns_zero_on_failure(monkeypatch):
    """When neither isaacsim.core.version nor a VERSION file is reachable, returns 0."""
    monkeypatch.delenv("ISAAC_PATH", raising=False)
    monkeypatch.delenv("ISAACSIM_PATH", raising=False)
    for name in list(sys.modules):
        if name.startswith("isaacsim"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    import importlib

    import isaac_sim_mcp_extension.adapters as adapters_mod

    importlib.reload(adapters_mod)
    assert adapters_mod._detect_isaacsim_major_version() == 0


def test_v6_create_prim_calls_experimental_define_prim(monkeypatch):
    """V6.create_prim must call isaacsim.core.experimental.utils.stage.define_prim."""
    define_prim_mock = MagicMock(return_value="prim-handle")
    fake_stage_mod = types.ModuleType("isaacsim.core.experimental.utils.stage")
    fake_stage_mod.define_prim = define_prim_mock
    fake_stage_mod.add_reference_to_stage = MagicMock()
    fake_stage_mod.delete_prim = MagicMock()
    for name in ("isaacsim", "isaacsim.core", "isaacsim.core.experimental", "isaacsim.core.experimental.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.utils.stage", fake_stage_mod)

    # SimulationManager mock for __init__
    fake_sm_mod = types.ModuleType("isaacsim.core.simulation_manager")

    class _SM:
        @classmethod
        def get_active_physics_engine(cls):
            return "physx"

    fake_sm_mod.SimulationManager = _SM
    monkeypatch.setitem(sys.modules, "isaacsim.core.simulation_manager", fake_sm_mod)

    fake_version_mod = types.ModuleType("isaacsim.core.version")
    fake_version_mod.get_version = lambda: "6.0.0"
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", fake_version_mod)

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    result = adapter.create_prim("/World/Foo", "Xform")
    define_prim_mock.assert_called_once_with("/World/Foo", type_name="Xform")
    assert result == "prim-handle"


def test_v6_ensure_physics_world_calls_simulation_manager(monkeypatch):
    """V6._ensure_physics_world must use SimulationManager, not World."""
    sm_calls = []

    class _SM:
        @classmethod
        def get_active_physics_engine(cls):
            return "newton"

        @classmethod
        def setup_simulation(cls, dt=None, device=None):
            sm_calls.append(("setup_simulation", dt))

        @classmethod
        def initialize_physics(cls):
            sm_calls.append(("initialize_physics",))

    fake_sm_mod = types.ModuleType("isaacsim.core.simulation_manager")
    fake_sm_mod.SimulationManager = _SM
    monkeypatch.setitem(sys.modules, "isaacsim.core.simulation_manager", fake_sm_mod)
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.0"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    # Physics warming is guarded on a live stage (see
    # test_v6_never_warms_physics_without_a_stage), so provide one.
    monkeypatch.setattr(adapter, "get_stage", lambda: object())
    adapter._ensure_physics_world()
    assert ("setup_simulation", 1.0 / 60.0) in sm_calls
    assert ("initialize_physics",) in sm_calls
    # And confirm we picked up the engine
    assert adapter._engine == "newton"


def test_v6_set_joint_positions_calls_set_dof_position_targets(monkeypatch):
    """V6.set_joint_positions must build an Articulation and forward to set_dof_position_targets."""
    captured = {}

    class _Articulation:
        def __init__(self, paths):
            captured["paths"] = paths

        def is_physics_tensor_entity_initialized(self):
            return True

        def set_dof_position_targets(self, positions, dof_indices=None):
            captured["positions"] = positions
            captured["dof_indices"] = dof_indices

        def get_dof_indices(self, names):
            captured["dof_indices_names"] = names

    fake_prims_mod = types.ModuleType("isaacsim.core.experimental.prims")
    fake_prims_mod.Articulation = _Articulation

    fake_warp_mod = types.ModuleType("warp")
    fake_warp_mod.array = lambda data, dtype=None: list(data)
    fake_warp_mod.float32 = "float32"

    monkeypatch.setitem(sys.modules, "warp", fake_warp_mod)
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental", types.ModuleType("isaacsim.core.experimental"))
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.prims", fake_prims_mod)
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        types.SimpleNamespace(
            SimulationManager=type(
                "SM",
                (),
                {
                    "get_active_physics_engine": classmethod(lambda cls: "physx"),
                    "setup_simulation": classmethod(lambda cls, dt=None, device=None: None),
                    "initialize_physics": classmethod(lambda cls: None),
                },
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.0"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    adapter.set_joint_positions("/World/Franka", [0.1, 0.2, 0.3])
    assert captured["paths"] == ["/World/Franka"]
    assert list(captured["positions"][0]) == [0.1, 0.2, 0.3]


def test_v6_joint_command_uses_dof_subset_for_all_modes(monkeypatch):
    calls = []
    allocations = []

    class _Articulation:
        dof_names = ["j0", "j1", "j2"]
        _device = "cuda:0"

        def is_physics_tensor_entity_valid(self):
            return True

        def set_dof_position_targets(self, values, dof_indices=None):
            calls.append(("position", values, dof_indices))

        def set_dof_velocity_targets(self, values, dof_indices=None):
            calls.append(("velocity", values, dof_indices))

        def set_dof_efforts(self, values, dof_indices=None):
            calls.append(("effort", values, dof_indices))

    fake_warp_mod = types.ModuleType("warp")
    def fake_array(data, dtype=None, device=None):
        allocations.append((dtype, device))
        return list(data)

    fake_warp_mod.array = fake_array
    fake_warp_mod.float32 = "float32"
    fake_warp_mod.int32 = "int32"
    monkeypatch.setitem(sys.modules, "warp", fake_warp_mod)

    from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6

    adapter = object.__new__(IsaacAdapterV6)
    adapter._ensure_physics_world = lambda: None
    adapter._new_articulation = lambda _path: _Articulation()

    for mode in ("position", "velocity", "effort"):
        adapter.set_joint_command("/World/Robot", mode, [1.0, 2.0], [0, 2])

    assert [call[0] for call in calls] == ["position", "velocity", "effort"]
    assert all(list(call[1][0]) == [1.0, 2.0] for call in calls)
    assert all(list(call[2]) == [0, 2] for call in calls)
    assert allocations and all(device == "cuda:0" for _dtype, device in allocations)


def test_v6_holonomic_accepts_experimental_sequence_and_reorders_names(monkeypatch):
    class _Setup:
        def __init__(self, robot_prim_path, com_prim_path):
            assert robot_prim_path == "/World/Kaya"
            assert com_prim_path == "/World/Kaya/base_link/control_offset"

        def get_holonomic_controller_params(self):
            return [0.1] * 3, np.zeros((3, 3)), np.zeros((3, 4)), [45.0] * 3, [1, 0, 0], [0, 0, 1]

        def get_articulation_controller_params(self):
            return ["axle_2_joint", "axle_0_joint", "axle_1_joint"]

    class _Controller:
        def __init__(self, **_kwargs):
            pass

        def forward(self, command):
            assert list(command) == [0.2, -0.1, 0.3]
            return [10.0, 20.0, 30.0]

    controllers_mod = types.ModuleType("isaacsim.robot.experimental.wheeled_robots.controllers")
    controllers_mod.HolonomicController = _Controller
    robots_mod = types.ModuleType("isaacsim.robot.experimental.wheeled_robots.robots")
    robots_mod.HolonomicRobotUsdSetup = _Setup
    for name in (
        "isaacsim.robot",
        "isaacsim.robot.experimental",
        "isaacsim.robot.experimental.wheeled_robots",
    ):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, controllers_mod.__name__, controllers_mod)
    monkeypatch.setitem(sys.modules, robots_mod.__name__, robots_mod)

    class _Prim:
        def IsValid(self):
            return True

    from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6

    adapter = object.__new__(IsaacAdapterV6)
    adapter.get_stage = lambda: types.SimpleNamespace(GetPrimAtPath=lambda _path: _Prim())
    result = adapter.compute_holonomic_wheel_velocities(
        "/World/Kaya",
        "/World/Kaya/base_link/control_offset",
        [0.2, -0.1, 0.3],
        ["axle_0_joint", "axle_1_joint", "axle_2_joint"],
    )
    assert result == [20.0, 30.0, 10.0]


def test_v6_joint_state_reads_measured_and_target_arrays():
    class _DofType:
        def __init__(self, name):
            self.name = name

        def __str__(self):
            return f"DofType.{self.name}"

    class _Articulation:
        dof_names = ["shoulder", "finger"]
        dof_types = [_DofType("Rotation"), _DofType("Translation")]

        def is_physics_tensor_entity_valid(self):
            return True

        def get_dof_positions(self):
            return [[0.1, 0.02]]

        def get_dof_velocities(self):
            return [[0.2, 0.03]]

        def get_dof_projected_joint_forces(self):
            return [[1.5, 2.5]]

        def get_dof_position_targets(self):
            return [[0.15, 0.025]]

        def get_dof_velocity_targets(self):
            return [[0.25, 0.035]]

        def get_dof_efforts(self):
            return [[1.0, 2.0]]

    from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6

    adapter = object.__new__(IsaacAdapterV6)
    adapter._ensure_physics_world = lambda: None
    adapter._new_articulation = lambda _path: _Articulation()

    state = adapter.get_joint_state("/World/Robot")

    assert state == {
        "prim_path": "/World/Robot",
        "joint_names": ["shoulder", "finger"],
        "joint_types": ["revolute", "prismatic"],
        "positions": [0.1, 0.02],
        "velocities": [0.2, 0.03],
        "efforts": [1.5, 2.5],
        "position_targets": [0.15, 0.025],
        "velocity_targets": [0.25, 0.035],
        "effort_targets": [1.0, 2.0],
    }


def test_v6_runtime_articulation_rebinds_stale_preplay_cache(monkeypatch):
    created = []

    class _Articulation:
        def __init__(self, paths):
            self.paths = paths
            self.sequence = len(created)
            created.append(self)

        def is_physics_tensor_entity_valid(self):
            return self.sequence > 0

    fake_prims_mod = types.ModuleType("isaacsim.core.experimental.prims")
    fake_prims_mod.Articulation = _Articulation
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental", types.ModuleType("isaacsim.core.experimental"))
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.prims", fake_prims_mod)

    from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6

    adapter = object.__new__(IsaacAdapterV6)
    adapter._articulations = {}
    stale = adapter._new_articulation("/World/Robot")

    rebound = adapter._runtime_articulation("/World/Robot")

    assert rebound is not stale
    assert rebound.sequence == 1
    assert adapter._articulations["/World/Robot"] is rebound


def test_v6_unknown_dof_type_is_not_mislabeled_as_revolute():
    from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6

    assert IsaacAdapterV6._joint_type_name("DofType.Invalid") == "unknown"


def test_v6_get_simulation_state_includes_engine_and_version(monkeypatch):
    fake_timeline_iface = MagicMock()
    fake_timeline_iface.is_playing.return_value = False
    fake_timeline_iface.is_stopped.return_value = True
    fake_timeline_iface.get_current_time.return_value = 0.0
    fake_timeline_mod = types.ModuleType("omni.timeline")
    fake_timeline_mod.get_timeline_interface = lambda: fake_timeline_iface
    fake_omni_mod = types.ModuleType("omni")
    monkeypatch.setitem(sys.modules, "omni", fake_omni_mod)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline_mod)
    fake_omni_mod.timeline = fake_timeline_mod

    class _Stage:
        def Traverse(self):
            return []

    fake_usd_mod = types.ModuleType("omni.usd")
    fake_usd_mod.get_context = lambda: types.SimpleNamespace(get_stage=lambda: _Stage())
    monkeypatch.setitem(sys.modules, "omni.usd", fake_usd_mod)
    fake_omni_mod.usd = fake_usd_mod

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        types.SimpleNamespace(
            SimulationManager=type(
                "SM",
                (),
                {
                    "get_active_physics_engine": classmethod(lambda cls: "newton"),
                },
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.0-rc.59"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    state = adapter.get_simulation_state()
    assert state["engine"] == "newton"
    assert state["isaacsim_version"] == "6.0.0-rc.59"
    assert state["timeline_state"] == "stopped"


# The real isaacsim.core.version.get_version() on 6.0 is typed
# `-> tuple[str, str, str, str, str, str, str, str]` and returns
# (core, prerelease, major, minor, patch, pretag, prebuild, buildtag).
# Captured verbatim from a live Isaac Sim 6.0.1 runtime. Every other fake in
# this file returns a *string*, which is the 5.x shape the 6.x runtime never
# produces — so nothing here exercised the shape the adapter actually receives.
REAL_V6_VERSION_TUPLE = ("6.0.1", "rc.7", "6", "0", "1", "rc", "7", "release.42383.32955d8d.gl")


def test_detect_version_handles_real_6x_version_tuple(monkeypatch):
    """Detection must read the major from the tuple 6.0 actually returns."""
    fake_version_mod = types.ModuleType("isaacsim.core.version")
    fake_version_mod.get_version = lambda: REAL_V6_VERSION_TUPLE
    monkeypatch.setitem(sys.modules, "isaacsim", types.ModuleType("isaacsim"))
    monkeypatch.setitem(sys.modules, "isaacsim.core", types.ModuleType("isaacsim.core"))
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", fake_version_mod)

    import importlib

    import isaac_sim_mcp_extension.adapters as adapters_mod

    importlib.reload(adapters_mod)
    assert adapters_mod._detect_isaacsim_major_version() == 6


def test_v6_reports_a_human_version_from_the_real_tuple(monkeypatch):
    """isaacsim_version must be a version string, not the repr of a tuple.

    str(get_version()) yields "('6.0.1', 'rc.7', ...)" — a Python repr that
    leaks to every MCP client through get_simulation_state.
    """
    fake_timeline_iface = MagicMock()
    fake_timeline_iface.is_playing.return_value = False
    fake_timeline_iface.is_stopped.return_value = True
    fake_timeline_iface.get_current_time.return_value = 0.0
    fake_timeline_mod = types.ModuleType("omni.timeline")
    fake_timeline_mod.get_timeline_interface = lambda: fake_timeline_iface
    fake_omni_mod = types.ModuleType("omni")
    monkeypatch.setitem(sys.modules, "omni", fake_omni_mod)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline_mod)
    fake_omni_mod.timeline = fake_timeline_mod

    class _Stage:
        def Traverse(self):
            return []

    fake_usd_mod = types.ModuleType("omni.usd")
    fake_usd_mod.get_context = lambda: types.SimpleNamespace(get_stage=lambda: _Stage())
    monkeypatch.setitem(sys.modules, "omni.usd", fake_usd_mod)
    fake_omni_mod.usd = fake_usd_mod

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        types.SimpleNamespace(
            SimulationManager=type("SM", (), {"get_active_physics_engine": classmethod(lambda cls: "physx")})
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.version",
        types.SimpleNamespace(get_version=lambda: REAL_V6_VERSION_TUPLE),
    )

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    state = adapter.get_simulation_state()
    assert state["isaacsim_version"] == "6.0.1-rc.7"


def test_v6_engine_is_read_live_not_cached_at_construction(monkeypatch):
    """The engine must track SimulationManager, not a snapshot from __init__.

    Under isaac-sim.newton.sh the Newton backend registers ~2.7s AFTER this
    extension starts (measured on 6.0.1: mcp_extension at 3.978s,
    isaacsim.physics.newton at 6.649s), so at construction time the manager
    still reports the "physx" default. Caching there pins the adapter to the
    wrong backend for the whole session.
    """
    engine = {"value": "physx"}

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        types.SimpleNamespace(
            SimulationManager=type(
                "SM",
                (),
                {"get_active_physics_engine": classmethod(lambda cls: engine["value"])},
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.1"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    assert adapter._engine == "physx"

    # Newton registers late in the boot sequence.
    engine["value"] = "newton"
    assert adapter._engine == "newton"


def test_v6_engine_reports_unknown_when_simulation_manager_is_unavailable(monkeypatch):
    """A missing/failing SimulationManager degrades to "unknown", never raises."""

    class _Broken:
        @classmethod
        def get_active_physics_engine(cls):
            raise RuntimeError("no manager")

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        types.SimpleNamespace(SimulationManager=_Broken),
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.1"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    assert v6_mod.IsaacAdapterV6()._engine == "unknown"


def test_v6_import_urdf_uses_urdf_importer_class(monkeypatch, tmp_path):
    urdf_file = tmp_path / "robot.urdf"
    urdf_file.write_text("<robot name='r'/>")

    captured = {}

    class _Config:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class _Importer:
        def __init__(self, config):
            captured["importer_config"] = config

        def import_urdf(self, config=None):
            # 6.0: URDFImporter.import_urdf() converts the .urdf to a .usd on
            # disk and returns that generated USD path.
            return "/generated/robot.usd"

    def _fake_add_reference_to_stage(usd_path, prim_path):
        captured["add_reference"] = (usd_path, prim_path)
        return prim_path

    fake_urdf_mod = types.ModuleType("isaacsim.asset.importer.urdf")
    fake_urdf_mod.URDFImporter = _Importer
    fake_urdf_mod.URDFImporterConfig = _Config
    fake_stage_mod = types.ModuleType("isaacsim.core.experimental.utils.stage")
    fake_stage_mod.add_reference_to_stage = _fake_add_reference_to_stage
    monkeypatch.setitem(sys.modules, "isaacsim", types.ModuleType("isaacsim"))
    monkeypatch.setitem(sys.modules, "isaacsim.asset", types.ModuleType("isaacsim.asset"))
    monkeypatch.setitem(sys.modules, "isaacsim.asset.importer", types.ModuleType("isaacsim.asset.importer"))
    monkeypatch.setitem(sys.modules, "isaacsim.asset.importer.urdf", fake_urdf_mod)
    monkeypatch.setitem(sys.modules, "isaacsim.core", types.ModuleType("isaacsim.core"))
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental", types.ModuleType("isaacsim.core.experimental"))
    monkeypatch.setitem(
        sys.modules, "isaacsim.core.experimental.utils", types.ModuleType("isaacsim.core.experimental.utils")
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.utils.stage", fake_stage_mod)
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        types.SimpleNamespace(
            SimulationManager=type(
                "SM",
                (),
                {
                    "get_active_physics_engine": classmethod(lambda cls: "physx"),
                },
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.0"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    adapter = v6_mod.IsaacAdapterV6()
    result = adapter.import_urdf(str(urdf_file), prim_path="/World/robot")
    # 6.0 two-step API: config carries urdf_path + usd_path (the 5.x dest_path
    # kwarg is gone), then the generated USD is referenced into the live stage.
    assert captured["config"]["urdf_path"] == str(urdf_file)
    assert "usd_path" in captured["config"]
    assert "dest_path" not in captured["config"]
    assert captured["add_reference"] == ("/generated/robot.usd", "/World/robot")
    assert result == "/World/robot"


def test_get_simulation_state_detects_physics_scene_with_isa():
    """physics_dt detection must use IsA (typed schema), not HasAPI, on both adapters.

    Verified live against Isaac Sim 6.0.1: HasAPI(UsdPhysics.Scene) returns False
    on a PhysicsScene prim, so physics_dt stayed at 1/60 regardless of the scene's
    timeStepsPerSecond; IsA(UsdPhysics.Scene) matches correctly.
    """
    import os

    adapters_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "isaac.sim.mcp_extension",
        "isaac_sim_mcp_extension",
        "adapters",
    )
    for fname in ("v5.py", "v6.py"):
        with open(os.path.join(adapters_dir, fname)) as f:
            src = f.read()
        assert "IsA(UsdPhysics.Scene)" in src, f"{fname}: physics-scene check must use IsA"
        assert "HasAPI(UsdPhysics.Scene)" not in src, f"{fname}: HasAPI never matches a typed schema"


def _v6_with_stub_simulation_manager(monkeypatch, calls):
    """Build a V6 adapter whose SimulationManager records calls instead of running."""

    class _SM:
        @classmethod
        def get_active_physics_engine(cls):
            return "physx"

        @classmethod
        def _cleanup_stale_physics_scenes(cls):
            calls.append("cleanup")

        @classmethod
        def setup_simulation(cls, dt=None, device=None):
            calls.append("setup_simulation")

        @classmethod
        def initialize_physics(cls):
            calls.append("initialize_physics")

    monkeypatch.setitem(sys.modules, "isaacsim.core.simulation_manager", types.SimpleNamespace(SimulationManager=_SM))
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.1"))

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    return v6_mod.IsaacAdapterV6()


def test_v6_never_warms_physics_without_a_stage(monkeypatch):
    """setup_simulation() on a null stage is a native abort that kills Kit.

    Kit accepts MCP commands ~2.86s before it creates the USD stage (measured on
    6.0.1). setup_simulation() dereferences that stage in C++, so calling it in
    that window raises no Python exception — it prints
    "[Fatal] [omni.usd] attempted member lookup on NULL TfWeakPtr<UsdStage>" and
    aborts the process. It must never be reached without a stage.
    """
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "get_stage", lambda: None)

    adapter._ensure_physics_world()

    assert calls == [], f"physics was warmed with no stage: {calls}"


def test_v6_warms_physics_once_a_stage_exists(monkeypatch):
    """The guard must not disable normal warming — only the no-stage case."""
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "get_stage", lambda: object())

    adapter._ensure_physics_world()

    assert "setup_simulation" in calls
    assert "initialize_physics" in calls


def _install_fake_omni(monkeypatch, timeline, app):
    """Publish fake omni.timeline / omni.kit.app.

    `import omni.timeline` reads the attribute off the parent `omni` package, so
    patching sys.modules alone is not enough with conftest's omni stub.
    """
    fake_timeline = types.ModuleType("omni.timeline")
    fake_timeline.get_timeline_interface = lambda: timeline
    fake_app_mod = types.ModuleType("omni.kit.app")
    fake_app_mod.get_app = lambda: app
    fake_kit = types.ModuleType("omni.kit")
    fake_kit.app = fake_app_mod
    fake_omni = types.ModuleType("omni")
    fake_omni.timeline = fake_timeline
    fake_omni.kit = fake_kit
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline)
    monkeypatch.setitem(sys.modules, "omni.kit", fake_kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", fake_app_mod)


def test_v6_step_must_not_pump_the_kit_event_loop(monkeypatch):
    """step must not call omni.kit.app.update().

    Handlers run as an asyncio Task on kit's main loop (see
    SocketServer._dispatch_command). Pumping the loop from inside that Task
    raises "Cannot enter into task <other> while another task <this handler> is
    being executed" for every other pending kit task — property window,
    viewport, USD cache listener, throttling, HTTP server — and invalidates the
    physics tensor view, after which get_velocities fails with "Simulation view
    object is invalidated". Verified on 6.0.1.

    The errors never surface to the caller: asyncio logs them and step returns
    a plausible-looking result, so only the kit console reveals the damage.
    """
    import ast
    import os

    src_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "isaac.sim.mcp_extension",
        "isaac_sim_mcp_extension",
        "adapters",
        "v6.py",
    )
    with open(src_path) as f:
        text = f.read()
    tree = ast.parse(text)
    step_src = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "step":
            step_src = ast.get_source_segment(text, node)
            break
    assert step_src is not None, "v6.step not found"
    code = "\n".join(line.split("#", 1)[0] for line in step_src.splitlines())
    assert "get_app().update()" not in code, "v6.step must not pump the kit event loop"
    assert "SimulationManager.step" in code


def test_v6_stop_does_not_call_a_nonexistent_reset_api():
    """SimulationManager.reset_simulation() does not exist on 6.0.1.

    It used to be called inside a bare except, so every stop_simulation raised
    AttributeError internally, swallowed it, and reported success.
    """
    import os

    src = os.path.join(
        os.path.dirname(__file__),
        "..",
        "isaac.sim.mcp_extension",
        "isaac_sim_mcp_extension",
        "adapters",
        "v6.py",
    )
    with open(src) as f:
        body = f.read()
    call_sites = [ln for ln in body.splitlines() if "reset_simulation()" in ln and not ln.strip().startswith("#")]
    assert call_sites == [], f"v6 calls a non-existent API: {call_sites}"


def test_v6_current_time_uses_the_physics_clock_not_the_timeline(monkeypatch):
    """current_time must come from SimulationManager.get_simulation_time().

    V6 advances physics with SimulationManager.step(), which never runs the
    timeline, so timeline.get_current_time() reports 0.0 for the whole step-only
    debug loop. The physics clock tracks each step and resets on stop.
    """

    class _Timeline:
        def is_playing(self):
            return False

        def is_stopped(self):
            return True

        def get_current_time(self):
            return 0.0  # timeline never advanced — the bug being fixed

    class _Stage:
        def Traverse(self):
            return []

    class _SM:
        @classmethod
        def get_active_physics_engine(cls):
            return "physx"

        @classmethod
        def get_simulation_time(cls):
            return 1.25

    monkeypatch.setitem(sys.modules, "isaacsim.core.simulation_manager", types.SimpleNamespace(SimulationManager=_SM))
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.1"))

    fake_timeline = types.ModuleType("omni.timeline")
    fake_timeline.get_timeline_interface = lambda: _Timeline()
    fake_usd = types.ModuleType("omni.usd")
    fake_usd.get_context = lambda: types.SimpleNamespace(get_stage=lambda: _Stage())
    fake_omni = types.ModuleType("omni")
    fake_omni.timeline = fake_timeline
    fake_omni.usd = fake_usd
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline)
    monkeypatch.setitem(sys.modules, "omni.usd", fake_usd)

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    state = v6_mod.IsaacAdapterV6().get_simulation_state()

    assert state["current_time"] == 1.25, "current_time must track the physics clock"


class _ArmTimeline:
    """Timeline whose transitions are tick-driven, like kit's."""

    def __init__(self, stopped=True):
        self._stopped = stopped
        self.calls = []

    def is_stopped(self):
        return self._stopped

    def is_playing(self):
        return False

    def play(self):
        self.calls.append("play")

    def pause(self):
        self.calls.append("pause")


def _v6_for_arming(monkeypatch, timeline):
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "get_stage", lambda: object())
    fake_timeline = types.ModuleType("omni.timeline")
    fake_timeline.get_timeline_interface = lambda: timeline
    fake_omni = types.ModuleType("omni")
    fake_omni.timeline = fake_timeline
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline)
    return adapter


def test_v6_step_arms_a_reset_point_when_the_timeline_is_stopped(monkeypatch):
    """Without a Play, PhysX has no restore point and stop_simulation does nothing.

    play() and pause() are queued together so the timeline ends up paused without
    a single frame running free — verified on 6.0.1, where a cube left at z=50.0
    was still at exactly 50.0 afterwards.
    """
    timeline = _ArmTimeline(stopped=True)
    adapter = _v6_for_arming(monkeypatch, timeline)

    adapter._arm_reset_point()

    assert timeline.calls == ["play", "pause"], "must queue play+pause to arm the restore point"


def test_v6_does_not_disturb_a_timeline_that_is_already_running(monkeypatch):
    """Re-arming mid-run would move the restore point and interrupt a real Play."""
    timeline = _ArmTimeline(stopped=False)
    adapter = _v6_for_arming(monkeypatch, timeline)

    adapter._arm_reset_point()

    assert timeline.calls == []


def test_v6_arming_failure_never_blocks_stepping(monkeypatch):
    """Losing the ability to reset must not cost the caller their step."""

    class _Broken:
        def is_stopped(self):
            raise RuntimeError("timeline unavailable")

    adapter = _v6_for_arming(monkeypatch, _Broken())
    adapter._arm_reset_point()  # must not raise


class _FakePrim:
    def __init__(self, schemas=None, valid=True):
        self._schemas = list(schemas or [])
        self._valid = valid
        self.applied = []

    def IsValid(self):
        return self._valid

    def GetAppliedSchemas(self):
        return list(self._schemas)

    def ApplyAPI(self, name):
        self.applied.append(name)
        self._schemas.append(name)
        return True


def _v6_with_stage_prim(monkeypatch, prim):
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "get_stage", lambda: types.SimpleNamespace(GetPrimAtPath=lambda _p: prim))
    return adapter


def test_v6_applies_the_sensor_schema_to_an_existing_camera_prim(monkeypatch):
    """RtxCamera adopts an existing prim without applying OmniSensorAPI.

    Pointing create_camera at a path that already holds a plain UsdGeom.Camera —
    which imported USD scenes routinely ship — failed on 6.0.1 with "Prim at
    <path> does not have the 'OmniSensorAPI' schema", while the same call on a
    fresh path succeeded.
    """
    prim = _FakePrim(schemas=[])  # a plain Camera: no applied API schemas
    adapter = _v6_with_stage_prim(monkeypatch, prim)

    adapter._apply_sensor_schema("/World/Cam")

    assert prim.applied == ["OmniSensorAPI"]


def test_v6_does_not_reapply_the_sensor_schema(monkeypatch):
    """A healthy RTX camera must be left untouched."""
    prim = _FakePrim(schemas=["OmniSensorAPI", "OmniRtxCameraExposureAPI_1"])
    adapter = _v6_with_stage_prim(monkeypatch, prim)

    adapter._apply_sensor_schema("/World/Cam")

    assert prim.applied == []


def test_v6_sensor_schema_noop_when_the_prim_does_not_exist(monkeypatch):
    """A path with no prim needs nothing — RtxCamera creates it correctly."""
    prim = _FakePrim(schemas=[], valid=False)
    adapter = _v6_with_stage_prim(monkeypatch, prim)

    adapter._apply_sensor_schema("/World/Cam")

    assert prim.applied == []


def test_v6_camera_output_attaches_annotator_once_and_reuses_sensor(monkeypatch):
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)

    class _Data:
        def numpy(self):
            return "typed-array"

    class _Sensor:
        def __init__(self):
            self._annotators = {"rgb": object()}
            self.attached = []

        def attach_annotators(self, annotator):
            self.attached.append(annotator)
            self._annotators[annotator] = object()

        def get_data(self, annotator):
            return _Data(), {"source": annotator}

    rtx = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx.CameraSensor = MagicMock()
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx)
    sensor = _Sensor()
    adapter._camera_sensors["/World/Cam"] = sensor

    first = adapter.capture_camera_output("/World/Cam", "normals")
    second = adapter.capture_camera_output("/World/Cam", "normals")

    assert first == ("typed-array", {"source": "normals"})
    assert second == first
    assert sensor.attached == ["normals"]
    rtx.CameraSensor.assert_not_called()


def test_v6_create_camera_registers_all_task_1_2_annotators_before_play(monkeypatch):
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "_apply_sensor_schema", lambda _path: None)
    sensor_factory = MagicMock(return_value=object())
    rtx = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx.RtxCamera = MagicMock(return_value=object())
    rtx.CameraSensor = sensor_factory
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx)

    adapter.create_camera("/World/Cam", resolution=(64, 48))

    from isaac_sim_mcp_extension.adapters.v6 import CAMERA_ANNOTATORS

    sensor_factory.assert_called_once_with(
        path="/World/Cam",
        resolution=(48, 64),
        annotators=CAMERA_ANNOTATORS,
    )
    assert CAMERA_ANNOTATORS == [
        "rgb",
        "distance_to_camera",
        "distance_to_image_plane",
        "semantic_segmentation",
        "instance_segmentation",
        "instance_id_segmentation",
        "normals",
        "motion_vectors",
    ]


def test_v6_recreating_camera_releases_the_previous_runtime(monkeypatch):
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "_apply_sensor_schema", lambda _path: None)

    class _OldSensor:
        def __init__(self):
            self._annotators = {}
            self._writers = {}
            self._hydra_texture = None
            self.invalidated = 0

        def _invalidate_sensor(self):
            self.invalidated += 1

    old_sensor = _OldSensor()
    adapter._camera_sensors["/World/Cam"] = old_sensor
    rtx = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx.RtxCamera = MagicMock(return_value=object())
    rtx.CameraSensor = MagicMock(return_value=object())
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx)

    adapter.create_camera("/World/Cam", resolution=(64, 48))

    assert old_sensor.invalidated == 1
    assert adapter._camera_sensors["/World/Cam"] is rtx.CameraSensor.return_value


def test_v6_camera_calibration_reads_intrinsics_extrinsics_and_units(monkeypatch):
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)

    class _Attr:
        def __init__(self, value):
            self.value = value

        def Get(self):
            return self.value

    class _Prim:
        def IsValid(self):
            return True

        def IsA(self, _type):
            return True

    class _Camera:
        def __init__(self, _prim):
            pass

        def GetFocalLengthAttr(self):
            return _Attr(50.0)

        def GetHorizontalApertureAttr(self):
            return _Attr(100.0)

        def GetVerticalApertureAttr(self):
            return _Attr(50.0)

        def GetHorizontalApertureOffsetAttr(self):
            return _Attr(0.0)

        def GetVerticalApertureOffsetAttr(self):
            return _Attr(0.0)

        def GetProjectionAttr(self):
            return _Attr("perspective")

        def GetClippingRangeAttr(self):
            return _Attr((0.1, 1000.0))

    class _Matrix:
        def __init__(self, diagonal):
            self.rows = [[float(diagonal if row == column else 0) for column in range(4)] for row in range(4)]

        def __getitem__(self, index):
            return self.rows[index]

        def GetInverse(self):
            return _Matrix(0.5)

    class _Xformable:
        def __init__(self, _prim):
            pass

        def ComputeLocalToWorldTransform(self, _time):
            return _Matrix(2.0)

    prim = _Prim()
    stage = types.SimpleNamespace(GetPrimAtPath=lambda _path: prim)
    adapter.get_stage = lambda: stage
    adapter._camera_sensors["/World/Cam"] = types.SimpleNamespace(resolution=(480, 640))

    fake_usd = types.SimpleNamespace(TimeCode=types.SimpleNamespace(Default=lambda: object()))
    fake_usd_geom = types.SimpleNamespace(
        Camera=_Camera,
        Xformable=_Xformable,
        GetStageMetersPerUnit=lambda _stage: 0.01,
    )
    pxr = sys.modules["pxr"]
    monkeypatch.setattr(pxr, "Usd", fake_usd, raising=False)
    monkeypatch.setattr(pxr, "UsdGeom", fake_usd_geom, raising=False)

    result = adapter.get_camera_calibration("/World/Cam")

    assert result["resolution"] == {"width": 640, "height": 480}
    assert result["intrinsic_matrix"] == [[320.0, 0.0, 320.0], [0.0, 480.0, 240.0], [0.0, 0.0, 1.0]]
    assert result["camera_to_world"][0][0] == 2.0
    assert result["world_to_camera"][0][0] == 0.5
    assert result["meters_per_unit"] == 0.01
    assert result["depth_units"] == "meters"


def _install_fake_replicator(monkeypatch, scheduled, pending_done):
    """Publish omni.replicator.core and capture what gets scheduled.

    `import omni.replicator.core` walks the parent packages, so each level has to
    exist as an attribute as well as in sys.modules. asyncio.ensure_future is
    patched on the real module rather than replaced wholesale.
    """
    import asyncio as real_asyncio

    async def _step_async(**kwargs):
        return None

    fake_core = types.ModuleType("omni.replicator.core")
    fake_core.orchestrator = types.SimpleNamespace(step_async=_step_async)
    fake_replicator = types.ModuleType("omni.replicator")
    fake_replicator.core = fake_core
    fake_omni = types.ModuleType("omni")
    fake_omni.replicator = fake_replicator
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.replicator", fake_replicator)
    monkeypatch.setitem(sys.modules, "omni.replicator.core", fake_core)

    class _Task:
        def done(self):
            return pending_done

    def _ensure_future(coro, *a, **kw):
        scheduled.append(coro)
        coro.close()
        return _Task()

    monkeypatch.setattr(real_asyncio, "ensure_future", _ensure_future)


def test_v6_requests_a_render_frame_without_starting_the_timeline(monkeypatch):
    """An empty sensor must trigger a Replicator frame, scheduled not awaited.

    Measured on 6.0.1: orchestrator.run() starts the timeline (playing=True),
    which destroys frame-exact stepping, and the synchronous orchestrator.step()
    is refused from inside kit. step_async scheduled onto kit's loop captures one
    frame with the timeline left stopped.
    """
    scheduled = []
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    _install_fake_replicator(monkeypatch, scheduled, pending_done=False)

    assert adapter._request_render_frame() is True
    assert len(scheduled) == 1, "must schedule exactly one render request"


def test_v6_uses_running_timeline_instead_of_requesting_a_pause_render(monkeypatch):
    """A fallback render must not stop Play and release the camera sensor."""
    scheduled = []
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    _install_fake_replicator(monkeypatch, scheduled, pending_done=False)
    timeline = types.SimpleNamespace(is_playing=lambda: True)
    fake_timeline = types.ModuleType("omni.timeline")
    fake_timeline.get_timeline_interface = lambda: timeline
    fake_omni = sys.modules.get("omni", types.ModuleType("omni"))
    monkeypatch.setattr(fake_omni, "timeline", fake_timeline, raising=False)
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline)

    assert adapter._request_render_frame() is True
    assert scheduled == []


def test_v6_play_commits_timeline_transition(monkeypatch):
    """Replicator capture-on-play callbacks require the transition to commit."""
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    monkeypatch.setattr(adapter, "_ensure_physics_world", lambda: calls.append("physics"))
    timeline = types.SimpleNamespace(
        play=lambda: calls.append("play"),
        commit=lambda: calls.append("commit"),
    )
    fake_timeline = types.ModuleType("omni.timeline")
    fake_timeline.get_timeline_interface = lambda: timeline
    fake_omni = types.ModuleType("omni")
    fake_omni.timeline = fake_timeline
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline)

    adapter.play()

    assert calls == ["physics", "play", "commit"]


def test_v6_does_not_queue_a_second_render_request_while_one_is_pending(monkeypatch):
    """Repeated captures on a blank camera must not pile up orchestrator tasks."""
    scheduled = []
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    _install_fake_replicator(monkeypatch, scheduled, pending_done=False)

    adapter._request_render_frame()
    adapter._request_render_frame()
    adapter._request_render_frame()

    assert len(scheduled) == 1


def test_v6_requests_a_new_frame_once_the_previous_request_finished(monkeypatch):
    """A completed request must not block later captures from asking again."""
    scheduled = []
    calls = []
    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    _install_fake_replicator(monkeypatch, scheduled, pending_done=True)

    adapter._request_render_frame()
    adapter._request_render_frame()

    assert len(scheduled) == 2


def test_v6_get_simulation_state_survives_a_missing_stage(monkeypatch):
    """Kit accepts commands ~2.9s before it creates a stage.

    Traversing None there raised "'NoneType' object has no attribute 'Traverse'"
    — an opaque failure for a routine status query. The timeline state is still
    knowable, so it must be reported.
    """

    class _Timeline:
        def is_playing(self):
            return False

        def is_stopped(self):
            return True

        def get_current_time(self):
            return 0.0

    class _SM:
        @classmethod
        def get_active_physics_engine(cls):
            return "physx"

        @classmethod
        def get_simulation_time(cls):
            return 0.0

    monkeypatch.setitem(sys.modules, "isaacsim.core.simulation_manager", types.SimpleNamespace(SimulationManager=_SM))
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", types.SimpleNamespace(get_version=lambda: "6.0.1"))

    fake_timeline = types.ModuleType("omni.timeline")
    fake_timeline.get_timeline_interface = lambda: _Timeline()
    fake_usd = types.ModuleType("omni.usd")
    fake_usd.get_context = lambda: types.SimpleNamespace(get_stage=lambda: None)  # no stage yet
    fake_omni = types.ModuleType("omni")
    fake_omni.timeline = fake_timeline
    fake_omni.usd = fake_usd
    monkeypatch.setitem(sys.modules, "omni", fake_omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", fake_timeline)
    monkeypatch.setitem(sys.modules, "omni.usd", fake_usd)

    import importlib

    import isaac_sim_mcp_extension.adapters.v6 as v6_mod

    importlib.reload(v6_mod)
    state = v6_mod.IsaacAdapterV6().get_simulation_state()

    assert state["timeline_state"] == "stopped"
    assert state["physics_dt"] == 1.0 / 60.0


def test_v6_create_lidar_requests_full_auxiliary_output(monkeypatch):
    """Task 1.3 fields require FULL GMO output and the stable-ID annotator."""
    captured = {}

    class _Lidar:
        def __init__(self, path, aux_output_level, **kwargs):
            captured["path"] = path
            captured["aux_output_level"] = aux_output_level
            captured.update(kwargs)
            self.paths = [path]

    class _LidarSensor:
        def __init__(self, lidar, annotators):
            captured["lidar"] = lidar
            captured["annotators"] = annotators

    rtx_mod = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx_mod.Lidar = _Lidar
    rtx_mod.LidarSensor = _LidarSensor
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx_mod)
    adapter = _v6_with_stub_simulation_manager(monkeypatch, [])

    lidar = adapter.create_lidar("/World/TestLidar")

    assert captured["path"] == "/World/TestLidar"
    assert captured["aux_output_level"] == "FULL"
    assert captured["accumulate_outputs"] is False
    assert captured["attributes"]["omni:sensor:tickRate"] == 10.0
    assert captured["attributes"]["omni:sensor:Core:validEndAzimuthDeg"] == 360.0
    assert captured["lidar"] is lidar
    assert captured["annotators"] == ["generic-model-output", "stable-id-map"]


def test_v6_create_lidar_uses_supported_preset_api(monkeypatch):
    captured = {}

    class _Lidar:
        @classmethod
        def create(cls, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(paths=["/World/Preset/Lidar"])

    class _LidarSensor:
        def __init__(self, lidar, annotators):
            captured["wrapped"] = lidar
            captured["annotators"] = annotators

    rtx_mod = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx_mod.Lidar = _Lidar
    rtx_mod.LidarSensor = _LidarSensor
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx_mod)
    adapter = _v6_with_stub_simulation_manager(monkeypatch, [])

    lidar = adapter.create_lidar("/World/Preset", config="OS1", variant="OS1_REV6_32ch20hz512res")

    assert captured["path"] == "/World/Preset"
    assert captured["config"] == "OS1"
    assert captured["variant"] == "OS1_REV6_32ch20hz512res"
    assert captured["aux_output_level"] == "FULL"
    assert captured["wrapped"] is lidar
    assert adapter._lidar_actual_paths["/World/Preset"] == "/World/Preset/Lidar"


def test_v6_get_lidar_config_derives_effective_values_from_usd(monkeypatch):
    values = {
        "omni:sensor:Core:validStartAzimuthDeg": 0.0,
        "omni:sensor:Core:validEndAzimuthDeg": 120.0,
        "omni:sensor:Core:startAzimuthOffsetDeg": -60.0,
        "omni:sensor:Core:scanRateBaseHz": 10,
        "omni:sensor:tickRate": 10.0,
        "omni:sensor:Core:patternFiringRateHz": 2400,
        "omni:sensor:Core:nearRangeM": 0.5,
        "omni:sensor:Core:farRangeM": 80.0,
        "omni:sensor:Core:numberOfChannels": 11,
        "omni:sensor:Core:numberOfEmitters": 11,
        "omni:sensor:Core:emitterState:s001:elevationDeg": [float(value) for value in range(-10, 11, 2)],
    }

    class _Attribute:
        def __init__(self, name):
            self.name = name

        def IsValid(self):
            return self.name in values

        def Get(self):
            return values[self.name]

    class _Prim:
        def IsValid(self):
            return True

        def GetAttribute(self, name):
            return _Attribute(name)

    adapter = _v6_with_stub_simulation_manager(monkeypatch, [])
    adapter._lidar_config_metadata["/World/Lidar"] = {"source": "generic"}
    monkeypatch.setattr(
        adapter,
        "get_stage",
        lambda: types.SimpleNamespace(GetPrimAtPath=lambda _path: _Prim()),
    )

    result = adapter.get_lidar_config("/World/Lidar")

    assert result["effective"] == {
        "horizontal_fov_deg": 120.0,
        "vertical_fov_deg": 20.0,
        "horizontal_resolution_deg": 0.5,
        "vertical_resolution_deg": 2.0,
        "rotation_rate_hz": 10.0,
        "min_range_m": 0.5,
        "max_range_m": 80.0,
        "horizontal_samples": 240,
        "vertical_channels": 11,
    }
    assert result["schema_attributes"]["pattern_firing_rate_hz"] == 2400


def test_v6_lidar_spherical_gmo_converts_to_cartesian(monkeypatch):
    """GMO spherical x/y/z are azimuth/elevation/range, not Cartesian XYZ."""

    class _Data:
        def numpy(self):
            return types.SimpleNamespace(size=1)

    gmo = types.SimpleNamespace(
        numElements=2,
        x=[0.0, 90.0],
        y=[0.0, 0.0],
        z=[2.0, 3.0],
        elementsCoordsType=types.SimpleNamespace(name="SPHERICAL"),
        frameOfReference=types.SimpleNamespace(name="SENSOR"),
        timestampNs=123,
        frameId=7,
        scalar=[0.25, 0.75],
        objId=[],
    )
    rtx_mod = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx_mod.LidarSensor = object
    rtx_mod.parse_generic_model_output_data = lambda _data: gmo
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx_mod)
    adapter = _v6_with_stub_simulation_manager(monkeypatch, [])
    adapter._lidar_sensors["/World/TestLidar"] = types.SimpleNamespace(get_data=lambda _annotator: (_Data(), {}))
    monkeypatch.setattr(
        adapter,
        "get_prim_transform",
        lambda _path: {"position": [0.0, 0.0, 1.0], "rotation": [0.0, 0.0, 0.0]},
    )

    frame = adapter.get_lidar_point_cloud_frame("/World/TestLidar")

    points = frame["fields"]["points"]["data"]
    assert points[0] == [2.0, 0.0, 0.0]
    assert abs(points[1][0]) < 1e-6
    assert abs(points[1][1] - 3.0) < 1e-6
    assert points[1][2] == 0.0
    assert frame["fields"]["range"]["data"] == [2.0, 3.0]
    assert frame["fields"]["intensity"]["data"] == [0.25, 0.75]
    assert frame["coordinate_type"] == "spherical"
    assert frame["coordinate_frame"] == "sensor"
    assert frame["sensor_timestamp_ns"] == 123
    assert frame["sensor_frame_id"] == 7
