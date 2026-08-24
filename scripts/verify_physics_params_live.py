#!/usr/bin/env python3
"""Guarded Isaac Sim 6.0.1 live acceptance for Task 3.1."""

from __future__ import annotations

import json
import math
import time

from isaac_mcp.connection import IsaacConnection

DEFAULT_PHYSICS_PATHS = ("/PhysicsScene", "/World/PhysicsScene")


def _progress(step: str) -> None:
    print(json.dumps({"event": "progress", "step": step}), flush=True)


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _wait_timeline_state(connection: IsaacConnection, expected: str, timeout_seconds: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        state = _data(connection.send_command("simulation.get_state"))
        if state["timeline_state"] == expected:
            return state
        if time.monotonic() >= deadline:
            raise AssertionError({"expected_timeline_state": expected, "last_state": state})
        time.sleep(0.05)


def _stage_guard(connection: IsaacConnection) -> list[str]:
    code = """
import json
import omni.usd
unexpected = []
stage = omni.usd.get_context().get_stage()
for prim in stage.TraverseAll():
    path = str(prim.GetPath())
    if path in {"/World", "/Environment", "/Environment/defaultLight", "/PhysicsScene", "/World/PhysicsScene"} or path.startswith(
        ("/Render", "/OmniverseKit")
    ):
        continue
    unexpected.append(path)
print(json.dumps(unexpected))
"""
    deadline = time.monotonic() + 30.0
    while True:
        response = connection.send_command("simulation.execute_script", {"code": code})
        if response.get("code") != "STAGE_NOT_READY" or time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    result = _data(response)
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return json.loads(lines[-1])


def _physics_snapshot(connection: IsaacConnection, path: str) -> dict:
    code = f"""
import json
import omni.usd
from pxr import PhysxSchema
stage = omni.usd.get_context().get_stage()
prim = stage.GetPrimAtPath({path!r})
names = [
    "physics:gravityDirection",
    "physics:gravityMagnitude",
    "physxScene:timeStepsPerSecond",
    "physxScene:enableGPUDynamics",
    "physxScene:broadphaseType",
    "physxScene:enableCCD",
]
payload = {{"exists": bool(prim and prim.IsValid())}}
if payload["exists"]:
    payload["had_physx_api"] = prim.HasAPI(PhysxSchema.PhysxSceneAPI)
    payload["attrs"] = {{
        name: {{
            "authored": bool(prim.GetAttribute(name) and prim.GetAttribute(name).HasAuthoredValueOpinion()),
            "value": prim.GetAttribute(name).Get() if prim.GetAttribute(name) else None,
        }}
        for name in names
    }}
    for name, item in list(payload["attrs"].items()):
        value = item["value"]
        if name == "physics:gravityDirection" and value is not None:
            item["value"] = [float(component) for component in value]
        elif value is not None and not isinstance(value, (bool, int, float, str)):
            item["value"] = str(value)
print(json.dumps(payload))
"""
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return json.loads(lines[-1])


def _restore_physics_snapshot(connection: IsaacConnection, path: str, snapshot: dict) -> None:
    payload = json.dumps(snapshot, separators=(",", ":"))
    code = f"""
import json
import omni.usd
from pxr import Gf, PhysxSchema
snapshot = json.loads({payload!r})
prim = omni.usd.get_context().get_stage().GetPrimAtPath({path!r})
assert prim and prim.IsValid()
for name, item in snapshot["attrs"].items():
    attr = prim.GetAttribute(name)
    if not attr:
        continue
    if item["authored"]:
        value = item["value"]
        if name == "physics:gravityDirection" and value is not None:
            value = Gf.Vec3f(*value)
        attr.Set(value)
    else:
        attr.Clear()
if not snapshot["had_physx_api"] and prim.HasAPI(PhysxSchema.PhysxSceneAPI):
    prim.RemoveAPI(PhysxSchema.PhysxSceneAPI)
print("restored")
"""
    _data(connection.send_command("simulation.execute_script", {"code": code}))


def _manager_snapshot(connection: IsaacConnection) -> dict:
    code = """
import json
import inspect
import carb
import omni.usd
from isaacsim.core.simulation_manager import SimulationManager
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
print(json.dumps({
    "default_dt": SimulationManager.get_physics_dt(),
    "default_path": getattr(SimulationManager, "_default_physics_scene_path", None),
    "stage_time_codes_per_second": float(omni.usd.get_context().get_stage().GetTimeCodesPerSecond()),
    "min_frame_rate": carb.settings.get_settings().get("/persistent/simulation/minFrameRate"),
    "source_has_string_path_match": "str(item.path)" in inspect.getsource(IsaacAdapterV6.configure_physics),
    "scenes": [
        {
            "path": str(scene.path),
            "path_repr": repr(scene.path),
            "path_type": str(type(scene.path)),
            "dt": float(scene.get_dt()),
            "type": str(type(scene)),
            "methods": {
                name: hasattr(scene, name)
                for name in (
                    "set_steps_per_second",
                    "set_enabled_gpu_dynamics",
                    "set_broadphase_type",
                    "get_dt",
                    "get_enabled_gpu_dynamics",
                    "get_broadphase_type",
                )
            },
        }
        for scene in SimulationManager.get_physics_scenes()
    ],
}))
"""
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return json.loads(lines[-1])


def _restore_manager_snapshot(connection: IsaacConnection, snapshot: dict) -> None:
    payload = json.dumps(snapshot, separators=(",", ":"))
    code = f"""
import json
import carb
import omni.usd
from isaacsim.core.simulation_manager import SimulationManager
snapshot = json.loads({payload!r})
stage = omni.usd.get_context().get_stage()
stage.SetTimeCodesPerSecond(snapshot["stage_time_codes_per_second"])
settings = carb.settings.get_settings()
key = "/persistent/simulation/minFrameRate"
if snapshot["min_frame_rate"] is None:
    settings.destroy_item(key)
else:
    settings.set(key, snapshot["min_frame_rate"])
if snapshot["default_path"] is None:
    SimulationManager._default_physics_scene_path = None
else:
    SimulationManager.set_default_physics_scene(snapshot["default_path"])
print("restored")
"""
    _data(connection.send_command("simulation.execute_script", {"code": code}))


def _assert_120_hz_readback(result: dict) -> None:
    assert result["code"] == "PHYSICS_PARAMS_APPLIED", result
    data = result["data"]
    usd = data["readback"]["usd"]
    runtime = data["readback"]["runtime"]
    assert data["atomic"] is True
    assert data["side_effects"]["physics_gpu_ordinal_changed"] is False
    assert usd["time_steps_per_second"] == 120
    assert math.isclose(usd["time_step"], 1.0 / 120.0, abs_tol=1e-9)
    assert math.isclose(runtime["time_step"], 1.0 / 120.0, abs_tol=1e-9)
    assert math.isclose(runtime["manager_time_step"], 1.0 / 120.0, abs_tol=1e-9)
    assert runtime["default_scene_path"] == data["scene_path"]
    assert runtime["stage_time_codes_per_second"] == 120.0
    assert runtime["min_frame_rate"] == 120
    assert usd["gpu_enabled"] is True and runtime["gpu_enabled"] is True
    assert usd["broadphase_type"] == "GPU" and runtime["broadphase_type"] == "GPU"


def main() -> int:
    connection = IsaacConnection(port=8766)
    owns_scene = False
    baseline_path = None
    baseline_snapshot = None
    baseline_manager = None
    active_scene_path = None
    try:
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["runtime"]["isaac_sim_version"].startswith("6.0.1")
        assert capabilities["runtime"]["physics_backend"] == "physx"
        assert capabilities["feature_flags"]["physics.time_step"]["state"] == "supported"
        assert capabilities["feature_flags"]["physics.gpu_enabled"]["state"] == "supported"

        unexpected = _stage_guard(connection)
        if unexpected:
            print(
                json.dumps(
                    {
                        "pass": False,
                        "code": "SCRATCH_STAGE_REQUIRED",
                        "message": "Refusing Stage and timeline writes because pre-existing content exists",
                        "unexpected_prim_count": len(unexpected),
                        "unexpected_prims": unexpected[:20],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2

        for candidate in DEFAULT_PHYSICS_PATHS:
            snapshot = _physics_snapshot(connection, candidate)
            if snapshot["exists"]:
                assert baseline_path is None, "Multiple baseline PhysicsScene prims are unsafe"
                baseline_path = candidate
                baseline_snapshot = snapshot
        baseline_manager = _manager_snapshot(connection)

        _progress("verify_120_hz_gpu_mapping")
        applied = connection.send_command(
            "simulation.set_physics",
            {"gravity": [0.0, 0.0, -3.72], "time_step": 1.0 / 120.0, "gpu_enabled": True},
        )
        _assert_120_hz_readback(applied)
        active_scene_path = applied["data"]["scene_path"]
        owns_scene = baseline_path is None
        manager_120 = _manager_snapshot(connection)
        assert math.isclose(manager_120["default_dt"], 1.0 / 120.0, abs_tol=1e-9), {
            "active_scene_path": active_scene_path,
            "applied": applied["data"],
            "stage_after_response": _physics_snapshot(connection, active_scene_path),
            "manager": manager_120,
        }

        state_120 = _data(connection.send_command("simulation.get_state"))
        assert state_120["timeline_state"] == "stopped", state_120
        assert math.isclose(state_120["physics_dt"], 1.0 / 120.0, abs_tol=1e-9), state_120

        _progress("verify_invalid_request_atomicity")
        before_invalid = _physics_snapshot(connection, active_scene_path)
        invalid = connection.send_command("simulation.set_physics", {"time_step": 0.007})
        assert invalid["status"] == "error" and invalid["code"] == "INVALID_PHYSICS_PARAMS", invalid
        assert _physics_snapshot(connection, active_scene_path) == before_invalid

        _progress("verify_actual_step_timing")
        # The first step call also initializes physics and arms the Stop reset
        # point. Measure a second, steady-state batch so initialization work is
        # not mistaken for the configured physics clock.
        _data(connection.send_command("simulation.step", {"num_steps": 2}))
        time_before = float(_data(connection.send_command("simulation.get_state"))["current_time"])
        _data(connection.send_command("simulation.step", {"num_steps": 12}))
        time_after = float(_data(connection.send_command("simulation.get_state"))["current_time"])
        measured_delta = time_after - time_before
        assert math.isclose(measured_delta, 0.1, rel_tol=1e-5, abs_tol=1e-6), {
            "measured_delta": measured_delta,
            "manager": _manager_snapshot(connection),
        }

        _progress("verify_active_timeline_rejection")
        _data(connection.send_command("simulation.play"))
        before_active = _physics_snapshot(connection, active_scene_path)
        active = connection.send_command("simulation.set_physics", {"gpu_enabled": False})
        assert active["status"] == "error" and active["code"] == "TIMELINE_NOT_STOPPED", active
        assert _physics_snapshot(connection, active_scene_path) == before_active
        _data(connection.send_command("simulation.stop"))
        _wait_timeline_state(connection, "stopped")

        _progress("verify_cpu_mbp_mapping")
        cpu = connection.send_command("simulation.set_physics", {"gpu_enabled": False})
        cpu_data = _data(cpu)
        cpu_usd = cpu_data["readback"]["usd"]
        cpu_runtime = cpu_data["readback"]["runtime"]
        assert cpu_usd["gpu_enabled"] is False and cpu_runtime["gpu_enabled"] is False
        assert cpu_usd["broadphase_type"] == "MBP" and cpu_runtime["broadphase_type"] == "MBP"

        print(
            json.dumps(
                {
                    "pass": True,
                    "runtime": capabilities["runtime"],
                    "physics_scene": active_scene_path,
                    "gpu_120_hz_readback": applied["data"]["readback"],
                    "invalid_request_atomic": True,
                    "active_timeline_atomic": True,
                    "step_timing": {"steps": 12, "expected_seconds": 0.1, "measured_seconds": measured_delta},
                    "cpu_mbp_readback": cpu_data["readback"],
                    "physics_gpu_ordinal_changed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        try:
            if active_scene_path:
                connection.send_command("simulation.stop")
                _wait_timeline_state(connection, "stopped")
                if owns_scene:
                    _progress("cleanup_owned_physics_scene")
                    if connection.send_command(
                        "scene.get_prim_info", {"prim_path": active_scene_path}
                    )["status"] == "success":
                        connection.send_command("objects.delete", {"prim_path": active_scene_path})
                elif baseline_path and baseline_snapshot:
                    _progress("restore_baseline_physics_scene")
                    _restore_physics_snapshot(connection, baseline_path, baseline_snapshot)
                    if baseline_manager:
                        _restore_manager_snapshot(connection, baseline_manager)
                    assert _physics_snapshot(connection, baseline_path) == baseline_snapshot
                    restored_manager = _manager_snapshot(connection)
                    for key in ("default_dt", "default_path", "stage_time_codes_per_second", "min_frame_rate"):
                        assert restored_manager[key] == baseline_manager[key]
        finally:
            connection.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
