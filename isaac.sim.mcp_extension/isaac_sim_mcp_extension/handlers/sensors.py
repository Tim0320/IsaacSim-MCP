# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Sensor creation and data capture command handlers."""

from __future__ import annotations

import base64
import hashlib
import os
import struct
import tempfile
import time
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from ..adapters.base import IsaacAdapterBase

CAMERA_RETURN_MODES = {"metadata", "artifact", "inline"}
DEFAULT_INLINE_MAX_BYTES = 1024 * 1024
MAX_INLINE_MAX_BYTES = 4 * 1024 * 1024
ARTIFACT_ROOT_ENV = "ISAAC_MCP_ARTIFACT_ROOT"


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["sensors.create_camera"] = lambda **p: create_camera(adapter, **p)
    registry["sensors.capture_image"] = lambda **p: capture_image(adapter, **p)
    registry["sensors.create_lidar"] = lambda **p: create_lidar(adapter, **p)
    registry["sensors.get_point_cloud"] = lambda **p: get_point_cloud(adapter, **p)


def create_camera(
    adapter: IsaacAdapterBase,
    prim_path: str = "/World/Camera",
    position: Optional[Sequence[float]] = None,
    rotation: Optional[Sequence[float]] = None,
    resolution: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    try:
        res = tuple(resolution) if resolution else (1280, 720)
        _cam = adapter.create_camera(prim_path, resolution=res)
        if position or rotation:
            adapter.set_prim_transform(prim_path, position=position, rotation=rotation)
        return {"status": "success", "message": f"Camera created at {prim_path}", "prim_path": prim_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _timeline_metadata(adapter: IsaacAdapterBase) -> Dict[str, Any]:
    metadata = {"frame": None, "timeline_time_seconds": None, "time_codes_per_second": None}
    try:
        import omni.timeline

        timeline_time = float(omni.timeline.get_timeline_interface().get_current_time())
        stage = adapter.get_stage()
        time_codes_per_second = float(stage.GetTimeCodesPerSecond()) if stage is not None else 60.0
        metadata.update(
            {
                "frame": int(round(timeline_time * time_codes_per_second)),
                "timeline_time_seconds": timeline_time,
                "time_codes_per_second": time_codes_per_second,
            }
        )
    except Exception:
        pass
    return metadata


def _pixel_bytes(image_data: Any) -> bytes:
    if hasattr(image_data, "tobytes"):
        return image_data.tobytes(order="C")
    return bytes(image_data)


def _image_metadata(adapter: IsaacAdapterBase, image_data: Any, prim_path: str) -> Dict[str, Any]:
    shape = list(getattr(image_data, "shape", ()))
    if len(shape) not in (2, 3) or any(not isinstance(value, int) or value <= 0 for value in shape):
        raise ValueError(f"Camera frame has an invalid shape: {shape}")

    height, width = shape[:2]
    channels = shape[2] if len(shape) == 3 else 1
    dtype = str(getattr(image_data, "dtype", "unknown"))
    if dtype != "uint8":
        raise ValueError(f"Camera RGB output must use uint8 pixels, got {dtype}")
    if channels not in (3, 4):
        raise ValueError(f"Camera RGB frame must have 3 or 4 channels, got {channels}")

    pixels = _pixel_bytes(image_data)
    expected_size = height * width * channels
    if len(pixels) != expected_size:
        raise ValueError(f"Camera frame byte length mismatch: expected {expected_size}, got {len(pixels)}")
    timestamp_ns = time.time_ns()
    metadata = {
        "camera_prim": prim_path,
        "format": "raw",
        "mime_type": "application/octet-stream",
        "dtype": dtype,
        "shape": shape,
        "width": width,
        "height": height,
        "channels": channels,
        "color_space": {3: "RGB", 4: "RGBA"}[channels],
        "raw_size_bytes": len(pixels),
        "pixel_sha256": hashlib.sha256(pixels).hexdigest(),
        "captured_at": datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc).isoformat(),
        "timestamp_ns": timestamp_ns,
    }
    metadata.update(_timeline_metadata(adapter))
    return metadata


def _encode_png(image_data: Any) -> bytes:
    shape = list(image_data.shape)
    height, width, channels = shape
    color_type = 2 if channels == 3 else 6
    pixels = _pixel_bytes(image_data)
    stride = width * channels
    scanlines = b"".join(b"\x00" + pixels[offset : offset + stride] for offset in range(0, len(pixels), stride))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")
    )


def _artifact_root() -> Path:
    configured = os.environ.get(ARTIFACT_ROOT_ENV)
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "isaacsim-mcp" / "artifacts"
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_png_artifact(png_bytes: bytes, output_path: Optional[str], metadata: Dict[str, Any]) -> Dict[str, Any]:
    artifact_id = uuid.uuid4().hex
    managed = output_path is None
    if managed:
        root = _artifact_root()
        path = root / f"camera-{artifact_id}.png"
    else:
        path = Path(output_path).expanduser().resolve()
        if path.suffix.lower() != ".png":
            raise ValueError("output_path must end in .png")
        if not path.parent.is_dir():
            raise ValueError(f"output_path parent does not exist: {path.parent}")

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(png_bytes)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return {
        "id": artifact_id,
        "handle": f"artifact://camera/{artifact_id}",
        "kind": "camera.rgb",
        "managed": managed,
        "path": str(path),
        "format": "png",
        "mime_type": "image/png",
        "size_bytes": len(png_bytes),
        "sha256": hashlib.sha256(png_bytes).hexdigest(),
        **{key: metadata[key] for key in ("dtype", "shape", "width", "height", "channels", "color_space")},
        "camera_prim": metadata["camera_prim"],
        "captured_at": metadata["captured_at"],
        "timestamp_ns": metadata["timestamp_ns"],
        "frame": metadata["frame"],
    }


def capture_image(
    adapter: IsaacAdapterBase,
    prim_path: str = "/World/Camera",
    output_path: Optional[str] = None,
    return_mode: str = "artifact",
    inline_max_bytes: int = DEFAULT_INLINE_MAX_BYTES,
) -> Dict[str, Any]:
    try:
        if return_mode not in CAMERA_RETURN_MODES:
            return {
                "status": "error",
                "code": "INVALID_RETURN_MODE",
                "message": f"return_mode must be one of {sorted(CAMERA_RETURN_MODES)}, got {return_mode!r}",
            }
        if output_path and return_mode != "artifact":
            return {
                "status": "error",
                "code": "OUTPUT_PATH_REQUIRES_ARTIFACT",
                "message": "output_path can only be used with return_mode='artifact'",
            }
        if return_mode == "inline" and (isinstance(inline_max_bytes, bool) or not isinstance(inline_max_bytes, int)):
            return {
                "status": "error",
                "code": "INVALID_INLINE_LIMIT",
                "message": "inline_max_bytes must be an integer",
            }
        if return_mode == "inline" and not 1 <= inline_max_bytes <= MAX_INLINE_MAX_BYTES:
            return {
                "status": "error",
                "code": "INVALID_INLINE_LIMIT",
                "message": f"inline_max_bytes must be between 1 and {MAX_INLINE_MAX_BYTES}",
            }

        image_data = adapter.capture_camera_image(prim_path)
        # An RTX sensor with no frame yet yields an empty array, not an error.
        # Reporting that as success gave back {"shape": [0]} with status
        # "success", which a caller cannot tell apart from a captured image —
        # and with output_path set it fed an empty array to Image.fromarray.
        # Verified on Isaac Sim 6.0.1: in the step-only debug loop the timeline
        # never plays, Replicator's orchestrator therefore stays STOPPED
        # (/omni/replicator/captureOnPlay defaults to True), and every capture
        # returned an empty array while reporting success.
        if image_data is None or getattr(image_data, "size", 0) == 0:
            # Only say a render was requested if this adapter can actually
            # request one. V6 schedules a Replicator frame; V5 has no such path,
            # and telling a 5.1 caller to "call again to collect it" would send
            # them round a loop that never terminates.
            # Test the capability, not the current value: _render_request starts
            # as None, so checking it would give a V6 caller the V5 wording on
            # the first call — the one that actually schedules the render.
            requested = callable(getattr(adapter, "_request_render_frame", None))
            remedy = (
                "A render has been requested — call capture_image again to collect it."
                if requested
                else "Play the simulation, or capture again once a frame has rendered."
            )
            return {
                "status": "error",
                "message": (
                    f"No frame available from {prim_path} yet. RTX sensor data is produced by "
                    "Replicator, which by default only captures while the timeline is playing "
                    f"(/omni/replicator/captureOnPlay). {remedy}"
                ),
            }
        metadata = _image_metadata(adapter, image_data, prim_path)
        response: Dict[str, Any] = {
            "status": "success",
            "message": "Image captured",
            "return_mode": return_mode,
            "image": metadata,
        }
        if return_mode == "metadata":
            return response

        png_bytes = _encode_png(image_data)
        png_sha256 = hashlib.sha256(png_bytes).hexdigest()
        if return_mode == "inline":
            if len(png_bytes) > inline_max_bytes:
                return {
                    "status": "error",
                    "code": "INLINE_SIZE_LIMIT_EXCEEDED",
                    "message": f"Encoded PNG is {len(png_bytes)} bytes; inline limit is {inline_max_bytes} bytes",
                    "return_mode": return_mode,
                    "image": metadata,
                    "encoded_size_bytes": len(png_bytes),
                    "inline_max_bytes": inline_max_bytes,
                }
            response["inline"] = {
                "encoding": "base64",
                "format": "png",
                "mime_type": "image/png",
                "size_bytes": len(png_bytes),
                "sha256": png_sha256,
                "data": base64.b64encode(png_bytes).decode("ascii"),
            }
            return response

        artifact = _write_png_artifact(png_bytes, output_path, metadata)
        response["message"] = f"Image saved to {artifact['path']}"
        response["output_path"] = artifact["path"]
        response["artifact_handle"] = artifact["handle"]
        response["artifacts"] = [artifact]
        return response
    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_lidar(
    adapter: IsaacAdapterBase,
    prim_path: str = "/World/Lidar",
    position: Optional[Sequence[float]] = None,
    rotation: Optional[Sequence[float]] = None,
    config: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        adapter.create_lidar(prim_path, config=config)
        if position or rotation:
            adapter.set_prim_transform(prim_path, position=position, rotation=rotation)
        return {"status": "success", "message": f"Lidar created at {prim_path}", "prim_path": prim_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_point_cloud(adapter: IsaacAdapterBase, prim_path: str = "/World/Lidar") -> Dict[str, Any]:
    try:
        pc = adapter.get_lidar_point_cloud(prim_path)
        point_count = len(pc) if pc is not None else 0
        # An empty return means Replicator has not produced a frame for this
        # sensor, not that the lidar saw nothing. Reporting it as success with
        # "Got 0 points" is indistinguishable from a lidar aimed at empty space.
        # Same gating as capture_image: RTX sensor data only flows while
        # Replicator is capturing (/omni/replicator/captureOnPlay).
        if point_count == 0:
            # No retry advice here, unlike capture_image. A single Replicator
            # frame fills a camera but not a lidar: measured on 6.0.1 with the
            # orchestrator at STEPPED and the render request completed, the
            # sensor was still empty, and only play_simulation produced data.
            return {
                "status": "error",
                "message": (
                    f"No lidar frame available from {prim_path}. RTX lidar data is produced by "
                    "Replicator while the timeline runs; a single rendered frame is not enough. "
                    "Call play_simulation, then read the point cloud."
                ),
                "point_count": 0,
            }
        return {"status": "success", "message": f"Got {point_count} points", "point_count": point_count}
    except Exception as e:
        return {"status": "error", "message": str(e)}
