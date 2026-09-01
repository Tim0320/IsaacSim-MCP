#!/usr/bin/env python3
"""Live scratch verification for Task 1.3 typed LiDAR point-cloud transfer."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import json
import math
import os
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LIDAR_PATH = "/World/MCP_Task_1_3_Lidar"
TARGETS = {
    "/World/MCP_Task_1_3_Target_XP": [5.0, 0.0, 1.0],
    "/World/MCP_Task_1_3_Target_XN": [-5.0, 0.0, 1.0],
    "/World/MCP_Task_1_3_Target_YP": [0.0, 5.0, 1.0],
    "/World/MCP_Task_1_3_Target_YN": [0.0, -5.0, 1.0],
}
SCRATCH_PATHS = (LIDAR_PATH, *TARGETS)
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


def _read_npy(encoded: bytes) -> tuple[dict[str, Any], bytes]:
    assert encoded.startswith(b"\x93NUMPY\x01\x00")
    header_length = struct.unpack("<H", encoded[8:10])[0]
    header = ast.literal_eval(encoded[10 : 10 + header_length].decode("latin1").strip())
    return header, encoded[10 + header_length :]


async def _remove_scratch(session: ClientSession, require_present: bool) -> None:
    errors = []
    for prim_path in SCRATCH_PATHS:
        before = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
        if before["status"] == "success":
            deleted = _payload(await session.call_tool("delete_object", {"prim_path": prim_path}))
            if deleted["status"] != "success":
                errors.append(f"delete {prim_path}: {deleted}")
                continue
            after = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
            if after["status"] != "error":
                errors.append(f"delete read-back {prim_path}: {after}")
        elif require_present:
            errors.append(f"expected scratch prim before cleanup: {prim_path}")
    if errors:
        raise AssertionError("; ".join(errors))


async def _capture(session: ClientSession) -> dict[str, Any]:
    last = None
    for _attempt in range(20):
        last = _payload(
            await session.call_tool(
                "get_lidar_point_cloud",
                {"prim_path": LIDAR_PATH, "return_mode": "artifact"},
            )
        )
        if last["status"] == "success":
            return last
        assert last["code"] == "LIDAR_FRAME_NOT_READY", last
        await asyncio.sleep(0.5)
    raise AssertionError(f"LiDAR did not produce a frame: {last}")


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _remove_scratch(session, require_present=False)
            cleanup_required = False
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                assert capabilities["data"]["runtime"]["isaac_sim_version"].startswith("6.0.1")
                assert capabilities["data"]["feature_flags"]["lidar.point_cloud"]["state"] == "supported"

                for prim_path, position in TARGETS.items():
                    created = _payload(
                        await session.call_tool(
                            "create_object",
                            {
                                "object_type": "Cube",
                                "prim_path": prim_path,
                                "position": position,
                                "size": 2.0,
                                "color": [0.8, 0.2, 0.1],
                            },
                        )
                    )
                    assert created["status"] == "success", created
                    cleanup_required = True
                created = _payload(
                    await session.call_tool(
                        "create_lidar",
                        {"prim_path": LIDAR_PATH, "position": [0.0, 0.0, 1.0]},
                    )
                )
                assert created["status"] == "success", created

                lidar_readback = _payload(await session.call_tool("get_prim_info", {"prim_path": LIDAR_PATH}))
                assert lidar_readback["status"] == "success", lidar_readback
                prewarm = _payload(
                    await session.call_tool(
                        "get_lidar_point_cloud",
                        {"prim_path": LIDAR_PATH, "return_mode": "artifact"},
                    )
                )
                assert prewarm["status"] == "error" and prewarm["code"] == "LIDAR_FRAME_NOT_READY", prewarm
                target_readback = {}
                for prim_path in TARGETS:
                    value = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
                    assert value["status"] == "success", value
                    target_readback[prim_path] = value["data"]

                played = _payload(await session.call_tool("play_simulation", {}))
                assert played["status"] == "success", played
                await asyncio.sleep(3)
                capture = await _capture(session)
                stopped = _payload(await session.call_tool("stop_simulation", {}))
                assert stopped["status"] == "success", stopped
            finally:
                if cleanup_required:
                    await _remove_scratch(session, require_present=False)

    metadata = capture["data"]["lidar_point_cloud"]
    artifact = capture["artifacts"][0]
    encoded = Path(artifact["path"]).read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == artifact["sha256"]
    point_count = metadata["point_count"]
    assert point_count > 0
    required = {"points", "range", "azimuth", "elevation"}
    assert required <= set(metadata["fields"])

    decoded = {}
    with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
        assert {name.removesuffix(".npy") for name in archive.namelist()} == set(metadata["fields"])
        for field_name, field_metadata in metadata["fields"].items():
            header, raw = _read_npy(archive.read(f"{field_name}.npy"))
            assert list(header["shape"]) == field_metadata["shape"]
            assert field_metadata["shape"][0] == point_count
            assert hashlib.sha256(raw).hexdigest() == field_metadata["sha256"]
            assert len(raw) == field_metadata["size_bytes"]
            decoded[field_name] = (header, raw)

    assert metadata["fields"]["points"]["shape"] == [point_count, 3]
    assert metadata["fields"]["points"]["units"] == "meters"
    assert metadata["fields"]["range"]["units"] == "meters"
    assert metadata["fields"]["azimuth"]["units"] == "degrees"
    assert metadata["fields"]["elevation"]["units"] == "degrees"
    assert metadata["coordinate_type"] in {"spherical", "cartesian"}
    assert metadata["coordinate_frame"] != "unknown"
    assert metadata["sensor_timestamp_ns"] > 0
    assert metadata["sensor_frame_id"] >= 0
    assert metadata["sensor_pose"] is not None
    assert metadata["sensor_pose"]["position"] == [0.0, 0.0, 1.0]

    points = [values for values in struct.iter_unpack("<fff", decoded["points"][1])]
    assert len(points) == point_count
    assert all(math.isfinite(value) for point in points for value in point)
    assert any(any(abs(value) > 1e-6 for value in point) for point in points)

    resolved_object_paths = set()
    unique_object_ids = set()
    if {"object_id_low", "object_id_high"} <= set(decoded):
        lows = [value[0] for value in struct.iter_unpack("<Q", decoded["object_id_low"][1])]
        highs = [value[0] for value in struct.iter_unpack("<Q", decoded["object_id_high"][1])]
        unique_object_ids = {(high << 64) | low for low, high in zip(lows, highs)}
        resolved_object_paths = {
            metadata["object_id_map"][f"{object_id:032x}"]
            for object_id in unique_object_ids
            if f"{object_id:032x}" in metadata["object_id_map"]
        }
        assert resolved_object_paths & set(TARGETS), (unique_object_ids, metadata["object_id_map"])

    summary = {
        "isaac_sim_version": capabilities["data"]["runtime"]["isaac_sim_version"],
        "adapter": capabilities["data"]["runtime"]["adapter"],
        "physics_backend": capabilities["data"]["runtime"]["physics_backend"],
        "lidar_prim": LIDAR_PATH,
        "prewarm_code": prewarm["code"],
        "target_prims": list(TARGETS),
        "point_count": point_count,
        "fields": metadata["fields"],
        "coordinate_type": metadata["coordinate_type"],
        "coordinate_frame": metadata["coordinate_frame"],
        "sensor_timestamp_ns": metadata["sensor_timestamp_ns"],
        "sensor_frame_id": metadata["sensor_frame_id"],
        "sensor_pose": metadata["sensor_pose"],
        "object_id_map_count": len(metadata["object_id_map"]),
        "unique_object_id_count": len(unique_object_ids),
        "resolved_object_paths": sorted(resolved_object_paths),
        "unavailable_fields": metadata["unavailable_fields"],
        "artifact_sha256": artifact["sha256"],
        "scratch_readback": {"lidar": lidar_readback["data"], "targets": target_readback},
        "scratch_cleanup": True,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
