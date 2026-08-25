#!/usr/bin/env python3
"""Guarded live acceptance for Tasks 5.1 and 5.2."""

from __future__ import annotations

import json
import socket
import time

from isaac_mcp.connection import IsaacConnection

ROOT = "/World/MCP_Task_5_1_5_2"
IDEMPOTENT_PRIM = f"{ROOT}/IdempotentCube"
TIMEOUT_PRIM = f"{ROOT}/MustStayAbsent"
ROLLBACK_PRIM = f"{ROOT}/RollbackTarget"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_stage(connection: IsaacConnection, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = connection.send_command("scene.get_info")
        if last["status"] == "success":
            return
        assert last["code"] == "STAGE_NOT_READY", last
        time.sleep(0.5)
    raise TimeoutError(f"Stage did not become ready within {timeout_s:g}s: {last}")


def main() -> int:
    connection = IsaacConnection(port=8766)
    evidence: dict = {}
    try:
        _wait_stage(connection)
        _data(connection.send_command("simulation.stop"))
        capabilities = _data(connection.send_command("system.get_capabilities"))
        assert capabilities["runtime"]["isaac_sim_version"].startswith("6.0.1"), capabilities["runtime"]
        assert capabilities["extension"]["command_count"] == 124, capabilities["extension"]
        assert capabilities["feature_flags"]["execute_script"]["state"] == "supported"
        assert capabilities["feature_flags"]["command.governance"]["state"] == "supported"

        if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))

        denied_cwd = connection.send_command(
            "simulation.execute_script", {"code": "result = 1", "cwd": "C:\\Windows"}
        )
        assert denied_cwd["code"] == "SCRIPT_POLICY_DENIED", denied_cwd

        denied_background = connection.send_command(
            "simulation.execute_script",
            {"code": "import threading\nthreading.Thread(target=lambda: None).start()"},
        )
        assert denied_background["code"] == "SCRIPT_POLICY_DENIED", denied_background

        output_limited = connection.send_command(
            "simulation.execute_script",
            {"code": "print('x' * 4096)", "max_output_bytes": 64},
        )
        assert output_limited["code"] == "SCRIPT_OUTPUT_LIMIT_EXCEEDED", output_limited
        assert len(output_limited["data"]["stdout"].encode("utf-8")) <= 64, output_limited

        timeout_code = f'''\ncount = 0\nwhile True:\n    count += 1\nfrom pxr import UsdGeom\nimport omni.usd\nUsdGeom.Xform.Define(omni.usd.get_context().get_stage(), "{TIMEOUT_PRIM}")\n'''
        timed_out = connection.send_command(
            "simulation.execute_script",
            {"code": timeout_code, "timeout_s": 0.05, "max_output_bytes": 256},
        )
        assert timed_out["status"] == "timeout" and timed_out["code"] == "SCRIPT_TIMEOUT", timed_out
        assert connection.send_command("scene.get_prim_info", {"prim_path": TIMEOUT_PRIM})["status"] == "error"

        create_params = {
            "object_type": "Cube",
            "prim_path": IDEMPOTENT_PRIM,
            "position": [0.0, 0.0, 0.5],
            "size": 0.25,
        }
        first = connection.send_command(
            "objects.create", create_params, command_id="task-5-create-1", idempotency_key="task-5-create"
        )
        replay = connection.send_command(
            "objects.create", create_params, command_id="task-5-create-2", idempotency_key="task-5-create"
        )
        assert first["status"] == replay["status"] == "success", (first, replay)
        assert first["data"]["command"]["replayed"] is False
        assert replay["data"]["command"]["replayed"] is True
        assert replay["data"]["command"]["original_command_id"] == "task-5-create-1"
        assert _data(connection.send_command("scene.get_prim_info", {"prim_path": IDEMPOTENT_PRIM}))["path"] == IDEMPOTENT_PRIM

        conflict = connection.send_command(
            "objects.create",
            {**create_params, "size": 0.5},
            command_id="task-5-create-3",
            idempotency_key="task-5-create",
        )
        assert conflict["code"] == "IDEMPOTENCY_KEY_CONFLICT", conflict

        fixture_code = f'''\nfrom pxr import UsdGeom\nimport omni.usd\nstage = omni.usd.get_context().get_stage()\nUsdGeom.Xform.Define(stage, "{ROOT}")\nvariant = UsdGeom.Xform.Define(stage, "{ROOT}/Variant").GetPrim()\nvariants = variant.GetVariantSets().AddVariantSet("shape")\nvariants.AddVariant("box")\nvariants.SetVariantSelection("box")\n'''
        _data(connection.send_command("simulation.execute_script", {"code": fixture_code}))
        rolled_back = connection.send_command(
            "stage.apply_batch",
            {
                "operations": [
                    {
                        "operation": "set_attribute",
                        "prim_path": ROOT,
                        "attribute": "mcp:rollbackProbe",
                        "type_name": "string",
                        "value": "must-disappear",
                    },
                    {
                        "operation": "set_variant",
                        "prim_path": f"{ROOT}/Variant",
                        "variant_set": "shape",
                        "selection": "missing",
                    },
                ],
                "preview": False,
                "readback_root_path": ROOT,
            },
            idempotency_key="task-5-rollback",
        )
        assert rolled_back["code"] == "BATCH_ROLLED_BACK", rolled_back
        assert rolled_back["readback"]["rolled_back"] is True, rolled_back
        absent = connection.send_command(
            "stage.get_attribute", {"prim_path": ROOT, "attribute": "mcp:rollbackProbe"}
        )
        assert absent["code"] == "ATTRIBUTE_NOT_FOUND", absent

        audit = _data(connection.send_command("simulation.get_script_audit", {"count": 20}))
        assert audit["count"] >= 5, audit
        assert all("target_sha256" in item and "code" not in item for item in audit["records"]), audit

        evidence = {
            "runtime": capabilities["runtime"],
            "command_count": capabilities["extension"]["command_count"],
            "script_policy": capabilities["feature_flags"]["execute_script"]["policy"],
            "cwd_denied": denied_cwd["code"],
            "background_denied": denied_background["code"],
            "output_limited": output_limited["code"],
            "timed_out": timed_out["code"],
            "timeout_postcondition_absent": True,
            "idempotency_replayed": replay["data"]["command"],
            "idempotency_conflict": conflict["code"],
            "transaction": {"code": rolled_back["code"], "readback": rolled_back["readback"]},
            "audit_records": audit["count"],
        }
    finally:
        try:
            connection.send_command("simulation.stop")
            if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
                connection.send_command("objects.delete", {"prim_path": ROOT})
        finally:
            evidence["root_absent_after_cleanup"] = (
                connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "error"
            )
            evidence["timeline_after_cleanup"] = _data(connection.send_command("simulation.get_state"))[
                "timeline_state"
            ]
            evidence["port_8766_open"] = _port_open(8766)
            connection.disconnect()

    assert evidence["root_absent_after_cleanup"] is True, evidence
    assert evidence["timeline_after_cleanup"] == "stopped", evidence
    assert evidence["port_8766_open"] is True, evidence
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
