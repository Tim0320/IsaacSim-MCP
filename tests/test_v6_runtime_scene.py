from __future__ import annotations

from typing import Any

import pytest
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.scene import SceneRuntime


class _SceneSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"result:{name}"

        return call


def _adapter(scene: Any) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    adapter._scene_runtime = scene
    return adapter


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        ("get_stage", (), {}, "result:get_stage"),
        ("get_assets_root_path", (), {}, "result:get_assets_root_path"),
        ("discover_environments", (), {}, "result:discover_environments"),
        ("load_environment", ("asset.usd", "/Environment"), {}, None),
        ("create_prim", ("/World/Box", "Cube"), {"ignored": True}, "result:create_prim"),
        ("add_reference_to_stage", ("asset.usd", "/World/Asset"), {}, "result:add_reference_to_stage"),
        ("set_prim_transform", ("/World/Box", [1, 2, 3], [0, 0, 0], [1, 1, 1]), {}, None),
        ("get_prim_transform", ("/World/Box",), {}, "result:get_prim_transform"),
        ("list_prims", ("/World", "Cube"), {}, "result:list_prims"),
        ("get_prim_info", ("/World/Box",), {}, "result:get_prim_info"),
        ("get_prim_actual_size", ("/World/Box",), {}, "result:get_prim_actual_size"),
    ],
)
def test_scene_facade_methods_forward_without_contract_changes(method, args, kwargs, expected) -> None:
    scene = _SceneSpy()
    result = getattr(_adapter(scene), method)(*args, **kwargs)

    assert result == expected
    assert scene.calls == [(method, args, kwargs)]


def test_delete_prim_releases_sensor_before_scene_deletion() -> None:
    events: list[tuple[str, str]] = []

    class _Scene:
        def delete_prim(self, prim_path: str) -> bool:
            events.append(("delete", prim_path))
            return True

    adapter = _adapter(_Scene())
    adapter.release_sensor = lambda prim_path: events.append(("release", prim_path))

    assert adapter.delete_prim("/World/Camera") is True
    assert events == [("release", "/World/Camera"), ("delete", "/World/Camera")]


def test_scene_runtime_get_stage_is_dynamic() -> None:
    stages = iter([object(), object()])

    class _Context:
        def get_stage(self):
            return next(stages)

    runtime = SceneRuntime(_Context())

    assert runtime.get_stage() is not runtime.get_stage()


@pytest.mark.parametrize(
    ("axis", "expected"),
    [("X", [6.0, 12.0, 16.0]), ("Y", [4.0, 18.0, 16.0]), ("Z", [4.0, 12.0, 24.0])],
)
def test_axial_dimensions_preserve_axis_mapping(axis: str, expected: list[float]) -> None:
    assert SceneRuntime._axial_dims(axis, height=6.0, diameter=4.0, scale=[1.0, 3.0, 4.0]) == expected
