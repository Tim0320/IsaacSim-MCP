"""Extension command handlers for the shared artifact provider."""

from __future__ import annotations

import base64

from isaac_sim_mcp_extension.artifact_store import ArtifactStore
from isaac_sim_mcp_extension.handlers import artifacts


def test_info_read_delete_and_error_envelopes(tmp_path, monkeypatch):
    store = ArtifactStore(root=tmp_path, ttl_seconds=60, max_total_bytes=1024, max_artifact_bytes=512)
    artifact = store.write_bytes(
        b"camera-or-lidar",
        kind="camera.rgb",
        format="png",
        mime_type="image/png",
        filename_prefix="camera",
    )
    monkeypatch.setattr(artifacts, "get_artifact_store", lambda: store)

    info = artifacts.get_artifact_info(artifact["handle"])
    read = artifacts.read_artifact(artifact["handle"], offset=3, length=4)
    deleted = artifacts.delete_artifact(artifact["handle"])
    missing = artifacts.get_artifact_info(artifact["handle"])

    assert info["status"] == "success"
    assert info["data"]["kind"] == "camera.rgb"
    assert base64.b64decode(read["data"]["data_base64"]) == b"era-"
    assert deleted["data"]["deleted"] is True
    assert missing["code"] == "ARTIFACT_NOT_FOUND"


def test_register_exposes_all_artifact_commands(tmp_path, monkeypatch):
    store = ArtifactStore(root=tmp_path, ttl_seconds=60, max_total_bytes=1024, max_artifact_bytes=512)
    monkeypatch.setattr(artifacts, "get_artifact_store", lambda: store)
    registry = {}
    artifacts.register(registry, None)

    assert set(registry) == {"artifacts.info", "artifacts.read", "artifacts.delete", "artifacts.cleanup"}
    assert registry["artifacts.cleanup"]()["status"] == "success"
