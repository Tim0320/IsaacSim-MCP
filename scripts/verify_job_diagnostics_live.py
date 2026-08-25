#!/usr/bin/env python3
"""Guarded live acceptance for Tasks 5.3 and 5.4."""

from __future__ import annotations

import json
import socket
import time
import uuid

from isaac_mcp.connection import IsaacConnection

ROOT = "/World/MCP_Task_5_3_5_4"
CAMERA = f"{ROOT}/Camera"
COMMAND_ID = "task-5-4-diagnostic-probe"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _wait_stage(connection: IsaacConnection, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = connection.send_command("scene.get_info")
        if last["status"] == "success":
            return
        assert last["code"] == "STAGE_NOT_READY", last
        time.sleep(0.5)
    raise TimeoutError(f"Stage did not become ready: {last}")


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    connection = IsaacConnection(port=8766)
    evidence: dict = {}
    run_id = uuid.uuid4().hex
    sdg_job_id = None
    try:
        _wait_stage(connection)
        _data(connection.send_command("simulation.stop"))
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["runtime"]["isaac_sim_version"].startswith("6.0.1")
        assert capabilities["extension"]["command_count"] == 128
        assert capabilities["feature_flags"]["job.lifecycle"]["state"] == "supported"
        assert capabilities["feature_flags"]["diagnostics.correlation"]["state"] == "supported"
        assert capabilities["feature_flags"]["transport.limits"]["state"] == "supported"

        if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))

        created = connection.send_command(
            "sensors.create_camera",
            {"prim_path": CAMERA, "position": [2.0, 2.0, 2.0], "rotation": [0.0, 0.0, 135.0], "resolution": [64, 64]},
        )
        _data(created)

        _data(connection.send_command("simulation.play"))
        time.sleep(2.0)
        # A newly created RTX camera needs bounded retries while its render
        # product and first frame become available.
        warmup = None
        for _attempt in range(8):
            warmup = connection.send_command(
                "sensors.capture_image",
                {"prim_path": CAMERA, "return_mode": "metadata"},
            )
            if warmup["status"] == "success":
                break
            time.sleep(1.0)
        assert warmup and warmup["status"] == "success", warmup

        started = connection.send_command(
            "job.start",
            {
                "command_type": "sensors.capture_image",
                "params": {"prim_path": CAMERA, "return_mode": "metadata"},
                "deadline_ms": 60000,
            },
            command_id=f"task-5-3-start-{run_id}",
            idempotency_key=f"task-5-3-camera-capture-{run_id}",
        )
        job_id = _data(started)["job_id"]

        # Prove the job is owned by Kit rather than the client socket.
        connection.disconnect()
        connection = IsaacConnection(port=8766)
        terminal = None
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            status = connection.send_command("job.get_status", {"job_id": job_id})
            terminal = _data(status)
            if terminal["terminal"]:
                break
            time.sleep(0.1)
        assert terminal and terminal["state"] == "succeeded", terminal
        repeated = _data(connection.send_command("job.get_status", {"job_id": job_id}))
        assert repeated["result"] == terminal["result"]

        _data(connection.send_command("simulation.stop"))
        sdg_created = _data(
            connection.send_command(
                "replicator.create_job",
                {
                    "camera_prim_path": CAMERA,
                    "frame_count": 100,
                    "annotations": ["rgb"],
                    "resolution": [64, 64],
                    "seed": 534,
                    "randomizers": [],
                    "rt_subframes": 1,
                    "delta_time": 0.0,
                    "preview": False,
                },
            )
        )
        sdg_job_id = sdg_created["job_id"]
        _data(connection.send_command("replicator.start_job", {"job_id": sdg_job_id, "preview": False}))
        progress = None
        progress_deadline = time.monotonic() + 20.0
        while time.monotonic() < progress_deadline:
            progress = _data(connection.send_command("job.get_status", {"job_id": sdg_job_id}))
            if progress["frames_completed"] >= 1:
                break
            time.sleep(0.05)
        assert progress and progress["frames_completed"] >= 1, progress
        _data(connection.send_command("job.cancel", {"job_id": sdg_job_id}))
        cancel_deadline = time.monotonic() + 20.0
        while time.monotonic() < cancel_deadline:
            cancelled = _data(connection.send_command("job.get_status", {"job_id": sdg_job_id}))
            if cancelled["state"] in {"cancelled", "completed", "error"}:
                break
            time.sleep(0.05)
        assert cancelled["state"] == "cancelled", cancelled
        assert all(cancelled["cleanup"].values()), cancelled

        warning = connection.send_command(
            "simulation.execute_script",
            {
                "code": (
                    "import carb\n"
                    "carb.log_warn('MCP_TASK_5_4_WARNING')\n"
                    "print('token=synthetic-diagnostic-value')"
                ),
                "max_output_bytes": 4096,
            },
            command_id=COMMAND_ID,
        )
        _data(warning)
        logs = _data(
            connection.send_command(
                "simulation.get_logs",
                {"count": 100, "since_last_play": True, "filter_command_id": COMMAND_ID},
            )
        )
        records = logs["records"]
        assert any(item["source"] == "dispatcher" and item["command_id"] == COMMAND_ID for item in records)
        assert any(item["source"] == "kit" and "MCP_TASK_5_4_WARNING" in item["message"] for item in records)
        assert any(item["source"] == "stdout" and "token=[REDACTED]" in item["message"] for item in records)
        assert all("synthetic-diagnostic-value" not in json.dumps(item) for item in records)
        assert "synthetic-diagnostic-value" not in json.dumps(logs)

        denied = connection.send_command(
            "job.start",
            {"command_type": "simulation.execute_script", "params": {"code": "pass"}, "deadline_ms": 1000},
        )
        assert denied["code"] == "JOB_COMMAND_NOT_ALLOWED"

        evidence = {
            "runtime": capabilities["runtime"],
            "command_count": capabilities["extension"]["command_count"],
            "camera_warmup_status": warmup["status"],
            "job_id": job_id,
            "disconnect_requery_terminal": terminal["state"],
            "repeat_result_equal": repeated["result"] == terminal["result"],
            "unified_cancel": {
                "job_id": sdg_job_id,
                "state": cancelled["state"],
                "frames_completed": cancelled["frames_completed"],
                "cleanup": cancelled["cleanup"],
            },
            "diagnostic_record_count": len(records),
            "sources": sorted({item["source"] for item in records}),
            "redaction_verified": True,
            "allowlist_denial": denied["code"],
        }
    finally:
        try:
            connection.send_command("simulation.stop")
            if sdg_job_id:
                connection.send_command(
                    "replicator.delete_job",
                    {"job_id": sdg_job_id, "delete_artifacts": True, "preview": False},
                )
            connection.send_command("sensors.delete", {"prim_path": CAMERA, "post_delete_updates": 8})
            if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
                connection.send_command("objects.delete", {"prim_path": ROOT})
        finally:
            evidence["root_absent_after_cleanup"] = (
                connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "error"
            )
            evidence["timeline_after_cleanup"] = _data(connection.send_command("simulation.get_state"))["timeline_state"]
            evidence["port_8766_open"] = _port_open(8766)
            connection.disconnect()

    assert evidence["root_absent_after_cleanup"] is True, evidence
    assert evidence["timeline_after_cleanup"] == "stopped", evidence
    assert evidence["port_8766_open"] is True, evidence
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
