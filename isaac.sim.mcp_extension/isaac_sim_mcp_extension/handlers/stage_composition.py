# MIT License
# Copyright (c) 2026 whats2000

"""Typed, guarded USD stage, layer, composition, and metadata operations."""

from __future__ import annotations

import math
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ..adapters.base import IsaacAdapterBase

TYPE_NAMES = {
    "bool",
    "int",
    "int64",
    "float",
    "double",
    "string",
    "token",
    "asset",
    "float2",
    "float3",
    "double2",
    "double3",
    "color3f",
    "quatf",
    "matrix4d",
    "bool[]",
    "int[]",
    "int64[]",
    "float[]",
    "double[]",
    "string[]",
    "token[]",
    "asset[]",
}
ARC_TYPES = {"reference", "payload"}
ARC_ACTIONS = {"add", "clear", "load", "unload"}
BATCH_OPERATIONS = {"edit_sublayer", "edit_composition_arc", "set_variant", "set_semantics", "set_attribute"}


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["stage.new"] = lambda **p: new_stage(adapter, **p)
    registry["stage.open"] = lambda **p: open_stage(adapter, **p)
    registry["stage.save_as"] = lambda **p: save_stage_as(adapter, **p)
    registry["stage.get_composition"] = lambda **p: get_stage_composition(adapter, **p)
    registry["stage.edit_sublayer"] = lambda **p: edit_sublayer(adapter, **p)
    registry["stage.edit_composition_arc"] = lambda **p: edit_composition_arc(adapter, **p)
    registry["stage.set_variant"] = lambda **p: set_variant_selection(adapter, **p)
    registry["stage.get_semantics"] = lambda **p: get_semantic_labels(adapter, **p)
    registry["stage.set_semantics"] = lambda **p: set_semantic_labels(adapter, **p)
    registry["stage.get_attribute"] = lambda **p: get_typed_attribute(adapter, **p)
    registry["stage.set_attribute"] = lambda **p: set_typed_attribute(adapter, **p)
    registry["stage.apply_batch"] = lambda **p: apply_stage_batch(adapter, **p)


def _error(code: str, message: str, **data: Any) -> Dict[str, Any]:
    return {"status": "error", "code": code, "message": message, **data}


def _require_stopped(adapter: IsaacAdapterBase) -> Optional[Dict[str, Any]]:
    try:
        state = adapter.get_simulation_state()
    except Exception:
        return None
    timeline = str((state or {}).get("timeline_state") or (state or {}).get("state") or "").lower()
    playing = bool((state or {}).get("playing")) or timeline in {"playing", "play"}
    if playing:
        return _error("TIMELINE_NOT_STOPPED", "Stage composition writes require a stopped timeline")
    return None


def _resolved_path(path: str) -> Path:
    if not path or not str(path).strip():
        raise ValueError("A non-empty filesystem path is required")
    value = str(path).strip()
    if "://" in value:
        raise ValueError("Only local filesystem paths are accepted by guarded stage file operations")
    return Path(value).expanduser().resolve(strict=False)


def _guarded_path(path: str, scratch_root: str) -> Path:
    target = _resolved_path(path)
    root = _resolved_path(scratch_root)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path '{target}' is outside scratch_root '{root}'") from exc
    return target


def _require_scratch(scratch_stage: bool, scratch_root: Optional[str]) -> Optional[Dict[str, Any]]:
    if scratch_stage is not True:
        return _error("SCRATCH_STAGE_REQUIRED", "Set scratch_stage=true for destructive stage lifecycle operations")
    if not scratch_root:
        return _error(
            "SCRATCH_ROOT_REQUIRED", "scratch_root is required and must contain every opened or saved stage path"
        )
    try:
        root = _resolved_path(str(scratch_root))
    except (OSError, ValueError) as exc:
        return _error("INVALID_SCRATCH_ROOT", str(exc))
    if not root.is_dir():
        return _error("SCRATCH_ROOT_NOT_FOUND", f"scratch_root must be an existing directory: {root}")
    return None


def _stage_snapshot(stage) -> Dict[str, Any]:
    root = stage.GetRootLayer()
    session = stage.GetSessionLayer()
    return {
        "root": root.ExportToString(),
        "session": session.ExportToString() if session else None,
        "edit_target": stage.GetEditTarget().GetLayer().identifier,
        "load_rules": stage.GetLoadRules(),
    }


def _restore_stage(stage, snapshot: Mapping[str, Any]) -> None:
    stage.GetRootLayer().ImportFromString(str(snapshot["root"]))
    session = stage.GetSessionLayer()
    if session and snapshot.get("session") is not None:
        session.ImportFromString(str(snapshot["session"]))
    if snapshot.get("load_rules") is not None:
        stage.SetLoadRules(snapshot["load_rules"])


def _restore_context_stage(snapshot: Mapping[str, Any]) -> None:
    import omni.usd

    context = omni.usd.get_context()
    context.new_stage()
    stage = context.get_stage()
    _restore_stage(stage, snapshot)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "path"):
        return str(value.path)
    if hasattr(value, "GetArray"):
        value = value.GetArray()
    if hasattr(value, "GetReal") and hasattr(value, "GetImaginary"):
        imaginary = value.GetImaginary()
        return [float(value.GetReal()), *[float(imaginary[index]) for index in range(3)]]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [_json_value(item) for item in value]
    if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        items = [_json_value(value[index]) for index in range(len(value))]
        if items and all(isinstance(item, list) for item in items):
            return [nested for item in items for nested in item]
        return items
    return str(value)


def _prim(stage, prim_path: str):
    from pxr import Sdf

    if not Sdf.Path.IsValidPathString(str(prim_path)) or not str(prim_path).startswith("/"):
        raise ValueError(f"Invalid absolute prim path: {prim_path}")
    prim = stage.GetPrimAtPath(str(prim_path))
    if not prim or not prim.IsValid():
        raise ValueError(f"Prim does not exist: {prim_path}")
    return prim


def _layer_record(layer) -> Dict[str, Any]:
    return {
        "identifier": str(layer.identifier),
        "real_path": str(layer.realPath or ""),
        "anonymous": bool(layer.anonymous),
        "dirty": bool(layer.dirty),
        "sub_layer_paths": list(layer.subLayerPaths),
    }


def _arc_items(prim, arc_type: str) -> list[Dict[str, str]]:
    metadata = prim.GetMetadata("references" if arc_type == "reference" else "payload")
    if metadata is None:
        return []
    items = []
    for item in list(metadata.GetAddedOrExplicitItems()):
        items.append({"asset_path": str(item.assetPath), "prim_path": str(item.primPath)})
    return items


def new_stage(
    adapter: IsaacAdapterBase,
    scratch_stage: bool = False,
    scratch_root: Optional[str] = None,
    preview: bool = True,
) -> Dict[str, Any]:
    guarded = _require_scratch(scratch_stage, scratch_root)
    if guarded:
        return guarded
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    operation = {"operation": "new_stage", "scratch_root": str(_resolved_path(str(scratch_root)))}
    if preview:
        return {"status": "success", "message": "New stage preview validated", "data": {"preview": True, **operation}}
    try:
        import omni.usd

        context = omni.usd.get_context()
        snapshot = _stage_snapshot(adapter.get_stage())
        if not context.new_stage():
            raise RuntimeError("Isaac Sim did not create a new stage")
        readback = get_stage_composition(adapter)
        if readback.get("status") != "success":
            raise RuntimeError(f"New-stage read-back failed: {readback}")
        return {
            "status": "success",
            "message": "New scratch stage created",
            "data": operation,
            "readback": readback.get("data"),
        }
    except Exception as exc:
        if "snapshot" in locals():
            _restore_context_stage(snapshot)
        return _error("NEW_STAGE_FAILED", str(exc), readback={"rolled_back": "snapshot" in locals()})


def open_stage(
    adapter: IsaacAdapterBase,
    path: str,
    scratch_stage: bool = False,
    scratch_root: Optional[str] = None,
    preview: bool = True,
    readback_root_path: str = "/",
) -> Dict[str, Any]:
    guarded = _require_scratch(scratch_stage, scratch_root)
    if guarded:
        return guarded
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        target = _guarded_path(path, str(scratch_root))
    except ValueError as exc:
        return _error("PATH_OUTSIDE_SCRATCH_ROOT", str(exc))
    if not target.is_file():
        return _error("STAGE_FILE_NOT_FOUND", f"Stage file does not exist: {target}")
    if target.suffix.lower() not in {".usd", ".usda", ".usdc"}:
        return _error("INVALID_STAGE_EXTENSION", "open_stage requires a .usd, .usda, or .usdc source")
    operation = {"operation": "open_stage", "path": str(target), "scratch_root": str(_resolved_path(str(scratch_root)))}
    if preview:
        return {"status": "success", "message": "Open stage preview validated", "data": {"preview": True, **operation}}
    try:
        import omni.usd

        context = omni.usd.get_context()
        snapshot = _stage_snapshot(adapter.get_stage())
        if not context.open_stage(str(target)):
            raise RuntimeError(f"Isaac Sim did not open stage: {target}")
        readback = get_stage_composition(adapter, root_path=readback_root_path)
        if readback.get("status") != "success":
            raise RuntimeError(f"Open-stage composition read-back failed: {readback}")
        opened = Path(str(adapter.get_stage().GetRootLayer().realPath)).resolve(strict=False)
        if opened != target:
            raise RuntimeError(f"Open-stage read-back mismatch: expected '{target}', read back '{opened}'")
        return {
            "status": "success",
            "message": "Scratch stage opened",
            "data": operation,
            "readback": readback.get("data"),
        }
    except Exception as exc:
        if "snapshot" in locals():
            _restore_context_stage(snapshot)
        return _error("OPEN_STAGE_FAILED", str(exc), readback={"rolled_back": "snapshot" in locals()})


def save_stage_as(
    adapter: IsaacAdapterBase,
    path: str,
    scratch_stage: bool = False,
    scratch_root: Optional[str] = None,
    overwrite: bool = False,
    preview: bool = True,
    readback_root_path: str = "/",
) -> Dict[str, Any]:
    guarded = _require_scratch(scratch_stage, scratch_root)
    if guarded:
        return guarded
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        target = _guarded_path(path, str(scratch_root))
    except ValueError as exc:
        return _error("PATH_OUTSIDE_SCRATCH_ROOT", str(exc))
    if target.suffix.lower() not in {".usd", ".usda", ".usdc"}:
        return _error("INVALID_STAGE_EXTENSION", "save_stage_as requires a .usd, .usda, or .usdc target")
    stage = adapter.get_stage()
    current = str(stage.GetRootLayer().realPath or "")
    if current and _resolved_path(current) == target:
        return _error("SOURCE_OVERWRITE_FORBIDDEN", "save_stage_as cannot target the currently opened source layer")
    if target.exists() and not overwrite:
        return _error(
            "TARGET_EXISTS",
            f"Target already exists; set overwrite=true only for an intentional scratch overwrite: {target}",
        )
    operation = {"operation": "save_stage_as", "path": str(target), "overwrite": bool(overwrite)}
    if preview:
        return {"status": "success", "message": "Save-as preview validated", "data": {"preview": True, **operation}}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp{target.suffix}")
        if not stage.GetRootLayer().Export(str(temporary)):
            raise RuntimeError(f"USD layer export failed: {target}")
        from pxr import Usd

        temporary_stage = Usd.Stage.Open(str(temporary))
        if temporary_stage is None:
            raise RuntimeError(f"Temporary export could not be reopened: {temporary}")
        _composition_data(temporary_stage, root_path=readback_root_path)
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
            temporary.unlink()
        reopened = Usd.Stage.Open(str(target))
        if reopened is None:
            raise RuntimeError(f"Saved file could not be reopened: {target}")
        readback = _composition_data(reopened, root_path=readback_root_path)
        return {
            "status": "success",
            "message": "Stage saved to a new scratch file",
            "data": operation,
            "readback": readback,
        }
    except Exception as exc:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
        return _error("SAVE_STAGE_FAILED", str(exc))


def _composition_data(stage, root_path: str = "/") -> Dict[str, Any]:
    root = stage.GetRootLayer()
    prims = []
    variants = []
    arcs = []
    semantics = []
    if root_path == "/":
        traversal = stage.TraverseAll()
    else:
        from pxr import Usd

        traversal = Usd.PrimRange(_prim(stage, root_path))
    for prim in traversal:
        path = str(prim.GetPath())
        prims.append(path)
        selections = dict(prim.GetVariantSets().GetAllVariantSelections())
        if selections:
            variants.append({"prim_path": path, "selections": selections})
        for arc_type in ARC_TYPES:
            items = _arc_items(prim, arc_type)
            if items:
                arcs.append({"prim_path": path, "arc_type": arc_type, "items": items, "loaded": bool(prim.IsLoaded())})
        labels = _semantic_records(prim)
        if labels:
            semantics.append({"prim_path": path, "labels": labels})
    return {
        "root_layer": _layer_record(root),
        "query_root_path": root_path,
        "layer_stack": [_layer_record(layer) for layer in stage.GetLayerStack(includeSessionLayers=True)],
        "prim_count": len(prims),
        "prim_paths": prims,
        "composition_arcs": arcs,
        "variant_selections": variants,
        "semantic_labels": semantics,
        "metadata": {
            "default_prim": str(stage.GetDefaultPrim().GetPath()) if stage.GetDefaultPrim().IsValid() else None,
            "up_axis": str(stage.GetMetadata("upAxis") or ""),
            "meters_per_unit": stage.GetMetadata("metersPerUnit"),
            "time_codes_per_second": float(stage.GetTimeCodesPerSecond()),
        },
    }


def get_stage_composition(adapter: IsaacAdapterBase, root_path: str = "/") -> Dict[str, Any]:
    try:
        data = _composition_data(adapter.get_stage(), root_path=root_path)
        return {"status": "success", "message": "Stage composition read", "data": data, "readback": data}
    except Exception as exc:
        return _error("STAGE_COMPOSITION_READ_FAILED", str(exc))


def edit_sublayer(
    adapter: IsaacAdapterBase, action: str, layer_path: str, index: int = -1, preview: bool = True
) -> Dict[str, Any]:
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    action = str(action).lower()
    if action not in {"add", "remove"}:
        return _error("INVALID_SUBLAYER_ACTION", "action must be add or remove")
    if not layer_path or "://" in str(layer_path):
        return _error("INVALID_LAYER_PATH", "layer_path must be a non-empty local path")
    stage = adapter.get_stage()
    root = stage.GetRootLayer()
    paths = list(root.subLayerPaths)
    normalized = str(Path(layer_path).resolve(strict=False))
    operation = {"operation": "edit_sublayer", "action": action, "layer_path": normalized, "index": int(index)}
    if action == "add" and normalized in paths:
        return _error("SUBLAYER_ALREADY_PRESENT", f"Sublayer already present: {normalized}")
    if action == "add":
        from pxr import Sdf

        if not Path(normalized).is_file() or Sdf.Layer.FindOrOpen(normalized) is None:
            return _error(
                "SUBLAYER_NOT_FOUND", f"Sublayer file does not exist or is not a readable USD layer: {normalized}"
            )
    if action == "remove" and normalized not in paths:
        return _error("SUBLAYER_NOT_FOUND", f"Sublayer not present: {normalized}")
    if preview:
        return {
            "status": "success",
            "message": "Sublayer edit preview validated",
            "data": {"preview": True, **operation},
            "readback": {"sub_layer_paths": paths},
        }
    snapshot = root.ExportToString()
    try:
        if action == "add":
            insert_at = len(paths) if int(index) < 0 else int(index)
            if insert_at < 0 or insert_at > len(paths):
                return _error("INVALID_SUBLAYER_INDEX", f"index must be between 0 and {len(paths)}, or -1")
            paths.insert(insert_at, normalized)
        else:
            paths.remove(normalized)
        root.subLayerPaths = paths
        actual = list(root.subLayerPaths)
        if (action == "add") != (normalized in actual):
            raise RuntimeError("Sublayer read-back did not match the requested state")
        return {
            "status": "success",
            "message": f"Sublayer {action} applied",
            "data": operation,
            "readback": {"sub_layer_paths": actual},
        }
    except Exception as exc:
        root.ImportFromString(snapshot)
        return _error(
            "SUBLAYER_EDIT_FAILED",
            str(exc),
            readback={"rolled_back": True, "sub_layer_paths": list(root.subLayerPaths)},
        )


def edit_composition_arc(
    adapter: IsaacAdapterBase,
    prim_path: str,
    arc_type: str,
    action: str,
    asset_path: Optional[str] = None,
    target_prim_path: Optional[str] = None,
    preview: bool = True,
) -> Dict[str, Any]:
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    arc_type, action = str(arc_type).lower(), str(action).lower()
    if arc_type not in ARC_TYPES:
        return _error("INVALID_ARC_TYPE", "arc_type must be reference or payload")
    if action not in ARC_ACTIONS:
        return _error("INVALID_ARC_ACTION", "action must be add, clear, load, or unload")
    if action in {"load", "unload"} and arc_type != "payload":
        return _error("INVALID_ARC_ACTION", "load and unload apply only to payload arcs")
    if action == "add" and not asset_path:
        return _error("ASSET_PATH_REQUIRED", "asset_path is required when adding a composition arc")
    stage = adapter.get_stage()
    try:
        prim = _prim(stage, prim_path)
    except ValueError as exc:
        return _error("PRIM_NOT_FOUND", str(exc))
    operation = {
        "operation": "edit_composition_arc",
        "prim_path": prim_path,
        "arc_type": arc_type,
        "action": action,
        "asset_path": asset_path,
        "target_prim_path": target_prim_path,
    }
    before = _arc_items(prim, arc_type)
    if preview:
        return {
            "status": "success",
            "message": "Composition arc preview validated",
            "data": {"preview": True, **operation},
            "readback": {"items": before, "loaded": bool(prim.IsLoaded())},
        }
    snapshot = _stage_snapshot(stage)
    try:
        editor = prim.GetReferences() if arc_type == "reference" else prim.GetPayloads()
        if action == "add":
            kwargs = (str(asset_path), str(target_prim_path)) if target_prim_path else (str(asset_path),)
            applied = editor.AddReference(*kwargs) if arc_type == "reference" else editor.AddPayload(*kwargs)
            if applied is False:
                raise RuntimeError("USD rejected the composition arc")
        elif action == "clear":
            applied = editor.ClearReferences() if arc_type == "reference" else editor.ClearPayloads()
            if applied is False:
                raise RuntimeError("USD rejected clearing the composition arc")
        elif action == "load":
            prim.Load()
        else:
            prim.Unload()
        after = _arc_items(prim, arc_type)
        loaded = bool(prim.IsLoaded())
        if action == "add" and len(after) <= len(before):
            raise RuntimeError("Composition arc read-back did not include the new item")
        if action == "clear" and after:
            raise RuntimeError("Composition arc read-back was not empty")
        if action == "load" and not loaded:
            raise RuntimeError("Payload remained unloaded")
        if action == "unload" and loaded:
            raise RuntimeError("Payload remained loaded")
        return {
            "status": "success",
            "message": f"{arc_type} {action} applied",
            "data": operation,
            "readback": {"items": after, "loaded": loaded},
        }
    except Exception as exc:
        _restore_stage(stage, snapshot)
        return _error("COMPOSITION_ARC_EDIT_FAILED", str(exc), readback={"rolled_back": True})


def set_variant_selection(
    adapter: IsaacAdapterBase, prim_path: str, variant_set: str, selection: str, preview: bool = True
) -> Dict[str, Any]:
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    try:
        prim = _prim(adapter.get_stage(), prim_path)
        variant = prim.GetVariantSets().GetVariantSet(str(variant_set))
        names = list(variant.GetVariantNames())
    except Exception as exc:
        return _error("VARIANT_SET_NOT_FOUND", str(exc))
    if not names:
        return _error("VARIANT_SET_NOT_FOUND", f"Variant set '{variant_set}' does not exist on {prim_path}")
    if selection not in names:
        return _error("VARIANT_SELECTION_NOT_FOUND", f"Selection '{selection}' is not one of {names}")
    operation = {"operation": "set_variant", "prim_path": prim_path, "variant_set": variant_set, "selection": selection}
    if preview:
        return {
            "status": "success",
            "message": "Variant selection preview validated",
            "data": {"preview": True, **operation},
            "readback": {"available": names, "selection": variant.GetVariantSelection()},
        }
    previous = variant.GetVariantSelection()
    try:
        if not variant.SetVariantSelection(selection):
            raise RuntimeError("USD rejected the variant selection")
        actual = variant.GetVariantSelection()
        if actual != selection:
            raise RuntimeError(f"Variant read-back mismatch: {actual}")
        return {
            "status": "success",
            "message": "Variant selection applied",
            "data": operation,
            "readback": {"available": names, "selection": actual},
        }
    except Exception as exc:
        variant.SetVariantSelection(previous)
        return _error(
            "VARIANT_SELECTION_FAILED",
            str(exc),
            readback={"rolled_back": True, "selection": variant.GetVariantSelection()},
        )


def _semantic_records(prim) -> list[Dict[str, Any]]:
    records = []
    for name in prim.GetAppliedSchemas():
        text = str(name)
        if text.startswith("SemanticsLabelsAPI:"):
            from pxr import UsdSemantics

            taxonomy = text.split(":", 1)[1]
            labels = list(UsdSemantics.LabelsAPI(prim, taxonomy).GetLabelsAttr().Get() or [])
            records.append({"schema": "LabelsAPI", "taxonomy": taxonomy, "labels": [str(item) for item in labels]})
        elif text.startswith("SemanticsAPI:"):
            instance = text.split(":", 1)[1]
            label_type = prim.GetAttribute(f"semantic:{instance}:params:semanticType").Get()
            label = prim.GetAttribute(f"semantic:{instance}:params:semanticData").Get()
            records.append(
                {
                    "schema": "legacy_SemanticsAPI",
                    "taxonomy": str(label_type or instance),
                    "labels": [str(label)] if label else [],
                    "instance": instance,
                }
            )
    return records


def get_semantic_labels(adapter: IsaacAdapterBase, prim_path: str) -> Dict[str, Any]:
    try:
        labels = _semantic_records(_prim(adapter.get_stage(), prim_path))
        return {
            "status": "success",
            "message": "Semantic labels read",
            "data": {"prim_path": prim_path, "labels": labels},
            "readback": {"labels": labels},
        }
    except Exception as exc:
        return _error("SEMANTIC_READ_FAILED", str(exc))


def set_semantic_labels(
    adapter: IsaacAdapterBase,
    prim_path: str,
    taxonomy: str,
    labels: Sequence[str],
    overwrite: bool = False,
    preview: bool = True,
) -> Dict[str, Any]:
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    if not str(taxonomy).strip():
        return _error("INVALID_SEMANTIC_LABEL", "taxonomy must be a non-empty string")
    if isinstance(labels, (str, bytes)) or not isinstance(labels, Sequence) or not labels:
        return _error("INVALID_SEMANTIC_LABEL", "labels must be a non-empty array of strings")
    if any(not isinstance(item, str) for item in labels):
        return _error("INVALID_SEMANTIC_LABEL", "labels must contain only strings")
    normalized_labels = [item.strip() for item in labels]
    if any(not item for item in normalized_labels) or len(set(normalized_labels)) != len(normalized_labels):
        return _error("INVALID_SEMANTIC_LABEL", "labels must contain unique, non-empty strings")
    try:
        from pxr import UsdSemantics

        prim = _prim(adapter.get_stage(), prim_path)
        before = _semantic_records(prim)
        existing = next((item for item in before if item["taxonomy"] == taxonomy), None)
        operation = {
            "operation": "set_semantics",
            "prim_path": prim_path,
            "taxonomy": taxonomy,
            "labels": normalized_labels,
            "overwrite": bool(overwrite),
        }
        if preview:
            return {
                "status": "success",
                "message": "Semantic label preview validated",
                "data": {"preview": True, **operation},
                "readback": {"labels": before},
            }
        snapshot = _stage_snapshot(adapter.get_stage())
        api = UsdSemantics.LabelsAPI.Apply(prim, taxonomy)
        attr = api.GetLabelsAttr()
        applied_labels = normalized_labels
        if existing and not overwrite:
            applied_labels = list(existing["labels"])
            applied_labels.extend(item for item in normalized_labels if item not in applied_labels)
        if not attr.Set(applied_labels):
            raise RuntimeError("USD rejected the semantic labels")
        after = _semantic_records(prim)
        actual = next((item for item in after if item["taxonomy"] == taxonomy and item["schema"] == "LabelsAPI"), None)
        if not actual or actual["labels"] != applied_labels:
            raise RuntimeError("Semantic label read-back mismatch")
        return {
            "status": "success",
            "message": "Semantic label applied",
            "data": operation,
            "readback": {"labels": after},
        }
    except Exception as exc:
        if "snapshot" in locals():
            _restore_stage(adapter.get_stage(), snapshot)
        return _error("SEMANTIC_WRITE_FAILED", str(exc), readback={"rolled_back": "snapshot" in locals()})


def _type_name(type_name: str):
    from pxr import Sdf

    mapping = {
        "bool": Sdf.ValueTypeNames.Bool,
        "int": Sdf.ValueTypeNames.Int,
        "int64": Sdf.ValueTypeNames.Int64,
        "float": Sdf.ValueTypeNames.Float,
        "double": Sdf.ValueTypeNames.Double,
        "string": Sdf.ValueTypeNames.String,
        "token": Sdf.ValueTypeNames.Token,
        "asset": Sdf.ValueTypeNames.Asset,
        "float2": Sdf.ValueTypeNames.Float2,
        "float3": Sdf.ValueTypeNames.Float3,
        "double2": Sdf.ValueTypeNames.Double2,
        "double3": Sdf.ValueTypeNames.Double3,
        "color3f": Sdf.ValueTypeNames.Color3f,
        "quatf": Sdf.ValueTypeNames.Quatf,
        "matrix4d": Sdf.ValueTypeNames.Matrix4d,
        "bool[]": Sdf.ValueTypeNames.BoolArray,
        "int[]": Sdf.ValueTypeNames.IntArray,
        "int64[]": Sdf.ValueTypeNames.Int64Array,
        "float[]": Sdf.ValueTypeNames.FloatArray,
        "double[]": Sdf.ValueTypeNames.DoubleArray,
        "string[]": Sdf.ValueTypeNames.StringArray,
        "token[]": Sdf.ValueTypeNames.TokenArray,
        "asset[]": Sdf.ValueTypeNames.AssetArray,
    }
    return mapping[type_name]


def _typed_value(type_name: str, value: Any) -> Any:
    from pxr import Gf, Sdf

    if type_name.endswith("[]"):
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"{type_name} value must be an array")
        scalar_type = type_name[:-2]
        return [_typed_value(scalar_type, item) for item in value]
    if type_name == "bool":
        if not isinstance(value, bool):
            raise ValueError("bool value must be a JSON boolean")
        return value
    if type_name in {"int", "int64"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{type_name} value must be a JSON integer")
        return value
    if type_name in {"float", "double"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{type_name} value must be finite")
        return float(value)
    if type_name in {"string", "token"}:
        if not isinstance(value, str):
            raise ValueError(f"{type_name} value must be a string")
        return value
    if type_name == "asset":
        if not isinstance(value, str):
            raise ValueError("asset value must be a string path")
        return Sdf.AssetPath(value)
    sizes = {"float2": 2, "float3": 3, "double2": 2, "double3": 3, "color3f": 3, "quatf": 4, "matrix4d": 16}
    expected = sizes[type_name]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != expected:
        raise ValueError(f"{type_name} value must contain exactly {expected} finite numbers")
    values = [float(item) for item in value]
    if not all(math.isfinite(item) for item in values):
        raise ValueError(f"{type_name} value must contain only finite numbers")
    constructors = {
        "float2": Gf.Vec2f,
        "float3": Gf.Vec3f,
        "double2": Gf.Vec2d,
        "double3": Gf.Vec3d,
        "color3f": Gf.Vec3f,
        "quatf": lambda real, i, j, k: Gf.Quatf(real, Gf.Vec3f(i, j, k)),
        "matrix4d": lambda *items: Gf.Matrix4d(*items),
    }
    return constructors[type_name](*values)


def get_typed_attribute(adapter: IsaacAdapterBase, prim_path: str, attribute: str) -> Dict[str, Any]:
    try:
        attr = _prim(adapter.get_stage(), prim_path).GetAttribute(str(attribute))
        if not attr or not attr.IsValid():
            return _error("ATTRIBUTE_NOT_FOUND", f"Attribute '{attribute}' does not exist on {prim_path}")
        record = {
            "prim_path": prim_path,
            "attribute": attribute,
            "type_name": str(attr.GetTypeName()),
            "value": _json_value(attr.Get()),
            "authored": bool(attr.HasAuthoredValueOpinion()),
        }
        return {"status": "success", "message": "Typed attribute read", "data": record, "readback": record}
    except Exception as exc:
        return _error("ATTRIBUTE_READ_FAILED", str(exc))


def set_typed_attribute(
    adapter: IsaacAdapterBase,
    prim_path: str,
    attribute: str,
    type_name: str,
    value: Any,
    custom: bool = True,
    overwrite: bool = False,
    preview: bool = True,
) -> Dict[str, Any]:
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    type_name = str(type_name).lower()
    if type_name not in TYPE_NAMES:
        return _error("UNSUPPORTED_ATTRIBUTE_TYPE", f"type_name must be one of {sorted(TYPE_NAMES)}")
    if not attribute or not str(attribute).strip():
        return _error("INVALID_ATTRIBUTE_NAME", "attribute must be non-empty")
    try:
        prim = _prim(adapter.get_stage(), prim_path)
        typed = _typed_value(type_name, value)
        existing = prim.GetAttribute(str(attribute))
        if existing and existing.IsValid() and not overwrite:
            return _error(
                "ATTRIBUTE_EXISTS", f"Attribute '{attribute}' exists; set overwrite=true to replace its value"
            )
        if existing and existing.IsValid() and str(existing.GetTypeName()) != str(_type_name(type_name)):
            return _error(
                "ATTRIBUTE_TYPE_MISMATCH",
                f"Existing type is {existing.GetTypeName()}, requested {_type_name(type_name)}",
            )
        operation = {
            "operation": "set_attribute",
            "prim_path": prim_path,
            "attribute": attribute,
            "type_name": type_name,
            "value": value,
            "custom": bool(custom),
            "overwrite": bool(overwrite),
        }
        if preview:
            return {
                "status": "success",
                "message": "Typed attribute preview validated",
                "data": {"preview": True, **operation},
            }
        snapshot = _stage_snapshot(adapter.get_stage())
        attr = (
            existing
            if existing and existing.IsValid()
            else prim.CreateAttribute(str(attribute), _type_name(type_name), custom=bool(custom))
        )
        if not attr.Set(typed):
            raise RuntimeError("USD rejected the typed attribute value")
        record = get_typed_attribute(adapter, prim_path, attribute)
        if record.get("status") != "success":
            raise RuntimeError("Typed attribute could not be read back")
        return {
            "status": "success",
            "message": "Typed attribute applied",
            "data": operation,
            "readback": record["data"],
        }
    except Exception as exc:
        if "snapshot" in locals():
            _restore_stage(adapter.get_stage(), snapshot)
        return _error("ATTRIBUTE_WRITE_FAILED", str(exc), readback={"rolled_back": "snapshot" in locals()})


def _dispatch_batch_operation(adapter: IsaacAdapterBase, operation: Mapping[str, Any]) -> Dict[str, Any]:
    name = str(operation.get("operation") or "")
    params = {key: value for key, value in operation.items() if key != "operation"}
    params["preview"] = False
    handlers = {
        "edit_sublayer": edit_sublayer,
        "edit_composition_arc": edit_composition_arc,
        "set_variant": set_variant_selection,
        "set_semantics": set_semantic_labels,
        "set_attribute": set_typed_attribute,
    }
    return handlers[name](adapter, **params)


def apply_stage_batch(
    adapter: IsaacAdapterBase,
    operations: Sequence[Mapping[str, Any]],
    preview: bool = True,
    readback_root_path: str = "/",
) -> Dict[str, Any]:
    stopped = _require_stopped(adapter)
    if stopped:
        return stopped
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)) or not operations:
        return _error("INVALID_BATCH", "operations must be a non-empty array")
    if len(operations) > 100:
        return _error("BATCH_TOO_LARGE", "A stage batch is limited to 100 operations")
    normalized = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            return _error("INVALID_BATCH_OPERATION", f"Operation {index} must be an object")
        name = str(operation.get("operation") or "")
        if name not in BATCH_OPERATIONS:
            return _error("INVALID_BATCH_OPERATION", f"Operation {index} must be one of {sorted(BATCH_OPERATIONS)}")
        normalized.append(dict(operation))
    if preview:
        previews = []
        for index, operation in enumerate(normalized):
            name = operation["operation"]
            params = {key: value for key, value in operation.items() if key != "operation"}
            params["preview"] = True
            result = {
                "edit_sublayer": edit_sublayer,
                "edit_composition_arc": edit_composition_arc,
                "set_variant": set_variant_selection,
                "set_semantics": set_semantic_labels,
                "set_attribute": set_typed_attribute,
            }[name](adapter, **params)
            previews.append(
                {"index": index, "operation": name, "status": result.get("status"), "code": result.get("code", "OK")}
            )
            if result.get("status") != "success":
                return _error(
                    "BATCH_PREVIEW_FAILED",
                    f"Operation {index} failed validation: {result.get('message')}",
                    data={"operations": previews},
                )
        return {
            "status": "success",
            "message": "Batch preview validated",
            "data": {"preview": True, "operations": previews},
            "readback": get_stage_composition(adapter, root_path=readback_root_path).get("data"),
        }
    stage = adapter.get_stage()
    snapshot = _stage_snapshot(stage)
    results = []
    try:
        for index, operation in enumerate(normalized):
            result = _dispatch_batch_operation(adapter, operation)
            results.append(
                {
                    "index": index,
                    "operation": operation["operation"],
                    "status": result.get("status"),
                    "code": result.get("code", "OK"),
                    "readback": result.get("readback"),
                }
            )
            if result.get("status") != "success":
                raise RuntimeError(
                    f"Operation {index} failed: {result.get('code', 'COMMAND_FAILED')} {result.get('message', '')}"
                )
        composition = get_stage_composition(adapter, root_path=readback_root_path).get("data")
        return {
            "status": "success",
            "message": f"Applied {len(results)} stage operations atomically",
            "data": {"operations": results},
            "readback": composition,
        }
    except Exception as exc:
        _restore_stage(stage, snapshot)
        return _error(
            "BATCH_ROLLED_BACK",
            str(exc),
            data={"operations": results},
            readback={
                "rolled_back": True,
                "composition": get_stage_composition(adapter, root_path=readback_root_path).get("data"),
            },
        )
