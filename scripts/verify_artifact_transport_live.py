#!/usr/bin/env python3
"""Live scratch verification for Task 1.5 managed artifact transport."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CAMERA_PATH = "/World/MCP_Task_1_5_Camera"
LIDAR_PATH = "/World/MCP_Task_1_5_Lidar"
TARGET_PATH = "/World/MCP_Task_1_5_Target"
LIGHT_PATH = "/World/MCP_Task_1_5_Light"
SCRATCH_PATHS = (CAMERA_PATH, LIDAR_PATH, TARGET_PATH, LIGHT_PATH)
REQUIRED_ENVELOPE_FIELDS = {
    "schema_version",
    "status",
    "code",
    "message",
    "data",
    "warnings",
    "command_id",
    "timing",
    "artifacts",
    "readback",
}


def _payload(result: Any) -> dict[str, Any]:
    text = next(item.text for item in result.content if item.type == "text")
    value = json.loads(text)
    assert set(value) == REQUIRED_ENVELOPE_FIELDS, sorted(set(value) ^ REQUIRED_ENVELOPE_FIELDS)
    return value


async def _remove_scratch(session: ClientSession) -> None:
    for prim_path in SCRATCH_PATHS:
        before = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
        if before["status"] == "success":
            deleted = _payload(await session.call_tool("delete_object", {"prim_path": prim_path}))
            assert deleted["status"] == "success", deleted
            after = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
            assert after["status"] == "error", after


async def _capture(session: ClientSession, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    last = None
    for _attempt in range(24):
        last = _payload(await session.call_tool(tool, arguments))
        if last["status"] == "success":
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"{tool} did not produce a frame: {last}")


async def _download(session: ClientSession, artifact: dict[str, Any]) -> bytes:
    info = _payload(await session.call_tool("get_artifact_info", {"handle": artifact["handle"]}))
    assert info["status"] == "success", info
    assert info["data"]["sha256"] == artifact["sha256"]
    assert info["data"]["size_bytes"] == artifact["size_bytes"]
    assert info["data"]["mime_type"] == artifact["mime_type"]

    offset = 0
    chunks = []
    while True:
        result = _payload(
            await session.call_tool("read_artifact", {"handle": artifact["handle"], "offset": offset, "length": 512})
        )
        assert result["status"] == "success", result
        chunk = result["data"]
        chunks.append(base64.b64decode(chunk["data_base64"]))
        offset = chunk["next_offset"]
        if chunk["eof"]:
            break
    encoded = b"".join(chunks)
    assert len(encoded) == artifact["size_bytes"]
    assert hashlib.sha256(encoded).hexdigest() == artifact["sha256"]
    return encoded


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert {"get_artifact_info", "read_artifact", "delete_artifact", "cleanup_artifacts"} <= tools
            await _remove_scratch(session)
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                data = capabilities["data"]
                assert data["runtime"]["isaac_sim_version"].startswith("6.0.1")
                assert data["feature_flags"]["artifact.transport"]["state"] == "supported"
                assert data["extension"]["command_count"] == 54

                target = _payload(
                    await session.call_tool(
                        "create_object",
                        {
                            "object_type": "Cube",
                            "prim_path": TARGET_PATH,
                            "position": [4.0, 0.0, 1.0],
                            "size": 2.0,
                            "color": [0.8, 0.2, 0.1],
                        },
                    )
                )
                assert target["status"] == "success", target
                light = _payload(
                    await session.call_tool(
                        "create_light",
                        {
                            "light_type": "DistantLight",
                            "prim_path": LIGHT_PATH,
                            "rotation": [315.0, 0.0, 0.0],
                            "intensity": 3000.0,
                        },
                    )
                )
                assert light["status"] == "success", light
                camera = _payload(
                    await session.call_tool(
                        "create_camera",
                        {
                            "prim_path": CAMERA_PATH,
                            "position": [7.0, 4.0, 3.0],
                            "rotation": [70.0, 0.0, 120.0],
                            "resolution": [64, 48],
                        },
                    )
                )
                assert camera["status"] == "success", camera
                lidar = _payload(
                    await session.call_tool(
                        "create_lidar",
                        {
                            "prim_path": LIDAR_PATH,
                            "position": [0.0, 0.0, 1.0],
                            "horizontal_fov_deg": 90.0,
                            "vertical_fov_deg": 10.0,
                            "horizontal_resolution_deg": 10.0,
                            "vertical_resolution_deg": 10.0,
                            "rotation_rate_hz": 10.0,
                            "min_range_m": 0.1,
                            "max_range_m": 20.0,
                        },
                    )
                )
                assert lidar["status"] == "success", lidar

                played = _payload(await session.call_tool("play_simulation", {}))
                assert played["status"] == "success", played
                await asyncio.sleep(3)
                camera_capture = await _capture(
                    session, "capture_image", {"prim_path": CAMERA_PATH, "return_mode": "artifact"}
                )
                delete_capture = await _capture(
                    session, "capture_image", {"prim_path": CAMERA_PATH, "return_mode": "artifact"}
                )
                lidar_capture = await _capture(
                    session, "get_lidar_point_cloud", {"prim_path": LIDAR_PATH, "return_mode": "artifact"}
                )
                stopped = _payload(await session.call_tool("stop_simulation", {}))
                assert stopped["status"] == "success", stopped

                camera_artifact = camera_capture["artifacts"][0]
                delete_artifact = delete_capture["artifacts"][0]
                lidar_artifact = lidar_capture["artifacts"][0]
                assert all(
                    item["handle"].startswith("artifact://managed/")
                    for item in (camera_artifact, delete_artifact, lidar_artifact)
                )
                camera_bytes = await _download(session, camera_artifact)
                lidar_bytes = await _download(session, lidar_artifact)
                assert camera_bytes.startswith(b"\x89PNG\r\n\x1a\n")
                assert lidar_bytes.startswith(b"PK")

                invalid = _payload(
                    await session.call_tool("get_artifact_info", {"handle": "artifact://managed/../escape"})
                )
                assert invalid["code"] == "INVALID_ARTIFACT_HANDLE", invalid
                oversized = _payload(
                    await session.call_tool(
                        "read_artifact",
                        {
                            "handle": camera_artifact["handle"],
                            "offset": 0,
                            "length": 1025,
                        },
                    )
                )
                assert oversized["code"] == "ARTIFACT_CHUNK_LIMIT_EXCEEDED", oversized

                deleted = _payload(await session.call_tool("delete_artifact", {"handle": delete_artifact["handle"]}))
                assert deleted["status"] == "success" and deleted["data"]["deleted"] is True, deleted
                deleted_info = _payload(
                    await session.call_tool("get_artifact_info", {"handle": delete_artifact["handle"]})
                )
                assert deleted_info["code"] == "ARTIFACT_NOT_FOUND", deleted_info

                expires_at = max(
                    datetime.fromisoformat(camera_artifact["expires_at"]),
                    datetime.fromisoformat(lidar_artifact["expires_at"]),
                )
                wait_seconds = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds() + 0.5)
                await asyncio.sleep(wait_seconds)
                expired = _payload(await session.call_tool("get_artifact_info", {"handle": camera_artifact["handle"]}))
                assert expired["code"] == "ARTIFACT_EXPIRED", expired
                cleanup = _payload(await session.call_tool("cleanup_artifacts", {}))
                assert cleanup["status"] == "success", cleanup
                assert lidar_artifact["id"] in cleanup["data"]["deleted_ids"], cleanup
                lidar_info = _payload(
                    await session.call_tool("get_artifact_info", {"handle": lidar_artifact["handle"]})
                )
                assert lidar_info["code"] == "ARTIFACT_NOT_FOUND", lidar_info
            finally:
                await _remove_scratch(session)

    print(
        json.dumps(
            {
                "isaac_sim_version": data["runtime"]["isaac_sim_version"],
                "adapter": data["runtime"]["adapter"],
                "command_count": data["extension"]["command_count"],
                "camera": {"size_bytes": len(camera_bytes), "sha256": camera_artifact["sha256"]},
                "lidar": {"size_bytes": len(lidar_bytes), "sha256": lidar_artifact["sha256"]},
                "chunk_bytes": 512,
                "traversal_rejected": True,
                "chunk_limit_rejected": True,
                "delete_verified": True,
                "expiry_verified": True,
                "cleanup_verified": True,
                "scratch_cleanup": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
