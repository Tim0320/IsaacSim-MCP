"""Managed artifact command handlers."""

from __future__ import annotations

from typing import Any, Dict

from ..artifact_store import ArtifactError, get_artifact_store


def register(registry: Dict[str, Any], _adapter: Any) -> None:
    registry["artifacts.info"] = get_artifact_info
    registry["artifacts.read"] = read_artifact
    registry["artifacts.delete"] = delete_artifact
    registry["artifacts.cleanup"] = cleanup_artifacts


def _run(operation) -> Dict[str, Any]:
    try:
        return {"status": "success", "data": operation()}
    except ArtifactError as exc:
        return {"status": "error", "code": exc.code, "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "code": "ARTIFACT_OPERATION_FAILED", "message": str(exc)}


def get_artifact_info(handle: str) -> Dict[str, Any]:
    return _run(lambda: get_artifact_store().info(handle))


def read_artifact(handle: str, offset: int = 0, length: int = 256 * 1024) -> Dict[str, Any]:
    return _run(lambda: get_artifact_store().read(handle, offset=offset, length=length))


def delete_artifact(handle: str) -> Dict[str, Any]:
    return _run(lambda: get_artifact_store().delete(handle))


def cleanup_artifacts() -> Dict[str, Any]:
    return _run(lambda: get_artifact_store().cleanup_expired())
