from __future__ import annotations

from typing import Any

import pytest
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.sensors import SensorRuntime


class _SensorSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.lifecycle_state = object()

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"result:{name}"

        return call


def _adapter(sensor_runtime: Any) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    adapter._sensor_runtime = sensor_runtime
    return adapter


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        ("_request_render_frame", (), {}, "result:_request_render_frame"),
        ("_apply_sensor_schema", ("/World/Camera",), {}, None),
        ("create_camera", ("/World/Camera", (640, 480)), {"frequency": 30}, "result:create_camera"),
        ("capture_camera_image", ("/World/Camera",), {}, "result:capture_camera_image"),
        ("capture_camera_output", ("/World/Camera", "normals"), {}, "result:capture_camera_output"),
        ("get_camera_calibration", ("/World/Camera",), {}, "result:get_camera_calibration"),
        ("create_lidar", ("/World/Lidar", "OS1"), {"variant": "32ch"}, "result:create_lidar"),
        ("get_lidar_config", ("/World/Lidar",), {}, "result:get_lidar_config"),
        ("get_lidar_point_cloud", ("/World/Lidar",), {}, "result:get_lidar_point_cloud"),
        ("get_lidar_point_cloud_frame", ("/World/Lidar",), {}, "result:get_lidar_point_cloud_frame"),
    ],
)
def test_sensor_facade_methods_forward_without_contract_changes(method, args, kwargs, expected) -> None:
    sensor_runtime = _SensorSpy()

    result = getattr(_adapter(sensor_runtime), method)(*args, **kwargs)

    assert result == expected
    assert sensor_runtime.calls == [(method, args, kwargs)]


def test_sensor_runtime_owns_lifecycle_state_and_render_request() -> None:
    runtime = SensorRuntime(object(), object())
    adapter = _adapter(runtime)

    assert adapter._sensor_lifecycle_state() is runtime.lifecycle_state
    assert adapter._camera_sensors is runtime.lifecycle_state.camera_sensors
    assert adapter._lidar_sensors is runtime.lifecycle_state.lidar_sensors
    assert adapter._lidar_actual_paths is runtime.lifecycle_state.lidar_actual_paths
    assert adapter._lidar_config_metadata is runtime.lifecycle_state.lidar_config_metadata
    assert "_camera_sensors" not in adapter.__dict__
    assert "_render_request" not in adapter.__dict__
    assert runtime._render_request is None


def test_shared_release_uses_runtime_owned_state_without_facade_cache_fields() -> None:
    class _Sensor:
        def __init__(self) -> None:
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    runtime = SensorRuntime(object(), object())
    adapter = _adapter(runtime)
    sensor = _Sensor()
    runtime.lifecycle_state.camera_sensors["/World/Camera"] = sensor

    report = adapter.release_sensor("/World/Camera")

    assert sensor.destroyed is True
    assert report["teardown_method"] == "destroy"
    assert report["cache_evicted"] is True
    assert runtime.lifecycle_state.camera_sensors == {}
    assert "_camera_sensors" not in adapter.__dict__
