from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.robots import RobotRuntime


class _RobotSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._articulations: dict[str, Any] = {}

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"result:{name}"

        return call


def _adapter(robot_runtime: Any) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    adapter._robot_runtime = robot_runtime
    return adapter


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        ("create_xform_prim", ("/World/Robot",), {}, "result:create_xform_prim"),
        ("create_articulation", ("/World/Robot", "robot"), {}, "result:create_articulation"),
        ("_new_articulation", ("/World/Robot",), {}, "result:_new_articulation"),
        ("_runtime_articulation", ("/World/Robot",), {}, "result:_runtime_articulation"),
        ("discover_robots", (), {}, "result:discover_robots"),
        ("get_robot_joint_info", ("/World/Robot",), {}, "result:get_robot_joint_info"),
        ("set_joint_positions", ("/World/Robot", [0.1], [0]), {}, None),
        ("_set_joint_drive_targets", ("/World/Robot", [0.1], [0]), {}, None),
        ("_get_joint_names", ("/World/Robot",), {}, "result:_get_joint_names"),
        ("get_joint_positions", ("/World/Robot",), {}, "result:get_joint_positions"),
        ("get_joint_state", ("/World/Robot",), {}, "result:get_joint_state"),
        ("set_joint_command", ("/World/Robot", "position", [0.1], [0]), {}, None),
        (
            "compute_holonomic_wheel_velocities",
            ("/World/Robot", "/World/Robot/com", [0.1, 0.0, 0.0], ["wheel"]),
            {},
            "result:compute_holonomic_wheel_velocities",
        ),
        ("_drive_config_articulation", ("/World/Robot",), {}, "result:_drive_config_articulation"),
        ("get_joint_drive_config", ("/World/Robot",), {}, "result:get_joint_drive_config"),
        ("set_joint_drive_config", ("/World/Robot", {"damping": 1.0}, [0]), {}, None),
        ("get_joint_config", ("/World/Robot",), {}, "result:get_joint_config"),
    ],
)
def test_robot_facade_methods_forward_without_contract_changes(method, args, kwargs, expected) -> None:
    runtime = _RobotSpy()

    result = getattr(_adapter(runtime), method)(*args, **kwargs)

    assert result == expected
    assert runtime.calls == [(method, args, kwargs)]


def test_robot_runtime_owns_articulation_cache_but_not_motion_state() -> None:
    runtime = RobotRuntime(object(), object(), object())
    adapter = _adapter(runtime)
    marker = object()
    runtime._articulations["/World/Robot"] = marker

    assert adapter._articulations is runtime._articulations
    assert adapter._articulations["/World/Robot"] is marker
    assert "_articulations" not in adapter.__dict__
    assert not hasattr(runtime, "_motion_trajectories")
    assert not hasattr(runtime, "_motion_jobs")
    assert not hasattr(runtime, "_motion_update_subscription")


def test_robot_runtime_stop_hook_target_clears_only_articulation_cache() -> None:
    runtime = RobotRuntime(object(), object(), object())
    runtime._articulations["/World/Robot"] = object()

    runtime.clear_runtime_cache()

    assert runtime._articulations == {}


def test_robot_runtime_rejects_a_fresh_but_invalid_tensor_entity(monkeypatch) -> None:
    created = []

    class _Articulation:
        def __init__(self, paths):
            created.append(paths)

        def is_physics_tensor_entity_valid(self):
            return False

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.experimental.prims",
        types.SimpleNamespace(Articulation=_Articulation),
    )
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: object()), object(), object())
    runtime._ensure_physics_world = lambda: None

    with pytest.raises(RuntimeError, match="physics tensor entity"):
        runtime._runtime_articulation("/World/Robot")

    assert created == [["/World/Robot"], ["/World/Robot"]]


def test_robot_runtime_does_not_reuse_articulation_across_stage_identity(monkeypatch) -> None:
    created = []
    active_stage = [object()]

    class _Articulation:
        def __init__(self, paths):
            self.paths = paths
            created.append(self)

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.experimental.prims",
        types.SimpleNamespace(Articulation=_Articulation),
    )
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: active_stage[0]), object(), object())

    first = runtime._new_articulation("/World/Robot")
    active_stage[0] = object()
    second = runtime._new_articulation("/World/Robot")

    assert second is not first
    assert len(created) == 2


def test_robot_runtime_rebinds_same_path_when_usd_joint_identity_changes(monkeypatch) -> None:
    created = []

    class _Articulation:
        def __init__(self, paths):
            self.paths = paths
            self.dof_names = ["fr3_joint1"] if not created else ["panda_joint1"]
            created.append(self)

        def is_physics_tensor_entity_valid(self):
            return True

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.experimental.prims",
        types.SimpleNamespace(Articulation=_Articulation),
    )
    stage = object()
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: stage), object(), object())
    runtime._ensure_physics_world = lambda: None
    runtime._usd_joint_names = lambda _path: ["panda_joint1"]
    stale = runtime._new_articulation("/World/Robot")

    rebound = runtime._runtime_articulation("/World/Robot")

    assert stale.dof_names == ["fr3_joint1"]
    assert rebound.dof_names == ["panda_joint1"]
    assert rebound is not stale
