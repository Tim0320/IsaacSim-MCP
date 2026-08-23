#!/usr/bin/env python3
"""Live scratch verification for Task 1.2 camera annotators and calibration."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CAMERA_PATH = "/World/MCP_Task_1_2_Camera"
TARGET_PATH = "/World/MCP_Task_1_2_Target"
LIGHT_PATH = "/World/MCP_Task_1_2_Light"
SEMANTIC_LABEL = "mcp_task_1_2_target"
OUTPUT_TYPES = (
    "depth",
    "distance_to_image_plane",
    "semantic_segmentation",
    "instance_segmentation",
    "instance_id_segmentation",
    "normals",
    "motion_vectors",
)
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


def _read_npy(path: Path) -> tuple[dict[str, Any], bytes, bytes]:
    encoded = path.read_bytes()
    assert encoded.startswith(b"\x93NUMPY\x01\x00")
    header_length = struct.unpack("<H", encoded[8:10])[0]
    header = ast.literal_eval(encoded[10 : 10 + header_length].decode("latin1").strip())
    return header, encoded[10 + header_length :], encoded


async def _capture(session: ClientSession, output_type: str) -> dict[str, Any]:
    last = None
    for _attempt in range(12):
        last = _payload(
            await session.call_tool(
                "capture_camera_output",
                {
                    "prim_path": CAMERA_PATH,
                    "output_type": output_type,
                    "return_mode": "artifact",
                },
            )
        )
        if last["status"] == "success":
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"capture_camera_output({output_type}) did not produce a frame: {last}")


async def _delete_scratch(session: ClientSession) -> None:
    errors = []
    for prim_path in (CAMERA_PATH, TARGET_PATH, LIGHT_PATH):
        try:
            deleted = _payload(await session.call_tool("delete_object", {"prim_path": prim_path}))
            if deleted["status"] != "success":
                errors.append(f"delete {prim_path}: {deleted}")
                continue
            readback = _payload(await session.call_tool("get_prim_info", {"prim_path": prim_path}))
            if readback["status"] != "error":
                errors.append(f"delete read-back {prim_path}: {readback}")
        except Exception as exc:
            errors.append(f"delete {prim_path}: {exc}")
    if errors:
        raise AssertionError("; ".join(errors))


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _delete_scratch(session)
            try:
                capabilities = _payload(await session.call_tool("get_capabilities", {}))
                flags = capabilities["data"]["feature_flags"]
                assert capabilities["data"]["runtime"]["isaac_sim_version"].startswith("6.0.1")
                assert flags["camera.annotators"]["state"] == "supported"
                assert flags["camera.calibration"]["state"] == "supported"

                target = _payload(
                    await session.call_tool(
                        "create_object",
                        {
                            "object_type": "Cube",
                            "prim_path": TARGET_PATH,
                            "position": [0.0, 0.0, 0.5],
                            "size": 1.0,
                            "color": [1.0, 0.0, 0.0],
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
                label_code = f"""
import isaacsim.core.experimental.utils.semantics as semantics_utils
semantics_utils.add_labels({TARGET_PATH!r}, labels={SEMANTIC_LABEL!r})
"""
                labelled = _payload(await session.call_tool("execute_script", {"code": label_code}))
                assert labelled["status"] == "success", labelled

                created = _payload(
                    await session.call_tool(
                        "create_camera",
                        {
                            "prim_path": CAMERA_PATH,
                            "position": [3.0, 3.0, 2.0],
                            "rotation": [65.0, 0.0, 135.0],
                            "resolution": [64, 48],
                        },
                    )
                )
                assert created["status"] == "success", created

                calibration = _payload(await session.call_tool("get_camera_calibration", {"prim_path": CAMERA_PATH}))
                assert calibration["status"] == "success", calibration
                calibration_data = calibration["data"]["calibration"]
                assert calibration_data["resolution"] == {"width": 64, "height": 48}
                assert calibration_data["projection"] == "perspective"
                assert len(calibration_data["intrinsic_matrix"]) == 3
                assert len(calibration_data["camera_to_world"]) == 4
                assert len(calibration_data["world_to_camera"]) == 4
                assert calibration_data["depth_units"] == "meters"
                assert calibration_data["meters_per_unit"] > 0

                played = _payload(await session.call_tool("play_simulation", {}))
                assert played["status"] == "success", played
                await asyncio.sleep(2)

                captures = {}
                for output_type in OUTPUT_TYPES:
                    if output_type == "motion_vectors":
                        moved = _payload(
                            await session.call_tool(
                                "transform_object",
                                {"prim_path": TARGET_PATH, "position": [0.25, 0.0, 0.5]},
                            )
                        )
                        assert moved["status"] == "success", moved
                        await asyncio.sleep(0.5)
                    captures[output_type] = await _capture(session, output_type)

                stopped = _payload(await session.call_tool("stop_simulation", {}))
                assert stopped["status"] == "success", stopped
            finally:
                await _delete_scratch(session)

    verified = {}
    for output_type, capture in captures.items():
        metadata = capture["data"]["camera_output"]
        artifact = capture["artifacts"][0]
        header, raw, encoded = _read_npy(Path(artifact["path"]))
        assert list(header["shape"]) == metadata["shape"]
        assert metadata["shape"][:2] == [48, 64]
        assert hashlib.sha256(raw).hexdigest() == metadata["raw_sha256"]
        assert hashlib.sha256(encoded).hexdigest() == artifact["sha256"]
        assert len(raw) == metadata["raw_size_bytes"]
        verified[output_type] = {
            "dtype": metadata["dtype"],
            "shape": metadata["shape"],
            "units": metadata["units"],
            "raw_sha256": metadata["raw_sha256"],
            "artifact_sha256": artifact["sha256"],
        }

    for output_type in ("depth", "distance_to_image_plane", "normals"):
        artifact = captures[output_type]["artifacts"][0]
        _header, raw, _encoded = _read_npy(Path(artifact["path"]))
        values = [value[0] for value in struct.iter_unpack("<f", raw)]
        assert any(value != 0.0 for value in values), output_type

    for output_type in ("semantic_segmentation", "instance_segmentation", "instance_id_segmentation"):
        artifact = captures[output_type]["artifacts"][0]
        _header, raw, _encoded = _read_npy(Path(artifact["path"]))
        values = [value[0] for value in struct.iter_unpack("<I", raw)]
        assert any(value != 0 for value in values), output_type

    semantic_info = captures["semantic_segmentation"]["data"]["camera_output"]["annotator_info"]
    assert SEMANTIC_LABEL in json.dumps(semantic_info), semantic_info
    instance_info = captures["instance_segmentation"]["data"]["camera_output"]["annotator_info"]
    assert SEMANTIC_LABEL in json.dumps(instance_info), instance_info
    instance_id_info = captures["instance_id_segmentation"]["data"]["camera_output"]["annotator_info"]
    assert TARGET_PATH in json.dumps(instance_id_info), instance_id_info

    summary = {
        "isaac_sim_version": capabilities["data"]["runtime"]["isaac_sim_version"],
        "adapter": capabilities["data"]["runtime"]["adapter"],
        "physics_backend": capabilities["data"]["runtime"]["physics_backend"],
        "camera_prim": CAMERA_PATH,
        "target_prim": TARGET_PATH,
        "semantic_label": SEMANTIC_LABEL,
        "calibration": calibration_data,
        "outputs": verified,
        "scratch_cleanup": True,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
