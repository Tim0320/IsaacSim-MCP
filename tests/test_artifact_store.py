"""Task 1.5 shared managed-artifact store contract."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from isaac_sim_mcp_extension.artifact_store import ArtifactError, ArtifactStore


def _store(tmp_path, **kwargs):
    return ArtifactStore(root=tmp_path, ttl_seconds=60, max_total_bytes=1024, max_artifact_bytes=512, **kwargs)


def test_managed_artifact_round_trips_metadata_and_chunks(tmp_path):
    store = _store(tmp_path, max_chunk_bytes=4)
    payload = b"abcdefghij"

    artifact = store.write_bytes(
        payload,
        kind="camera.rgb",
        format="png",
        mime_type="image/png",
        filename_prefix="camera",
        metadata={"dtype": "uint8", "shape": [1, 10, 1]},
    )

    assert artifact["handle"].startswith("artifact://managed/")
    assert artifact["managed"] is True
    assert artifact["size_bytes"] == len(payload)
    assert artifact["sha256"] == hashlib.sha256(payload).hexdigest()
    assert artifact["dtype"] == "uint8"
    assert artifact["shape"] == [1, 10, 1]
    assert artifact["expires_at"]

    first = store.read(artifact["handle"], offset=0, length=4)
    second = store.read(artifact["handle"], offset=4, length=4)
    final = store.read(artifact["handle"], offset=8, length=4)
    assert base64.b64decode(first["data_base64"]) == b"abcd"
    assert base64.b64decode(second["data_base64"]) == b"efgh"
    assert base64.b64decode(final["data_base64"]) == b"ij"
    assert first["next_offset"] == 4 and first["eof"] is False
    assert final["next_offset"] == 10 and final["eof"] is True


def test_handles_reject_traversal_and_unknown_ids(tmp_path):
    store = _store(tmp_path)

    for handle in ("artifact://managed/../secret", "artifact://managed/a/b", "file:///etc/passwd"):
        with pytest.raises(ArtifactError) as exc:
            store.info(handle)
        assert exc.value.code == "INVALID_ARTIFACT_HANDLE"

    with pytest.raises(ArtifactError) as exc:
        store.info("artifact://managed/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    assert exc.value.code == "ARTIFACT_NOT_FOUND"


def test_sidecar_cannot_escape_the_managed_root(tmp_path):
    store = _store(tmp_path)
    artifact = store.write_bytes(
        b"safe",
        kind="camera.rgb",
        format="png",
        mime_type="image/png",
        filename_prefix="camera",
    )
    artifact_id = artifact["id"]
    sidecar = tmp_path / f"{artifact_id}.json"
    value = json.loads(sidecar.read_text(encoding="utf-8"))
    value["storage_name"] = "../outside.bin"
    sidecar.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ArtifactError) as exc:
        store.read(artifact["handle"], offset=0, length=1)
    assert exc.value.code == "ARTIFACT_METADATA_INVALID"


def test_expired_artifact_is_removed_on_access(tmp_path):
    now = [100.0]
    store = ArtifactStore(
        root=tmp_path,
        ttl_seconds=5,
        max_total_bytes=1024,
        max_artifact_bytes=512,
        now=lambda: now[0],
    )
    artifact = store.write_bytes(
        b"expires",
        kind="lidar.point_cloud",
        format="npz",
        mime_type="application/x-npz",
        filename_prefix="lidar",
    )
    data_path = tmp_path / artifact["storage_name"]
    sidecar = tmp_path / f"{artifact['id']}.json"
    now[0] = 106.0

    with pytest.raises(ArtifactError) as exc:
        store.info(artifact["handle"])
    assert exc.value.code == "ARTIFACT_EXPIRED"
    assert not data_path.exists()
    assert not sidecar.exists()


def test_size_capacity_and_chunk_limits_have_stable_codes(tmp_path):
    store = ArtifactStore(
        root=tmp_path,
        ttl_seconds=60,
        max_total_bytes=6,
        max_artifact_bytes=4,
        max_chunk_bytes=2,
    )
    artifact = store.write_bytes(
        b"1234",
        kind="camera.rgb",
        format="png",
        mime_type="image/png",
        filename_prefix="camera",
    )

    with pytest.raises(ArtifactError) as exc:
        store.write_bytes(
            b"12345",
            kind="camera.rgb",
            format="png",
            mime_type="image/png",
            filename_prefix="camera",
        )
    assert exc.value.code == "ARTIFACT_TOO_LARGE"

    with pytest.raises(ArtifactError) as exc:
        store.write_bytes(
            b"789",
            kind="lidar.point_cloud",
            format="npz",
            mime_type="application/x-npz",
            filename_prefix="lidar",
        )
    assert exc.value.code == "ARTIFACT_CAPACITY_EXCEEDED"

    with pytest.raises(ArtifactError) as exc:
        store.read(artifact["handle"], offset=0, length=3)
    assert exc.value.code == "ARTIFACT_CHUNK_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "argument",
    ("ttl_seconds", "max_total_bytes", "max_artifact_bytes", "max_chunk_bytes"),
)
def test_explicit_non_positive_limits_are_rejected(tmp_path, argument):
    values = {
        "ttl_seconds": 60,
        "max_total_bytes": 1024,
        "max_artifact_bytes": 512,
        "max_chunk_bytes": 256,
    }
    values[argument] = 0

    with pytest.raises(ArtifactError) as exc:
        ArtifactStore(root=tmp_path, **values)

    assert exc.value.code == "ARTIFACT_CONFIG_INVALID"


def test_delete_and_cleanup_are_idempotently_safe(tmp_path):
    now = [10.0]
    store = ArtifactStore(
        root=tmp_path,
        ttl_seconds=2,
        max_total_bytes=1024,
        max_artifact_bytes=512,
        now=lambda: now[0],
    )
    first = store.write_bytes(
        b"first",
        kind="camera.rgb",
        format="png",
        mime_type="image/png",
        filename_prefix="camera",
    )
    now[0] = 11.0
    second = store.write_bytes(
        b"second",
        kind="lidar.point_cloud",
        format="npz",
        mime_type="application/x-npz",
        filename_prefix="lidar",
    )

    deleted = store.delete(second["handle"])
    assert deleted["deleted"] is True
    with pytest.raises(ArtifactError) as exc:
        store.delete(second["handle"])
    assert exc.value.code == "ARTIFACT_NOT_FOUND"

    now[0] = 12.5
    cleanup = store.cleanup_expired()
    assert cleanup["deleted_count"] == 1
    assert cleanup["deleted_ids"] == [first["id"]]
