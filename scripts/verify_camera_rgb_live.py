#!/usr/bin/env python3
"""Read/write scratch verification for capture_image metadata, artifact, and inline modes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
CAMERA_PATH = "/World/MCP_Task_1_1_Camera"
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


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
    return (left, up, upper_left)[distances.index(min(distances))]


def _decode_png(png: bytes) -> tuple[int, int, int, bytes]:
    """Decode non-interlaced 8-bit RGB/RGBA PNG bytes with the stdlib."""
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        kind = png[offset + 4 : offset + 8]
        data = png[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            break

    assert bit_depth == 8 and color_type in (2, 6) and interlace == 0
    channels = 3 if color_type == 2 else 4
    scanlines = zlib.decompress(bytes(compressed))
    stride = width * channels
    expected = height * (stride + 1)
    assert len(scanlines) == expected, (len(scanlines), expected)

    decoded = bytearray()
    previous = bytearray(stride)
    for row_index in range(height):
        start = row_index * (stride + 1)
        filter_type = scanlines[start]
        source = scanlines[start + 1 : start + 1 + stride]
        row = bytearray(stride)
        for index, value in enumerate(source):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            predictors = {
                0: 0,
                1: left,
                2: up,
                3: (left + up) // 2,
                4: _paeth(left, up, upper_left),
            }
            assert filter_type in predictors, filter_type
            row[index] = (value + predictors[filter_type]) & 0xFF
        decoded.extend(row)
        previous = row
    return width, height, channels, bytes(decoded)


async def _capture(session: ClientSession, mode: str, **kwargs: Any) -> dict[str, Any]:
    arguments = {"prim_path": CAMERA_PATH, "return_mode": mode, **kwargs}
    last = None
    for _attempt in range(8):
        last = _payload(await session.call_tool("capture_image", arguments))
        if last["status"] == "success":
            return last
        await asyncio.sleep(1)
    raise AssertionError(f"capture_image({mode}) did not produce a frame: {last}")


async def main() -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            capabilities = _payload(await session.call_tool("get_capabilities", {}))
            assert capabilities["data"]["runtime"]["isaac_sim_version"].startswith("6.0.1")
            assert capabilities["data"]["feature_flags"]["camera.rgb_pixels"]["state"] == "supported"

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
            readback = _payload(await session.call_tool("get_prim_info", {"prim_path": CAMERA_PATH}))
            assert readback["status"] == "success" and readback["data"]["path"] == CAMERA_PATH

            played = _payload(await session.call_tool("play_simulation", {}))
            assert played["status"] == "success", played
            await asyncio.sleep(2)

            metadata = await _capture(session, "metadata")
            artifact = await _capture(session, "artifact")
            inline = await _capture(session, "inline", inline_max_bytes=1024 * 1024)
            tiny_limit = _payload(
                await session.call_tool(
                    "capture_image",
                    {"prim_path": CAMERA_PATH, "return_mode": "inline", "inline_max_bytes": 1},
                )
            )

            stopped = _payload(await session.call_tool("stop_simulation", {}))
            assert stopped["status"] == "success", stopped

    image = artifact["data"]["image"]
    artifact_meta = artifact["artifacts"][0]
    artifact_path = Path(artifact_meta["path"])
    png = artifact_path.read_bytes()
    width, height, channels, pixels = _decode_png(png)

    assert artifact_meta["managed"] is True
    assert artifact_meta["handle"].startswith("artifact://camera/")
    assert hashlib.sha256(png).hexdigest() == artifact_meta["sha256"]
    assert [height, width, channels] == image["shape"] == [48, 64, 3]
    assert image["dtype"] == "uint8" and image["color_space"] == "RGB"
    assert hashlib.sha256(pixels).hexdigest() == image["pixel_sha256"]

    inline_png = base64.b64decode(inline["data"]["inline"]["data"])
    inline_width, inline_height, inline_channels, inline_pixels = _decode_png(inline_png)
    assert hashlib.sha256(inline_png).hexdigest() == inline["data"]["inline"]["sha256"]
    assert [inline_height, inline_width, inline_channels] == inline["data"]["image"]["shape"]
    assert hashlib.sha256(inline_pixels).hexdigest() == inline["data"]["image"]["pixel_sha256"]

    assert metadata["data"]["return_mode"] == "metadata"
    assert metadata["artifacts"] == [] and "inline" not in metadata["data"]
    assert tiny_limit["status"] == "error" and tiny_limit["code"] == "INLINE_SIZE_LIMIT_EXCEEDED"

    summary = {
        "isaac_sim_version": capabilities["data"]["runtime"]["isaac_sim_version"],
        "adapter": capabilities["data"]["runtime"]["adapter"],
        "physics_backend": capabilities["data"]["runtime"]["physics_backend"],
        "camera_prim": CAMERA_PATH,
        "shape": image["shape"],
        "dtype": image["dtype"],
        "frame": image["frame"],
        "timestamp_ns": image["timestamp_ns"],
        "pixel_sha256_verified": True,
        "artifact_path": str(artifact_path),
        "artifact_sha256_verified": True,
        "inline_png_bytes": len(inline_png),
        "inline_sha256_verified": True,
        "inline_limit_code": tiny_limit["code"],
        "camera_readback_verified": True,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
