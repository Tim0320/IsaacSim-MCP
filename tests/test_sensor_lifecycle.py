"""Task 1.6 deterministic Camera/LiDAR lifecycle contracts."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from isaac_sim_mcp_extension.adapters.base import IsaacAdapterBase, SensorLifecycleError
from isaac_sim_mcp_extension.handlers import objects, sensors


class _HydraTexture:
    path = "/Render/HydraTextures/test_sensor"

    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _RuntimeSensor:
    def __init__(self, *, fail: bool = False) -> None:
        self._annotators = {"rgb": object(), "normals": object()}
        self._writers = {"writer": object()}
        self._hydra_texture = _HydraTexture()
        self.fail = fail
        self.invalidations = 0

    def _invalidate_sensor(self) -> None:
        self.invalidations += 1
        if self.fail:
            raise RuntimeError("hydra teardown failed")
        self._annotators.clear()
        self._writers.clear()
        self._hydra_texture.destroy()
        self._hydra_texture = None


class _DestroyRuntimeSensor:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


def _adapter() -> IsaacAdapterBase:
    class _LifecycleAdapter(IsaacAdapterBase):
        pass

    _LifecycleAdapter.__abstractmethods__ = frozenset()
    adapter = _LifecycleAdapter()
    adapter._camera_sensors = {}
    adapter._lidar_sensors = {}
    adapter._initialized_cameras = set()
    adapter._lidar_actual_paths = {}
    adapter._lidar_config_metadata = {}
    return adapter


def test_release_sensor_uses_v6_runtime_invalidation_and_evicts_every_cache():
    adapter = _adapter()
    runtime = _RuntimeSensor()
    adapter._camera_sensors["/World/Camera"] = runtime
    adapter._initialized_cameras.add("/World/Camera")

    report = adapter.release_sensor("/World/Camera")

    assert runtime.invalidations == 1
    assert report == {
        "prim_path": "/World/Camera",
        "actual_prim_path": "/World/Camera",
        "sensor_type": "camera",
        "found": True,
        "teardown_method": "_invalidate_sensor",
        "annotators_before": ["normals", "rgb"],
        "writers_before": ["writer"],
        "render_product_path": "/Render/HydraTextures/test_sensor",
        "annotators_after": [],
        "writers_after": [],
        "render_product_released": True,
        "cache_evicted": True,
        "metadata_evicted": True,
    }
    assert "/World/Camera" not in adapter._camera_sensors
    assert "/World/Camera" not in adapter._initialized_cameras


def test_release_sensor_failure_is_explicit_and_keeps_reference_for_retry():
    adapter = _adapter()
    runtime = _RuntimeSensor(fail=True)
    adapter._lidar_sensors["/World/Lidar"] = runtime
    adapter._lidar_actual_paths["/World/Lidar"] = "/World/Lidar/Actual"
    adapter._lidar_config_metadata["/World/Lidar"] = {"source": "preset"}

    with pytest.raises(SensorLifecycleError) as exc:
        adapter.release_sensor("/World/Lidar")

    assert exc.value.code == "SENSOR_RELEASE_FAILED"
    assert "hydra teardown failed" in str(exc.value)
    assert adapter._lidar_sensors["/World/Lidar"] is runtime
    assert adapter._lidar_actual_paths["/World/Lidar"] == "/World/Lidar/Actual"
    assert adapter._lidar_config_metadata["/World/Lidar"] == {"source": "preset"}


def test_release_sensor_uses_public_destroy_fallback_when_invalidation_is_unavailable():
    adapter = _adapter()
    runtime = _DestroyRuntimeSensor()
    adapter._camera_sensors["/World/Camera"] = runtime

    report = adapter.release_sensor("/World/Camera")

    assert runtime.destroyed is True
    assert report["teardown_method"] == "destroy"
    assert report["cache_evicted"] is True


def test_runtime_release_on_timeline_stop_preserves_lidar_authoring_metadata():
    adapter = _adapter()
    runtime = _RuntimeSensor()
    adapter._lidar_sensors["/World/Lidar"] = runtime
    adapter._lidar_actual_paths["/World/Lidar"] = "/World/Lidar/Actual"
    adapter._lidar_config_metadata["/World/Lidar"] = {"source": "preset"}

    report = adapter.release_sensor("/World/Lidar", evict_metadata=False)

    assert report["metadata_evicted"] is False
    assert "/World/Lidar" not in adapter._lidar_sensors
    assert adapter._lidar_actual_paths["/World/Lidar"] == "/World/Lidar/Actual"
    assert adapter._lidar_config_metadata["/World/Lidar"] == {"source": "preset"}


class _Prim:
    def __init__(self, path: str, valid_paths: set[str], type_name: str = "Camera") -> None:
        self.path = path
        self.valid_paths = valid_paths
        self.type_name = type_name

    def IsValid(self) -> bool:
        return self.path in self.valid_paths

    def GetTypeName(self) -> str:
        return self.type_name

    def __bool__(self) -> bool:
        return self.IsValid()


class _Stage:
    def __init__(self, valid_paths: set[str]) -> None:
        self.valid_paths = valid_paths

    def GetPrimAtPath(self, path: str) -> _Prim:
        type_name = "RenderProduct" if path.startswith("/Render/") else "Camera"
        return _Prim(path, self.valid_paths, type_name)


class _DeleteAdapter:
    def __init__(self) -> None:
        self.valid_paths = {"/World/Camera", "/Render/HydraTextures/camera"}
        self._camera_sensors = {"/World/Camera": object()}
        self._lidar_sensors = {}
        self._lidar_actual_paths = {}
        self._lidar_config_metadata = {}

    def get_stage(self) -> _Stage:
        return _Stage(self.valid_paths)

    def get_simulation_state(self):
        return {"timeline_state": "stopped"}

    def release_sensor(self, prim_path: str):
        self._camera_sensors.pop(prim_path)
        return {
            "prim_path": prim_path,
            "actual_prim_path": prim_path,
            "sensor_type": "camera",
            "found": True,
            "teardown_method": "_invalidate_sensor",
            "annotators_before": ["rgb"],
            "writers_before": [],
            "render_product_path": "/Render/HydraTextures/camera",
            "annotators_after": [],
            "writers_after": [],
            "render_product_released": True,
            "cache_evicted": True,
            "metadata_evicted": True,
        }

    def delete_prim(self, prim_path: str) -> bool:
        self.valid_paths.discard(prim_path)
        self.valid_paths.discard("/Render/HydraTextures/camera")
        return True


class _IncompleteDeleteAdapter(_DeleteAdapter):
    def delete_prim(self, prim_path: str) -> bool:
        return True


def test_delete_sensor_waits_for_updates_and_returns_full_readback(monkeypatch):
    updates = []

    class _App:
        async def next_update_async(self):
            updates.append(len(updates) + 1)

    app_module = types.ModuleType("omni.kit.app")
    app_module.get_app = lambda: _App()
    kit_module = types.ModuleType("omni.kit")
    kit_module.app = app_module
    omni_module = types.ModuleType("omni")
    omni_module.kit = kit_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.kit", kit_module)
    monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)

    result = asyncio.run(sensors.delete_sensor(_DeleteAdapter(), "/World/Camera", post_delete_updates=3))

    assert result["status"] == "success"
    assert updates == [1, 2, 3]
    assert result["readback"] == {
        "prim_absent": True,
        "actual_prim_absent": True,
        "render_product_absent": True,
        "camera_cache_absent": True,
        "lidar_cache_absent": True,
        "lidar_path_metadata_absent": True,
        "lidar_config_metadata_absent": True,
    }
    assert result["lifecycle"]["teardown_method"] == "_invalidate_sensor"


def test_delete_sensor_rejects_running_timeline_and_invalid_update_count():
    adapter = _DeleteAdapter()
    adapter.get_simulation_state = lambda: {"timeline_state": "playing"}

    running = asyncio.run(sensors.delete_sensor(adapter, "/World/Camera"))
    invalid = asyncio.run(sensors.delete_sensor(_DeleteAdapter(), "/World/Camera", post_delete_updates=0))

    assert running["code"] == "SENSOR_DELETE_REQUIRES_NON_PLAYING"
    assert invalid["code"] == "INVALID_POST_DELETE_UPDATES"


def test_delete_sensor_fails_closed_when_timeline_state_cannot_be_read():
    adapter = _DeleteAdapter()
    adapter.get_simulation_state = lambda: (_ for _ in ()).throw(RuntimeError("timeline unavailable"))

    result = asyncio.run(sensors.delete_sensor(adapter, "/World/Camera"))

    assert result["code"] == "SENSOR_DELETE_STATE_UNAVAILABLE"
    assert "/World/Camera" in adapter.valid_paths


def test_delete_sensor_never_reports_success_when_resources_survive(monkeypatch):
    class _App:
        async def next_update_async(self):
            return None

    app_module = types.ModuleType("omni.kit.app")
    app_module.get_app = lambda: _App()
    kit_module = types.ModuleType("omni.kit")
    kit_module.app = app_module
    omni_module = types.ModuleType("omni")
    omni_module.kit = kit_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.kit", kit_module)
    monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)

    result = asyncio.run(sensors.delete_sensor(_IncompleteDeleteAdapter(), "/World/Camera"))

    assert result["status"] == "error"
    assert result["code"] == "SENSOR_DELETE_INCOMPLETE"
    assert result["readback"]["prim_absent"] is False
    assert result["readback"]["render_product_absent"] is False


def test_delete_object_routes_camera_through_verified_sensor_lifecycle(monkeypatch):
    adapter = _DeleteAdapter()
    calls = []

    async def _delete_sensor(received_adapter, prim_path, post_delete_updates):
        calls.append((received_adapter, prim_path, post_delete_updates))
        return {"status": "success", "code": "OK"}

    monkeypatch.setattr(sensors, "delete_sensor", _delete_sensor)

    result = asyncio.run(objects.delete(adapter, "/World/Camera", post_delete_updates=24))

    assert result == {"status": "success", "code": "OK"}
    assert calls == [(adapter, "/World/Camera", 24)]
