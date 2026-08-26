from __future__ import annotations

from typing import Any

import pytest
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.physics import PhysicsPolicyBridge


class _PhysicsSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"result:{name}"

        return call


def _adapter(runtime: Any) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    adapter._physics_runtime = runtime
    return adapter


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("create_world", (), {"physics_dt": 1.0 / 60.0}),
        ("create_simulation_context", (), {"device": "cpu"}),
        ("create_physics_scene", ([0.0, 0.0, -9.81], "PhysicsScene"), {}),
        ("configure_physics", ([0.0, 0.0, -9.81], 1.0 / 120.0, True), {}),
        ("configure_physics_body", ("/World/Box", "dynamic", True, "convex_hull", 2.0, None), {}),
        ("get_physics_body", ("/World/Box",), {}),
        ("create_collision_group", ("/World/Group", ["/World/Box"], [], False, None), {}),
        ("get_collision_group", ("/World/Group",), {}),
        (
            "create_physics_joint",
            (
                "/World/Joint",
                "revolute",
                "/World/Body1",
                "/World/Body0",
                "Z",
                -45.0,
                45.0,
                None,
                None,
                None,
                None,
                False,
            ),
            {},
        ),
        ("get_physics_joint", ("/World/Joint",), {}),
        ("get_physics_state", ("/World/Box",), {}),
    ],
)
def test_physics_facade_methods_forward_without_contract_changes(method, args, kwargs) -> None:
    runtime = _PhysicsSpy()

    result = getattr(_adapter(runtime), method)(*args, **kwargs)

    assert result == f"result:{method}"
    assert runtime.calls == [(method, args, kwargs)]


@pytest.mark.parametrize("method", ["_ensure_physics_world", "_arm_reset_point"])
def test_private_physics_lifecycle_methods_forward(method: str) -> None:
    runtime = _PhysicsSpy()

    result = getattr(_adapter(runtime), method)()

    assert result is None
    assert runtime.calls == [(method, (), {})]


def test_physics_policy_bridge_delegates_shared_base_policy() -> None:
    adapter = object.__new__(IsaacAdapterV6)
    adapter.require_backend_capability = lambda feature: {"feature": feature}
    adapter.get_simulation_state = lambda: {"timeline_state": "stopped"}
    adapter._find_physics_scene = lambda preferred: preferred or "/PhysicsScene"
    adapter._apply_gravity = lambda path, gravity: path == "/PhysicsScene" and gravity == [0.0, 0.0, -9.81]
    bridge = PhysicsPolicyBridge(adapter)

    assert bridge.require_backend_capability("physics.time_step") == {"feature": "physics.time_step"}
    assert bridge.get_simulation_state() == {"timeline_state": "stopped"}
    assert bridge.find_physics_scene("/PhysicsScene") == "/PhysicsScene"
    assert bridge.apply_gravity("/PhysicsScene", [0.0, 0.0, -9.81]) is True
