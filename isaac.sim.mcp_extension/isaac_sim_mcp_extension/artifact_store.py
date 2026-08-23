"""Shared bounded artifact storage for Camera, LiDAR, and future producers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

ARTIFACT_ROOT_ENV = "ISAAC_MCP_ARTIFACT_ROOT"
ARTIFACT_TTL_ENV = "ISAAC_MCP_ARTIFACT_TTL_SECONDS"
ARTIFACT_MAX_TOTAL_ENV = "ISAAC_MCP_ARTIFACT_MAX_TOTAL_BYTES"
ARTIFACT_MAX_FILE_ENV = "ISAAC_MCP_ARTIFACT_MAX_FILE_BYTES"
ARTIFACT_MAX_CHUNK_ENV = "ISAAC_MCP_ARTIFACT_MAX_CHUNK_BYTES"

DEFAULT_TTL_SECONDS = 3600
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_CHUNK_BYTES = 1024 * 1024
DEFAULT_READ_LENGTH = 256 * 1024

_HANDLE = re.compile(r"^artifact://managed/([A-Za-z0-9_-]{32})$")
_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FORMAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,31}$")


class ArtifactError(ValueError):
    """Machine-readable artifact operation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArtifactError("ARTIFACT_CONFIG_INVALID", f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ArtifactError("ARTIFACT_CONFIG_INVALID", f"{name} must be a positive integer")
    return value


def _positive_int(value: Optional[int], env_name: str, default: int) -> int:
    if value is None:
        return _positive_int_env(env_name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArtifactError("ARTIFACT_CONFIG_INVALID", f"{env_name} must be a positive integer")
    return value


def _iso_timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


class ArtifactStore:
    """Persist managed bytes with sidecar metadata and bounded access."""

    def __init__(
        self,
        *,
        root: Optional[Path] = None,
        ttl_seconds: Optional[int] = None,
        max_total_bytes: Optional[int] = None,
        max_artifact_bytes: Optional[int] = None,
        max_chunk_bytes: Optional[int] = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        configured_root = os.environ.get(ARTIFACT_ROOT_ENV)
        selected_root = root or (
            Path(configured_root) if configured_root else Path(tempfile.gettempdir()) / "isaacsim-mcp" / "artifacts"
        )
        self.root = selected_root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = _positive_int(ttl_seconds, ARTIFACT_TTL_ENV, DEFAULT_TTL_SECONDS)
        self.max_total_bytes = _positive_int(max_total_bytes, ARTIFACT_MAX_TOTAL_ENV, DEFAULT_MAX_TOTAL_BYTES)
        self.max_artifact_bytes = _positive_int(max_artifact_bytes, ARTIFACT_MAX_FILE_ENV, DEFAULT_MAX_ARTIFACT_BYTES)
        self.max_chunk_bytes = _positive_int(max_chunk_bytes, ARTIFACT_MAX_CHUNK_ENV, DEFAULT_MAX_CHUNK_BYTES)
        if self.max_artifact_bytes > self.max_total_bytes:
            raise ArtifactError("ARTIFACT_CONFIG_INVALID", "artifact max file bytes cannot exceed total capacity")
        self._now = now

    def _parse_handle(self, handle: str) -> str:
        if not isinstance(handle, str):
            raise ArtifactError("INVALID_ARTIFACT_HANDLE", "artifact handle must be a string")
        match = _HANDLE.fullmatch(handle)
        if match is None:
            raise ArtifactError("INVALID_ARTIFACT_HANDLE", "expected artifact://managed/<32-character-id>")
        return match.group(1)

    def _sidecar_path(self, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.json"

    def _safe_storage_path(self, storage_name: Any) -> Path:
        if not isinstance(storage_name, str) or Path(storage_name).name != storage_name:
            raise ArtifactError("ARTIFACT_METADATA_INVALID", "artifact storage name is invalid")
        path = (self.root / storage_name).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactError("ARTIFACT_METADATA_INVALID", "artifact storage path escapes the managed root") from exc
        return path

    def _load(self, artifact_id: str) -> tuple[Dict[str, Any], Path, Path]:
        sidecar = self._sidecar_path(artifact_id)
        if not sidecar.is_file():
            raise ArtifactError("ARTIFACT_NOT_FOUND", f"managed artifact not found: {artifact_id}")
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArtifactError("ARTIFACT_METADATA_INVALID", f"artifact metadata is unreadable: {artifact_id}") from exc
        if metadata.get("id") != artifact_id:
            raise ArtifactError("ARTIFACT_METADATA_INVALID", "artifact metadata ID does not match its handle")
        data_path = self._safe_storage_path(metadata.get("storage_name"))
        if not data_path.is_file():
            raise ArtifactError("ARTIFACT_NOT_FOUND", f"managed artifact data not found: {artifact_id}")
        expires_epoch = metadata.get("expires_epoch")
        if not isinstance(expires_epoch, (int, float)):
            raise ArtifactError("ARTIFACT_METADATA_INVALID", "artifact expiry metadata is invalid")
        if self._now() >= float(expires_epoch):
            self._delete_paths(data_path, sidecar)
            raise ArtifactError("ARTIFACT_EXPIRED", f"managed artifact expired: {artifact_id}")
        return metadata, data_path, sidecar

    @staticmethod
    def _delete_paths(data_path: Path, sidecar: Path) -> None:
        if data_path.exists():
            data_path.unlink()
        if sidecar.exists():
            sidecar.unlink()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _current_bytes(self) -> int:
        total = 0
        for path in self.root.iterdir():
            if path.is_file() and path.suffix != ".json" and not path.name.startswith("."):
                total += path.stat().st_size
        return total

    def _public(self, metadata: Dict[str, Any], data_path: Path) -> Dict[str, Any]:
        value = {key: item for key, item in metadata.items() if key != "expires_epoch"}
        value["path"] = str(data_path)
        return value

    def write_bytes(
        self,
        data: bytes,
        *,
        kind: str,
        format: str,
        mime_type: str,
        filename_prefix: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(data, bytes):
            raise ArtifactError("ARTIFACT_DATA_INVALID", "artifact payload must be bytes")
        if not _PREFIX.fullmatch(filename_prefix) or not _FORMAT.fullmatch(format):
            raise ArtifactError("ARTIFACT_METADATA_INVALID", "artifact filename prefix or format is invalid")
        if len(data) > self.max_artifact_bytes:
            raise ArtifactError(
                "ARTIFACT_TOO_LARGE",
                f"artifact has {len(data)} bytes; maximum is {self.max_artifact_bytes}",
            )
        self.cleanup_expired()
        used = self._current_bytes()
        if used + len(data) > self.max_total_bytes:
            raise ArtifactError(
                "ARTIFACT_CAPACITY_EXCEEDED",
                f"artifact root would use {used + len(data)} bytes; capacity is {self.max_total_bytes}",
            )

        artifact_id = secrets.token_urlsafe(24)
        storage_name = f"{filename_prefix}-{artifact_id}.{format}"
        data_path = self._safe_storage_path(storage_name)
        sidecar = self._sidecar_path(artifact_id)
        created_epoch = float(self._now())
        expires_epoch = created_epoch + self.ttl_seconds
        supplied = dict(metadata or {})
        reserved = {
            "id",
            "handle",
            "kind",
            "managed",
            "storage_name",
            "format",
            "mime_type",
            "size_bytes",
            "sha256",
            "created_at",
            "expires_at",
            "expires_epoch",
            "ttl_seconds",
            "path",
        }
        supplied = {key: value for key, value in supplied.items() if key not in reserved}
        artifact = {
            **supplied,
            "id": artifact_id,
            "handle": f"artifact://managed/{artifact_id}",
            "kind": kind,
            "managed": True,
            "storage_name": storage_name,
            "format": format,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "created_at": _iso_timestamp(created_epoch),
            "expires_at": _iso_timestamp(expires_epoch),
            "expires_epoch": expires_epoch,
            "ttl_seconds": self.ttl_seconds,
        }
        encoded_metadata = json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            self._atomic_write(data_path, data)
            self._atomic_write(sidecar, encoded_metadata)
        except Exception:
            self._delete_paths(data_path, sidecar)
            raise
        return self._public(artifact, data_path)

    def info(self, handle: str) -> Dict[str, Any]:
        artifact_id = self._parse_handle(handle)
        metadata, data_path, _sidecar = self._load(artifact_id)
        actual_size = data_path.stat().st_size
        if actual_size != metadata.get("size_bytes"):
            raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "artifact size no longer matches metadata")
        return self._public(metadata, data_path)

    def read(self, handle: str, *, offset: int = 0, length: int = DEFAULT_READ_LENGTH) -> Dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ArtifactError("INVALID_ARTIFACT_RANGE", "offset must be a non-negative integer")
        if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
            raise ArtifactError("INVALID_ARTIFACT_RANGE", "length must be a positive integer")
        if length > self.max_chunk_bytes:
            raise ArtifactError(
                "ARTIFACT_CHUNK_LIMIT_EXCEEDED",
                f"requested {length} bytes; maximum chunk is {self.max_chunk_bytes}",
            )
        artifact_id = self._parse_handle(handle)
        metadata, data_path, _sidecar = self._load(artifact_id)
        size = data_path.stat().st_size
        if size != metadata.get("size_bytes"):
            raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "artifact size no longer matches metadata")
        if offset > size:
            raise ArtifactError("INVALID_ARTIFACT_RANGE", f"offset {offset} exceeds artifact size {size}")
        with data_path.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read(length)
        next_offset = offset + len(chunk)
        return {
            "handle": handle,
            "offset": offset,
            "length": len(chunk),
            "next_offset": next_offset,
            "eof": next_offset >= size,
            "total_size_bytes": size,
            "mime_type": metadata["mime_type"],
            "sha256": metadata["sha256"],
            "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
            "encoding": "base64",
            "data_base64": base64.b64encode(chunk).decode("ascii"),
        }

    def delete(self, handle: str) -> Dict[str, Any]:
        artifact_id = self._parse_handle(handle)
        metadata, data_path, sidecar = self._load(artifact_id)
        size = data_path.stat().st_size
        self._delete_paths(data_path, sidecar)
        return {"handle": handle, "id": metadata["id"], "deleted": True, "freed_bytes": size}

    def cleanup_expired(self) -> Dict[str, Any]:
        deleted_ids = []
        freed_bytes = 0
        now = self._now()
        for sidecar in sorted(self.root.glob("*.json")):
            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                expires_epoch = metadata.get("expires_epoch")
                artifact_id = metadata.get("id")
                if not isinstance(artifact_id, str) or not isinstance(expires_epoch, (int, float)):
                    continue
                if now < float(expires_epoch):
                    continue
                data_path = self._safe_storage_path(metadata.get("storage_name"))
                if data_path.exists():
                    freed_bytes += data_path.stat().st_size
                self._delete_paths(data_path, sidecar)
                deleted_ids.append(artifact_id)
            except (ArtifactError, OSError, ValueError):
                continue
        return {"deleted_count": len(deleted_ids), "deleted_ids": deleted_ids, "freed_bytes": freed_bytes}


def get_artifact_store() -> ArtifactStore:
    """Build a store from current environment settings."""
    return ArtifactStore()


def write_unmanaged_artifact(data: bytes, output_path: str, *, expected_suffix: str) -> Dict[str, Any]:
    """Atomically write an explicit user path without registering it as managed."""
    path = Path(output_path).expanduser().resolve()
    if path.suffix.lower() != expected_suffix:
        raise ArtifactError("INVALID_OUTPUT_PATH", f"output_path must end in {expected_suffix}")
    if not path.parent.is_dir():
        raise ArtifactError("INVALID_OUTPUT_PATH", f"output_path parent does not exist: {path.parent}")
    ArtifactStore._atomic_write(path, data)
    return {
        "id": uuid.uuid4().hex,
        "handle": None,
        "managed": False,
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "expires_at": None,
        "ttl_seconds": None,
    }
