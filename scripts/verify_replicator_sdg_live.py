#!/usr/bin/env python3
"""Guarded live acceptance for Task 4.3 Replicator/SDG job lifecycle."""

from __future__ import annotations

import json
import time

from isaac_mcp.connection import IsaacConnection

ROOT = "/World/MCP_Task_4_3"
CAMERA = f"{ROOT}/Camera"
CUBE = f"{ROOT}/Cube"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    assert response["schema_version"] == "1.0", response
    return response["data"]


def _wait_terminal(connection: IsaacConnection, job_id: str, timeout: float = 45.0) -> dict:
    deadline = time.perf_counter() + timeout
    last = None
    while time.perf_counter() < deadline:
        last = _data(connection.send_command("replicator.get_job_status", {"job_id": job_id}))
        if last["state"] in {"completed", "cancelled", "error"}:
            return last
        time.sleep(0.05)
    raise TimeoutError(f"SDG job did not terminate: {last}")


def _create_fixture(connection: IsaacConnection) -> None:
    code = f'''
import omni.usd
from pxr import Gf, Semantics, UsdGeom
stage = omni.usd.get_context().get_stage()
root = UsdGeom.Xform.Define(stage, "{ROOT}").GetPrim()
cube = UsdGeom.Cube.Define(stage, "{CUBE}").GetPrim()
cube.GetAttribute("size").Set(1.0)
UsdGeom.XformCommonAPI(cube).SetTranslate(Gf.Vec3d(0.0, 0.0, 0.0))
semantics = Semantics.SemanticsAPI.Apply(cube, "Semantics")
semantics.CreateSemanticTypeAttr().Set("class")
semantics.CreateSemanticDataAttr().Set("cube")
camera = UsdGeom.Camera.Define(stage, "{CAMERA}").GetPrim()
UsdGeom.XformCommonAPI(camera).SetTranslate(Gf.Vec3d(0.0, 0.0, 5.0))
camera.GetAttribute("focalLength").Set(35.0)
'''
    _data(connection.send_command("simulation.execute_script", {"code": code}))
    camera = _data(connection.send_command("scene.get_prim_info", {"prim_path": CAMERA}))
    cube = _data(connection.send_command("scene.get_prim_info", {"prim_path": CUBE}))
    assert camera["type"] == "Camera" and cube["type"] == "Cube", {"camera": camera, "cube": cube}


def _config(frame_count: int) -> dict:
    return {
        "camera_prim_path": CAMERA,
        "frame_count": frame_count,
        "annotations": ["rgb", "semantic_segmentation"],
        "resolution": [320, 240],
        "seed": 4317,
        "randomizers": [
            {
                "type": "transform",
                "prim_paths": [CUBE],
                "position_min": [-0.4, 0.0, 0.0],
                "position_max": [0.4, 0.0, 0.0],
            }
        ],
        "rt_subframes": 2,
        "delta_time": 0.0,
    }


def _run_completed(connection: IsaacConnection, frame_count: int) -> dict:
    preview = _data(connection.send_command("replicator.create_job", {**_config(frame_count), "preview": True}))
    assert preview["preview"] is True
    created = connection.send_command("replicator.create_job", {**_config(frame_count), "preview": False})
    job = _data(created)
    assert created["readback"] == {"job_exists": True, "state": "configured"}
    started = connection.send_command("replicator.start_job", {"job_id": job["job_id"], "preview": False})
    _data(started)
    terminal = _wait_terminal(connection, job["job_id"])
    assert terminal["state"] == "completed", terminal
    assert terminal["frames_completed"] == frame_count, terminal
    manifest = _data(connection.send_command("replicator.get_manifest", {"job_id": job["job_id"]}))["manifest"]
    assert manifest["frames_completed"] == frame_count, manifest
    assert manifest["annotation_frame_counts"]["rgb"] == frame_count, manifest
    assert manifest["annotation_frame_counts"]["semantic_segmentation"] == frame_count, manifest
    assert manifest["file_count"] == len(manifest["files"]), manifest
    assert manifest["cleanup"] == {
        "writer_detached": True,
        "render_product_destroyed": True,
        "trigger_removed": True,
    }
    return {"job_id": job["job_id"], "terminal": terminal, "manifest": manifest}


def main() -> int:
    connection = IsaacConnection(port=8766)
    evidence = {}
    jobs = []
    try:
        _data(connection.send_command("simulation.stop"))
        state_before = _data(connection.send_command("simulation.get_state"))
        assert state_before["timeline_state"] == "stopped", state_before
        scene_before = _data(connection.send_command("scene.get_info"))
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["extension"]["command_count"] == 113
        assert capabilities["feature_flags"]["replicator.sdg_workflows"]["state"] == "supported"
        existing = connection.send_command("scene.get_prim_info", {"prim_path": ROOT})
        if existing["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))
        _create_fixture(connection)

        first = _run_completed(connection, 2)
        jobs.append(first["job_id"])
        second = _run_completed(connection, 2)
        jobs.append(second["job_id"])
        assert first["manifest"]["randomization_sha256"] == second["manifest"]["randomization_sha256"]
        assert first["manifest"]["randomization_trace"] == second["manifest"]["randomization_trace"]

        cancel_created = _data(
            connection.send_command("replicator.create_job", {**_config(100), "preview": False})
        )
        cancel_id = cancel_created["job_id"]
        jobs.append(cancel_id)
        _data(connection.send_command("replicator.start_job", {"job_id": cancel_id, "preview": False}))
        deadline = time.perf_counter() + 20
        progress = None
        while time.perf_counter() < deadline:
            progress = _data(connection.send_command("replicator.get_job_status", {"job_id": cancel_id}))
            if progress["frames_completed"] >= 1:
                break
            time.sleep(0.05)
        assert progress and progress["frames_completed"] >= 1, progress
        _data(connection.send_command("replicator.cancel_job", {"job_id": cancel_id, "preview": False}))
        cancelled = _wait_terminal(connection, cancel_id)
        assert cancelled["state"] == "cancelled", cancelled
        assert cancelled["frames_completed"] < 100, cancelled
        assert all(cancelled["cleanup"].values()), cancelled
        idle = _data(connection.send_command("replicator.get_status"))
        assert idle["active_job_count"] == 0 and idle["writer_attached"] is False and idle["trigger_active"] is False

        evidence = {
            "status": "success",
            "command_count": 113,
            "replicator_version": idle["extension"]["version"],
            "completed": {
                "frames": first["manifest"]["frames_completed"],
                "annotation_frame_counts": first["manifest"]["annotation_frame_counts"],
                "file_count": first["manifest"]["file_count"],
                "randomization_sha256": first["manifest"]["randomization_sha256"],
            },
            "repeat_seed_match": True,
            "cancelled": {
                "frames_completed": cancelled["frames_completed"],
                "frames_requested": cancelled["frames_requested"],
                "cleanup": cancelled["cleanup"],
            },
            "idle_readback": idle,
            "timeline_before": state_before["timeline_state"],
            "scene_prim_count_before": scene_before["prim_count"],
        }
    finally:
        _data(connection.send_command("simulation.stop"))
        for job_id in jobs:
            response = connection.send_command(
                "replicator.delete_job", {"job_id": job_id, "delete_artifacts": True, "preview": False}
            )
            if response["status"] != "success" and response.get("code") != "SDG_JOB_NOT_FOUND":
                raise RuntimeError(response)
        if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))
        absent = connection.send_command("scene.get_prim_info", {"prim_path": ROOT})
        assert absent["status"] == "error", absent
        final_status = _data(connection.send_command("replicator.get_status"))
        final_state = _data(connection.send_command("simulation.get_state"))
        assert final_status["job_count"] == 0 and final_status["active_job_count"] == 0, final_status
        assert final_state["timeline_state"] == "stopped", final_state
        evidence["fixture_absent"] = True
        evidence["job_count_after"] = final_status["job_count"]
        evidence["timeline_after"] = final_state["timeline_state"]
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
