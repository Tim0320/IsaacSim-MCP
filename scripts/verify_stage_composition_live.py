#!/usr/bin/env python3
"""Scratch-stage live acceptance for item 15 Stage/layer/composition contracts."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from isaac_mcp.connection import IsaacConnection

ROOT = "/World/MCP_Task_3_5"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _readback(response: dict) -> dict:
    assert response["status"] == "success", response
    assert isinstance(response.get("readback"), dict), response
    return response["readback"]


def _execute(connection: IsaacConnection, code: str) -> str:
    result = _data(connection.send_command("simulation.execute_script", {"code": code}))
    assert not result["stderr"], result
    return result["stdout"]


def _snapshot_code(root_snapshot: Path, session_snapshot: Path) -> str:
    return f"""
import json
import omni.usd
stage = omni.usd.get_context().get_stage()
root = stage.GetRootLayer()
session = stage.GetSessionLayer()
assert root.Export({str(root_snapshot)!r})
assert session.Export({str(session_snapshot)!r})
print(json.dumps({{
    "root_identifier": str(root.identifier),
    "root_real_path": str(root.realPath or ""),
    "root_anonymous": bool(root.anonymous),
    "prim_count": len(list(stage.TraverseAll())),
}}))
"""


def _restore_code(root_snapshot: Path, session_snapshot: Path) -> str:
    return f"""
import json
import omni.usd
from pathlib import Path
context = omni.usd.get_context()
assert context.new_stage()
stage = context.get_stage()
assert stage.GetRootLayer().ImportFromString(Path({str(root_snapshot)!r}).read_text(encoding="utf-8"))
assert stage.GetSessionLayer().ImportFromString(Path({str(session_snapshot)!r}).read_text(encoding="utf-8"))
print(json.dumps({{"prim_count": len(list(stage.TraverseAll())), "root_anonymous": bool(stage.GetRootLayer().anonymous)}}))
"""


def _fixture_code(scratch: Path) -> str:
    return f"""
import json
import omni.usd
from pxr import Usd, UsdGeom
stage = omni.usd.get_context().get_stage()
world = UsdGeom.Xform.Define(stage, "/World").GetPrim()
stage.SetDefaultPrim(world)
UsdGeom.Xform.Define(stage, {ROOT!r})
UsdGeom.Xform.Define(stage, {ROOT + "/Reference"!r})
UsdGeom.Xform.Define(stage, {ROOT + "/Payload"!r})
UsdGeom.Xform.Define(stage, {ROOT + "/Tagged"!r})
variant = UsdGeom.Xform.Define(stage, {ROOT + "/Variant"!r}).GetPrim()
variant_set = variant.GetVariantSets().AddVariantSet("shape")
for name in ("cube", "sphere"):
    variant_set.AddVariant(name)
variant_set.SetVariantSelection("cube")

sub = Usd.Stage.CreateNew({str(scratch / "sub.usda")!r})
UsdGeom.Xform.Define(sub, "/SubLayerPrim")
assert sub.GetRootLayer().Save()
reference = Usd.Stage.CreateNew({str(scratch / "reference.usda")!r})
asset = UsdGeom.Xform.Define(reference, "/Asset").GetPrim()
reference.SetDefaultPrim(asset)
assert reference.GetRootLayer().Save()
payload = Usd.Stage.CreateNew({str(scratch / "payload.usda")!r})
payload_asset = UsdGeom.Xform.Define(payload, "/PayloadAsset").GetPrim()
payload.SetDefaultPrim(payload_asset)
assert payload.GetRootLayer().Save()
print(json.dumps({{"root": {ROOT!r}, "prim_count": len(list(stage.TraverseAll()))}}))
"""


def _essential(composition: dict) -> dict:
    return {
        "sub_layer_paths": composition["root_layer"]["sub_layer_paths"],
        "prim_count": composition["prim_count"],
        "composition_arcs": composition["composition_arcs"],
        "variant_selections": composition["variant_selections"],
        "semantic_labels": composition["semantic_labels"],
        "metadata": composition["metadata"],
    }


def main() -> int:
    connection = IsaacConnection(port=8766)
    scratch = Path(tempfile.mkdtemp(prefix="isaacsim-mcp-task-3-5-"))
    root_snapshot = scratch / "original-root.usda"
    session_snapshot = scratch / "original-session.usda"
    restored = False
    evidence = {}
    try:
        _data(connection.send_command("simulation.stop"))
        capabilities = _data(connection.send_command("system.get_capabilities"))
        # Task 3.5 introduced an 88-command baseline. Later phases may add
        # commands, so keep this historical verifier forward-compatible while
        # still proving that the Stage composition contract is registered.
        assert capabilities["extension"]["command_count"] >= 88, capabilities["extension"]
        feature = capabilities["feature_flags"]["stage.composition"]
        assert feature["scratch_guarded_lifecycle"] is True
        assert feature["atomic_batch_rollback"] is True
        original = json.loads(_execute(connection, _snapshot_code(root_snapshot, session_snapshot)))

        denied = connection.send_command("stage.new", {"preview": False})
        assert denied["status"] == "error" and denied["code"] == "SCRATCH_STAGE_REQUIRED", denied
        preview = connection.send_command(
            "stage.new", {"scratch_stage": True, "scratch_root": str(scratch), "preview": True}
        )
        assert preview["status"] == "success" and preview["data"]["preview"] is True, preview
        _readback(
            connection.send_command(
                "stage.new", {"scratch_stage": True, "scratch_root": str(scratch), "preview": False}
            )
        )
        fixture = json.loads(_execute(connection, _fixture_code(scratch)))

        _readback(
            connection.send_command(
                "stage.edit_sublayer",
                {"action": "add", "layer_path": str(scratch / "sub.usda"), "preview": False},
            )
        )
        reference = _readback(
            connection.send_command(
                "stage.edit_composition_arc",
                {
                    "prim_path": f"{ROOT}/Reference",
                    "arc_type": "reference",
                    "action": "add",
                    "asset_path": str(scratch / "reference.usda"),
                    "preview": False,
                },
            )
        )
        payload = _readback(
            connection.send_command(
                "stage.edit_composition_arc",
                {
                    "prim_path": f"{ROOT}/Payload",
                    "arc_type": "payload",
                    "action": "add",
                    "asset_path": str(scratch / "payload.usda"),
                    "preview": False,
                },
            )
        )
        unloaded = _readback(
            connection.send_command(
                "stage.edit_composition_arc",
                {"prim_path": f"{ROOT}/Payload", "arc_type": "payload", "action": "unload", "preview": False},
            )
        )
        loaded = _readback(
            connection.send_command(
                "stage.edit_composition_arc",
                {"prim_path": f"{ROOT}/Payload", "arc_type": "payload", "action": "load", "preview": False},
            )
        )
        assert unloaded["loaded"] is False and loaded["loaded"] is True

        variant = _readback(
            connection.send_command(
                "stage.set_variant",
                {"prim_path": f"{ROOT}/Variant", "variant_set": "shape", "selection": "sphere", "preview": False},
            )
        )
        semantics = _readback(
            connection.send_command(
                "stage.set_semantics",
                {
                    "prim_path": f"{ROOT}/Tagged",
                    "taxonomy": "class",
                    "labels": ["fixture", "obstacle"],
                    "preview": False,
                },
            )
        )
        attribute = _readback(
            connection.send_command(
                "stage.set_attribute",
                {
                    "prim_path": f"{ROOT}/Tagged",
                    "attribute": "mcp:testVector",
                    "type_name": "float3",
                    "value": [1, 2, 3],
                    "preview": False,
                },
            )
        )
        assert attribute["value"] == [1.0, 2.0, 3.0]
        array_attribute = _readback(
            connection.send_command(
                "stage.set_attribute",
                {
                    "prim_path": f"{ROOT}/Tagged",
                    "attribute": "mcp:testArray",
                    "type_name": "double[]",
                    "value": [0.25, 0.5],
                    "preview": False,
                },
            )
        )
        assert array_attribute["value"] == [0.25, 0.5]

        valid_batch = [
            {
                "operation": "set_attribute",
                "prim_path": f"{ROOT}/Tagged",
                "attribute": "mcp:batch",
                "type_name": "string",
                "value": "applied",
            },
            {
                "operation": "set_semantics",
                "prim_path": f"{ROOT}/Tagged",
                "taxonomy": "role",
                "labels": ["acceptance_fixture"],
            },
        ]
        batch_preview = connection.send_command(
            "stage.apply_batch", {"operations": valid_batch, "preview": True, "readback_root_path": ROOT}
        )
        assert batch_preview["status"] == "success" and batch_preview["data"]["preview"] is True
        batch = _readback(
            connection.send_command(
                "stage.apply_batch", {"operations": valid_batch, "preview": False, "readback_root_path": ROOT}
            )
        )
        assert batch["query_root_path"] == ROOT

        invalid_batch = [
            {
                "operation": "set_attribute",
                "prim_path": f"{ROOT}/Tagged",
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
        ]
        rolled_back = connection.send_command(
            "stage.apply_batch", {"operations": invalid_batch, "preview": False, "readback_root_path": ROOT}
        )
        assert rolled_back["status"] == "error" and rolled_back["code"] == "BATCH_ROLLED_BACK", rolled_back
        absent = connection.send_command(
            "stage.get_attribute", {"prim_path": f"{ROOT}/Tagged", "attribute": "mcp:rollbackProbe"}
        )
        assert absent["status"] == "error" and absent["code"] == "ATTRIBUTE_NOT_FOUND", absent

        before_save = _data(connection.send_command("stage.get_composition", {"root_path": ROOT}))
        output = scratch / "saved-stage.usda"
        save_preview = connection.send_command(
            "stage.save_as",
            {"path": str(output), "scratch_stage": True, "scratch_root": str(scratch), "preview": True},
        )
        assert save_preview["status"] == "success" and save_preview["data"]["preview"] is True
        saved = _readback(
            connection.send_command(
                "stage.save_as",
                {
                    "path": str(output),
                    "scratch_stage": True,
                    "scratch_root": str(scratch),
                    "preview": False,
                    "readback_root_path": ROOT,
                },
            )
        )
        assert output.is_file()
        nested_scratch = scratch / "nested"
        nested_scratch.mkdir()
        outside = connection.send_command(
            "stage.open",
            {
                "path": str(output),
                "scratch_stage": True,
                "scratch_root": str(nested_scratch),
                "preview": True,
            },
        )
        assert outside["status"] == "error" and outside["code"] == "PATH_OUTSIDE_SCRATCH_ROOT", outside
        _readback(
            connection.send_command(
                "stage.open",
                {
                    "path": str(output),
                    "scratch_stage": True,
                    "scratch_root": str(scratch),
                    "preview": False,
                    "readback_root_path": ROOT,
                },
            )
        )
        reopened = _data(connection.send_command("stage.get_composition", {"root_path": ROOT}))
        assert _essential(saved) == _essential(reopened)
        assert _essential(before_save) == _essential(reopened)
        source_overwrite = connection.send_command(
            "stage.save_as",
            {
                "path": str(output),
                "scratch_stage": True,
                "scratch_root": str(scratch),
                "overwrite": True,
                "preview": False,
            },
        )
        assert source_overwrite["status"] == "error" and source_overwrite["code"] == "SOURCE_OVERWRITE_FORBIDDEN"

        restored_info = json.loads(_execute(connection, _restore_code(root_snapshot, session_snapshot)))
        restored = True
        assert restored_info["prim_count"] == original["prim_count"], (restored_info, original)
        assert restored_info["root_anonymous"] is True
        health = _data(connection.send_command("scene.get_info"))
        state = _data(connection.send_command("simulation.get_state"))
        assert state["timeline_state"] == "stopped"
        evidence = {
            "command_count": capabilities["extension"]["command_count"],
            "original_stage": original,
            "restored_stage": restored_info,
            "fixture": fixture,
            "reference": reference,
            "payload": payload,
            "variant": variant,
            "semantics": semantics,
            "typed_attribute": attribute,
            "array_attribute": array_attribute,
            "batch_operation_count": len(valid_batch),
            "rollback_code": rolled_back["code"],
            "saved_path": str(output),
            "saved_prim_count": saved["prim_count"],
            "reopened_prim_count": reopened["prim_count"],
            "restored_live_prim_count": health["prim_count"],
            "timeline_state": state["timeline_state"],
        }
        print(json.dumps({"status": "success", "scratch_root": ROOT, "evidence": evidence}, indent=2))
        return 0
    finally:
        if not restored and root_snapshot.is_file() and session_snapshot.is_file():
            try:
                _execute(connection, _restore_code(root_snapshot, session_snapshot))
            except Exception as exc:
                print(json.dumps({"status": "restore_failed", "message": str(exc)}), flush=True)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
