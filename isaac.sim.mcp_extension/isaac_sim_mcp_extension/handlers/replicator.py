# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Bounded Replicator/SDG jobs with deterministic typed randomization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..artifact_store import ArtifactError, get_artifact_store

ANNOTATIONS = {
    "rgb",
    "semantic_segmentation",
    "instance_segmentation",
    "instance_id_segmentation",
}
UNAVAILABLE_ANNOTATIONS = {
    "bounding_box_2d_tight": "Isaac Sim 6.0.1 BasicWriter NumPy backend passes removed fix_imports argument",
    "bounding_box_2d_loose": "Isaac Sim 6.0.1 BasicWriter NumPy backend passes removed fix_imports argument",
    "bounding_box_3d": "Isaac Sim 6.0.1 BasicWriter NumPy backend passes removed fix_imports argument",
    "distance_to_camera": "not live-verified with this Isaac Sim 6.0.1 writer runtime",
    "distance_to_image_plane": "not live-verified with this Isaac Sim 6.0.1 writer runtime",
    "occlusion": "not live-verified with this Isaac Sim 6.0.1 writer runtime",
    "normals": "not live-verified with this Isaac Sim 6.0.1 writer runtime",
    "motion_vectors": "not live-verified with this Isaac Sim 6.0.1 writer runtime",
    "camera_params": "not live-verified with this Isaac Sim 6.0.1 writer runtime",
}
TERMINAL_STATES = {"completed", "cancelled", "error"}
MAX_FRAMES = 1000
MAX_PIXELS = 4096 * 4096
MAX_JOBS = 32
_JOBS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_JOB: Optional[str] = None


def register(registry: Dict[str, Any], _adapter: Any) -> None:
    registry["replicator.get_status"] = lambda **p: get_status(**p)
    registry["replicator.create_job"] = lambda **p: create_job(**p)
    registry["replicator.start_job"] = lambda **p: start_job(**p)
    registry["replicator.get_job_status"] = lambda **p: get_job_status(**p)
    registry["replicator.cancel_job"] = lambda **p: cancel_job(**p)
    registry["replicator.get_manifest"] = lambda **p: get_manifest(**p)
    registry["replicator.delete_job"] = lambda **p: delete_job(**p)


def _error(code: str, message: str, *, status: str = "error", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"status": status, "code": code, "message": message, "applied": False, "data": data or {}}


def _success(data: Dict[str, Any], *, readback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "success", "code": "OK", "data": data}
    if readback is not None:
        result["readback"] = readback
    return result


def _finite_vector(name: str, value: Iterable[Any], length: int = 3) -> List[float]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a numeric list")
    result = list(value)
    if len(result) != length or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in result
    ):
        raise ValueError(f"{name} must contain exactly {length} finite numbers")
    return [float(item) for item in result]


def _range_pair(spec: Dict[str, Any], prefix: str, *, scalar: bool = False) -> Optional[List[Any]]:
    low_key, high_key = f"{prefix}_min", f"{prefix}_max"
    if low_key not in spec and high_key not in spec:
        return None
    if low_key not in spec or high_key not in spec:
        raise ValueError(f"{low_key} and {high_key} must be provided together")
    if scalar:
        low, high = spec[low_key], spec[high_key]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (low, high)):
            raise ValueError(f"{prefix} range must contain finite numbers")
        pair: List[Any] = [float(low), float(high)]
    else:
        pair = [_finite_vector(low_key, spec[low_key]), _finite_vector(high_key, spec[high_key])]
    if scalar and pair[0] > pair[1]:
        raise ValueError(f"{prefix}_min must not exceed {prefix}_max")
    if not scalar and any(low > high for low, high in zip(pair[0], pair[1])):
        raise ValueError(f"every {prefix}_min component must not exceed {prefix}_max")
    return pair


def _validate_randomizers(randomizers: Any) -> List[Dict[str, Any]]:
    if not isinstance(randomizers, list) or len(randomizers) > 32:
        raise ValueError("randomizers must be a list with at most 32 records")
    normalized = []
    for index, raw in enumerate(randomizers):
        if not isinstance(raw, dict) or raw.get("type") not in {"transform", "light"}:
            raise ValueError(f"randomizers[{index}].type must be 'transform' or 'light'")
        paths = raw.get("prim_paths")
        if not isinstance(paths, list) or not paths or len(paths) > 128:
            raise ValueError(f"randomizers[{index}].prim_paths must contain 1 through 128 paths")
        if any(not isinstance(path, str) or not path.startswith("/World/") for path in paths):
            raise ValueError(f"randomizers[{index}] prim paths must be below /World")
        record: Dict[str, Any] = {"type": raw["type"], "prim_paths": sorted(set(paths))}
        if raw["type"] == "transform":
            for key in ("position", "rotation", "scale"):
                value = _range_pair(raw, key)
                if value is not None:
                    record[f"{key}_range"] = value
            if len(record) == 2:
                raise ValueError(f"randomizers[{index}] transform has no ranges")
        else:
            intensity = _range_pair(raw, "intensity", scalar=True)
            color = _range_pair(raw, "color")
            if intensity is not None:
                record["intensity_range"] = intensity
            if color is not None:
                record["color_range"] = color
            if len(record) == 2:
                raise ValueError(f"randomizers[{index}] light has no ranges")
        normalized.append(record)
    return normalized


def _validate_config(**params: Any) -> Dict[str, Any]:
    camera = params.get("camera_prim_path")
    if not isinstance(camera, str) or not camera.startswith("/World/"):
        raise ValueError("camera_prim_path must be below /World")
    frame_count = params.get("frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or not 1 <= frame_count <= MAX_FRAMES:
        raise ValueError(f"frame_count must be an integer from 1 through {MAX_FRAMES}")
    annotations = params.get("annotations")
    if not isinstance(annotations, list) or not annotations or len(annotations) != len(set(annotations)):
        raise ValueError("annotations must be a non-empty list without duplicates")
    unknown = sorted(set(annotations) - ANNOTATIONS)
    if unknown:
        raise ValueError(f"unsupported annotations: {', '.join(unknown)}")
    resolution = params.get("resolution", [640, 480])
    if (
        not isinstance(resolution, list)
        or len(resolution) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 4096 for v in resolution)
        or resolution[0] * resolution[1] > MAX_PIXELS
    ):
        raise ValueError("resolution must be [width, height], each 1..4096 and at most 16777216 pixels")
    seed = params.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer from 0 through 4294967295")
    rt_subframes = params.get("rt_subframes", 1)
    if isinstance(rt_subframes, bool) or not isinstance(rt_subframes, int) or not 1 <= rt_subframes <= 64:
        raise ValueError("rt_subframes must be an integer from 1 through 64")
    delta_time = params.get("delta_time", 0.0)
    if isinstance(delta_time, bool) or not isinstance(delta_time, (int, float)) or not 0 <= delta_time <= 1.0:
        raise ValueError("delta_time must be a finite number from 0.0 through 1.0")
    return {
        "camera_prim_path": camera,
        "frame_count": frame_count,
        "annotations": sorted(annotations),
        "resolution": list(resolution),
        "seed": seed,
        "randomizers": _validate_randomizers(params.get("randomizers", [])),
        "rt_subframes": rt_subframes,
        "delta_time": float(delta_time),
        "trigger": {"mode": "manual", "count": frame_count},
        "writer": {"name": "BasicWriter", "managed_artifacts": True},
    }


def _public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"task", "writer", "render_product", "output_dir", "snapshots", "cancel_requested"}
    }


def get_status() -> Dict[str, Any]:
    extension = {"enabled": False, "version": None}
    orchestrator = "unavailable"
    try:
        import omni.kit.app
        import omni.replicator.core as rep

        manager = omni.kit.app.get_app().get_extension_manager()
        extension["enabled"] = bool(manager.is_extension_enabled("omni.replicator.core"))
        extension_id = manager.get_enabled_extension_id("omni.replicator.core")
        if extension_id:
            raw = manager.get_extension_dict(extension_id)
            raw = raw.get_dict() if hasattr(raw, "get_dict") else raw
            package = raw.get("package", {}) if isinstance(raw, dict) else {}
            package = package.get_dict() if hasattr(package, "get_dict") else package
            extension["version"] = package.get("version") if isinstance(package, dict) else None
        orchestrator = str(rep.orchestrator.get_status()).split(".")[-1].lower()
    except Exception:
        pass
    active = sum(job["state"] in {"starting", "running", "cancelling", "finalizing"} for job in _JOBS.values())
    return _success(
        {
            "extension": extension,
            "orchestrator_state": orchestrator,
            "job_count": len(_JOBS),
            "active_job_count": active,
            "active_job_id": _ACTIVE_JOB,
            "retained_job_ids": sorted(_JOBS),
            "writer_attached": _ACTIVE_JOB is not None,
            "trigger_active": _ACTIVE_JOB is not None,
            "supported_annotations": sorted(ANNOTATIONS),
            "unavailable_annotations": dict(UNAVAILABLE_ANNOTATIONS),
            "limits": {"max_frames": MAX_FRAMES, "max_jobs": MAX_JOBS, "max_pixels": MAX_PIXELS},
        }
    )


def create_job(preview: bool = True, **params: Any) -> Dict[str, Any]:
    try:
        config = _validate_config(**params)
    except (TypeError, ValueError) as exc:
        return _error("INVALID_SDG_CONFIG", str(exc))
    if preview:
        return _success({"preview": True, "would_create": config})
    if len(_JOBS) >= MAX_JOBS:
        return _error("SDG_JOB_LIMIT_REACHED", f"at most {MAX_JOBS} retained jobs are allowed")
    try:
        import omni.usd

        prim = omni.usd.get_context().get_stage().GetPrimAtPath(config["camera_prim_path"])
        if not prim or not prim.IsValid() or prim.GetTypeName() != "Camera":
            return _error("CAMERA_NOT_FOUND", f"camera prim not found: {config['camera_prim_path']}")
    except Exception as exc:
        return _error("REPLICATOR_RUNTIME_UNAVAILABLE", str(exc), status="unsupported")
    job_id = f"sdg-{uuid.uuid4().hex}"
    now = time.time()
    job = {
        "job_id": job_id,
        "state": "configured",
        "config": config,
        "frames_requested": config["frame_count"],
        "frames_completed": 0,
        "created_epoch": now,
        "started_epoch": None,
        "finished_epoch": None,
        "manifest": None,
        "artifacts": [],
        "cleanup": {"writer_detached": True, "render_product_destroyed": True, "trigger_removed": True},
        "cancel_requested": False,
        "task": None,
    }
    _JOBS[job_id] = job
    return _success(_public_job(job), readback={"job_exists": True, "state": "configured"})


def start_job(job_id: str, preview: bool = True) -> Dict[str, Any]:
    global _ACTIVE_JOB
    job = _JOBS.get(job_id)
    if job is None:
        return _error("SDG_JOB_NOT_FOUND", f"SDG job not found: {job_id}")
    if job["state"] != "configured":
        return _error("SDG_JOB_STATE_CONFLICT", f"job state must be configured, got {job['state']}")
    if _ACTIVE_JOB is not None:
        return _error("SDG_JOB_ALREADY_ACTIVE", f"another SDG job is active: {_ACTIVE_JOB}")
    if preview:
        return _success({"preview": True, "job_id": job_id, "would_start": True})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        return _error("REPLICATOR_RUNTIME_UNAVAILABLE", str(exc), status="unsupported")
    _ACTIVE_JOB = job_id
    job["state"] = "starting"
    job["started_epoch"] = time.time()
    job["cleanup"] = {"writer_detached": False, "render_product_destroyed": False, "trigger_removed": False}
    job["task"] = loop.create_task(_run_job(job))
    return _success(_public_job(job), readback={"active_job_id": _ACTIVE_JOB, "state": "starting"})


def get_job_status(job_id: str) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        return _error("SDG_JOB_NOT_FOUND", f"SDG job not found: {job_id}")
    return _success(_public_job(job))


def cancel_job(job_id: str, preview: bool = True) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        return _error("SDG_JOB_NOT_FOUND", f"SDG job not found: {job_id}")
    if job["state"] in TERMINAL_STATES:
        return _error("SDG_JOB_STATE_CONFLICT", f"job is already terminal: {job['state']}")
    if preview:
        return _success({"preview": True, "job_id": job_id, "would_cancel": True})
    if job["state"] == "configured":
        job["state"] = "cancelled"
        job["finished_epoch"] = time.time()
        job["manifest"] = _make_manifest(job)
    else:
        job["cancel_requested"] = True
        job["state"] = "cancelling"
    return _success(_public_job(job), readback={"state": job["state"]})


def get_manifest(job_id: str) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        return _error("SDG_JOB_NOT_FOUND", f"SDG job not found: {job_id}")
    if job["state"] not in TERMINAL_STATES or job.get("manifest") is None:
        return _error("SDG_MANIFEST_NOT_READY", f"job is not terminal: {job['state']}")
    return _success({"job_id": job_id, "manifest": job["manifest"], "artifacts": job["artifacts"]})


def delete_job(job_id: str, delete_artifacts: bool = False, preview: bool = True) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        return _error("SDG_JOB_NOT_FOUND", f"SDG job not found: {job_id}")
    if job["state"] not in TERMINAL_STATES and job["state"] != "configured":
        return _error("SDG_JOB_STATE_CONFLICT", f"active job cannot be deleted: {job['state']}")
    handles = [item["handle"] for item in job.get("artifacts", []) if item.get("handle")]
    manifest_handle = (job.get("manifest") or {}).get("artifact", {}).get("handle")
    if manifest_handle:
        handles.append(manifest_handle)
    if preview:
        return _success({"preview": True, "job_id": job_id, "would_delete_artifacts": handles if delete_artifacts else []})
    deleted = []
    if delete_artifacts:
        store = get_artifact_store()
        for handle in handles:
            try:
                store.delete(handle)
                deleted.append(handle)
            except ArtifactError as exc:
                if exc.code != "ARTIFACT_NOT_FOUND":
                    return _error(exc.code, str(exc), data={"deleted_handles": deleted})
    del _JOBS[job_id]
    return _success({"job_id": job_id, "deleted": True, "deleted_artifacts": deleted}, readback={"job_exists": False})


def _stage_attribute(path: str, name: str):
    import omni.usd

    prim = omni.usd.get_context().get_stage().GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        raise ValueError(f"randomizer prim not found: {path}")
    attr = prim.GetAttribute(name)
    if not attr or not attr.IsValid():
        raise ValueError(f"randomizer attribute not found: {path}.{name}")
    return attr


def _randomized_values(job: Dict[str, Any], frame: int, rng: random.Random) -> List[Dict[str, Any]]:
    trace = []
    snapshots = job.setdefault("snapshots", {})
    for spec in job["config"]["randomizers"]:
        for path in spec["prim_paths"]:
            values: Dict[str, Any] = {"prim_path": path, "type": spec["type"]}
            mappings = (
                [("position_range", "xformOp:translate"), ("rotation_range", "xformOp:rotateXYZ"), ("scale_range", "xformOp:scale")]
                if spec["type"] == "transform"
                else [("intensity_range", "intensity"), ("color_range", "color")]
            )
            for range_name, attr_name in mappings:
                if range_name not in spec:
                    continue
                attr = _stage_attribute(path, attr_name)
                key = f"{path}.{attr_name}"
                if key not in snapshots:
                    snapshots[key] = {"attribute": attr, "value": attr.Get()}
                low, high = spec[range_name]
                if isinstance(low, list):
                    value: Any = tuple(rng.uniform(a, b) for a, b in zip(low, high))
                    public_value: Any = list(value)
                else:
                    value = rng.uniform(low, high)
                    public_value = value
                if not attr.Set(value):
                    raise RuntimeError(f"failed to set randomizer attribute: {key}")
                values[attr_name] = public_value
            trace.append({"frame": frame, **values})
    return trace


def _restore_randomizers(job: Dict[str, Any]) -> None:
    for snapshot in job.get("snapshots", {}).values():
        snapshot["attribute"].Set(snapshot["value"])


def _make_manifest(job: Dict[str, Any], *, error: Optional[str] = None) -> Dict[str, Any]:
    files = [
        {
            key: item[key]
            for key in ("handle", "format", "mime_type", "size_bytes", "sha256", "relative_path")
            if key in item
        }
        for item in job.get("artifacts", [])
    ]
    by_format: Dict[str, int] = {}
    by_annotation: Dict[str, int] = {name: 0 for name in job["config"]["annotations"]}
    annotation_frames: Dict[str, set[int]] = {name: set() for name in job["config"]["annotations"]}
    for item in files:
        by_format[item["format"]] = by_format.get(item["format"], 0) + 1
        relative_path = item.get("relative_path", "")
        filename = Path(relative_path).name
        for annotation in sorted(by_annotation, key=len, reverse=True):
            if filename.startswith(annotation):
                by_annotation[annotation] += 1
                frame_match = re.search(r"(?:^|_)(\d+)(?:\.[^.]+)?$", filename)
                if frame_match:
                    annotation_frames[annotation].add(int(frame_match.group(1)))
                break
    manifest = {
        "schema_version": "1.0",
        "job_id": job["job_id"],
        "state": job["state"],
        "config": job["config"],
        "frames_requested": job["frames_requested"],
        "frames_completed": job["frames_completed"],
        "file_count": len(files),
        "files_by_format": by_format,
        "annotation_file_counts": by_annotation,
        "annotation_frame_counts": {name: len(frames) for name, frames in annotation_frames.items()},
        "files": files,
        "randomization_trace": job.get("randomization_trace", []),
        "randomization_sha256": hashlib.sha256(
            json.dumps(job.get("randomization_trace", []), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "cleanup": dict(job["cleanup"]),
        "error": error,
    }
    try:
        payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        artifact = get_artifact_store().write_bytes(
            payload,
            kind="sdg_manifest",
            format="json",
            mime_type="application/json",
            filename_prefix="sdg-manifest",
            metadata={"job_id": job["job_id"], "state": job["state"]},
        )
        manifest["artifact"] = artifact
    except Exception as exc:
        manifest["artifact_error"] = str(exc)
    return manifest


def _ingest_outputs(job: Dict[str, Any]) -> None:
    output_dir = Path(job["output_dir"])
    store = get_artifact_store()
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        suffix = path.suffix.lower().lstrip(".") or "bin"
        mime = {"png": "image/png", "json": "application/json", "npy": "application/octet-stream"}.get(
            suffix, "application/octet-stream"
        )
        artifact = store.write_bytes(
            path.read_bytes(),
            kind="sdg_output",
            format=suffix,
            mime_type=mime,
            filename_prefix="sdg-output",
            metadata={"job_id": job["job_id"], "relative_path": path.relative_to(output_dir).as_posix()},
        )
        job["artifacts"].append(artifact)


async def _run_job(job: Dict[str, Any]) -> None:
    global _ACTIVE_JOB
    writer = None
    render_product = None
    output_dir = Path(tempfile.gettempdir()) / "isaacsim-mcp" / "sdg" / job["job_id"]
    error = None
    capture_on_play = None
    terminal_state = "error"
    try:
        import carb.settings
        import omni.replicator.core as rep

        output_dir.mkdir(parents=True, exist_ok=False)
        job["output_dir"] = str(output_dir)
        settings = carb.settings.get_settings()
        capture_on_play = bool(settings.get_as_bool("/omni/replicator/captureOnPlay"))
        rep.orchestrator.set_capture_on_play(False)
        rep.set_global_seed(job["config"]["seed"])
        render_product = rep.create.render_product(job["config"]["camera_prim_path"], tuple(job["config"]["resolution"]))
        writer = rep.WriterRegistry.get("BasicWriter")
        writer.initialize(output_dir=str(output_dir), **{name: True for name in job["config"]["annotations"]})
        writer.attach([render_product])
        job["writer"] = writer
        job["render_product"] = render_product
        job["state"] = "running"
        job["randomization_trace"] = []
        rng = random.Random(job["config"]["seed"])
        for frame in range(job["frames_requested"]):
            if job["cancel_requested"]:
                terminal_state = "cancelled"
                job["state"] = "finalizing"
                break
            job["randomization_trace"].extend(_randomized_values(job, frame, rng))
            await rep.orchestrator.step_async(
                rt_subframes=job["config"]["rt_subframes"],
                pause_timeline=True,
                delta_time=job["config"]["delta_time"],
                wait_for_render=True,
            )
            job["frames_completed"] += 1
        if terminal_state != "cancelled":
            terminal_state = "completed"
            job["state"] = "finalizing"
        await rep.orchestrator.wait_until_complete_async()
    except asyncio.CancelledError:
        terminal_state = "cancelled"
        job["state"] = "finalizing"
    except Exception as exc:
        terminal_state = "error"
        job["state"] = "finalizing"
        error = str(exc)
        job["error"] = error
    finally:
        try:
            if writer is not None:
                writer.detach()
            job["cleanup"]["writer_detached"] = True
        except Exception as exc:
            error = error or f"writer detach failed: {exc}"
        try:
            if render_product is not None:
                render_product.destroy()
            job["cleanup"]["render_product_destroyed"] = True
        except Exception as exc:
            error = error or f"render product destroy failed: {exc}"
        try:
            _restore_randomizers(job)
            job["cleanup"]["trigger_removed"] = True
        except Exception as exc:
            error = error or f"randomizer restore failed: {exc}"
        if capture_on_play is not None:
            try:
                import omni.replicator.core as rep

                rep.orchestrator.set_capture_on_play(capture_on_play)
            except Exception:
                pass
        try:
            if output_dir.exists():
                _ingest_outputs(job)
        except Exception as exc:
            error = error or f"artifact ingestion failed: {exc}"
            terminal_state = "error"
        job["finished_epoch"] = time.time()
        job["state"] = terminal_state
        job["manifest"] = _make_manifest(job, error=error)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        job.pop("writer", None)
        job.pop("render_product", None)
        job.pop("output_dir", None)
        job.pop("snapshots", None)
        _ACTIVE_JOB = None
