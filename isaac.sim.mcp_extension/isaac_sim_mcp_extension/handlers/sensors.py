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

import ast
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

CAMERA_OUTPUT_SPECS = {
    "depth": {
        "annotator": "distance_to_camera",
        "dtype": "float32",
        "channels": 1,
        "units": "meters",
        "coordinate_space": "radial_distance_from_camera",
    },
    "distance_to_image_plane": {
        "annotator": "distance_to_image_plane",
        "dtype": "float32",
        "channels": 1,
        "units": "meters",
        "coordinate_space": "camera_image_plane",
    },
    "semantic_segmentation": {
        "annotator": "semantic_segmentation",
        "dtype": "uint32",
        "channels": 1,
        "units": "semantic_id",
        "coordinate_space": "image",
    },
    "instance_segmentation": {
        "annotator": "instance_segmentation",
        "dtype": "uint32",
        "channels": 1,
        "units": "instance_id",
        "coordinate_space": "image",
    },
    "instance_id_segmentation": {
        "annotator": "instance_id_segmentation",
        "dtype": "uint32",
        "channels": 1,
        "units": "instance_prim_id",
        "coordinate_space": "image",
    },
    "normals": {
        "annotator": "normals",
        "dtype": "float32",
        "channels": 3,
        "units": "unitless",
        "coordinate_space": "renderer",
    },
    "motion_vectors": {
        "annotator": "motion_vectors",
        "dtype": "float32",
        "channels": 2,
        "units": "pixels_per_frame",
        "coordinate_space": "image",
    },
}

_DTYPE_SIZE = {"float32": 4, "uint32": 4}
_NPY_DESCR = {"float32": "<f4", "uint32": "<u4"}


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["sensors.create_camera"] = lambda **p: create_camera(adapter, **p)
    registry["sensors.capture_image"] = lambda **p: capture_image(adapter, **p)
    registry["sensors.capture_camera_output"] = lambda **p: capture_camera_output(adapter, **p)
    registry["sensors.get_camera_calibration"] = lambda **p: get_camera_calibration(adapter, **p)
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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _camera_output_metadata(
    adapter: IsaacAdapterBase,
    data: Any,
    info: Dict[str, Any],
    prim_path: str,
    output_type: str,
) -> tuple[Dict[str, Any], bytes]:
    spec = CAMERA_OUTPUT_SPECS[output_type]
    shape = list(getattr(data, "shape", ()))
    channels = spec["channels"]
    valid_shape = len(shape) == 2 and channels == 1
    valid_shape = valid_shape or (len(shape) == 3 and shape[2] == channels)
    if not valid_shape or any(not isinstance(value, int) or value <= 0 for value in shape):
        raise ValueError(f"Camera {output_type} output has an invalid shape: {shape}; expected HxW or HxWx{channels}")

    dtype = str(getattr(data, "dtype", "unknown"))
    if dtype != spec["dtype"]:
        raise ValueError(f"Camera {output_type} output must use {spec['dtype']}, got {dtype}")

    raw = _pixel_bytes(data)
    elements = 1
    for dimension in shape:
        elements *= dimension
    expected_size = elements * _DTYPE_SIZE[dtype]
    if len(raw) != expected_size:
        raise ValueError(f"Camera {output_type} byte length mismatch: expected {expected_size}, got {len(raw)}")

    timestamp_ns = time.time_ns()
    metadata = {
        "camera_prim": prim_path,
        "output_type": output_type,
        "annotator": spec["annotator"],
        "dtype": dtype,
        "shape": shape,
        "width": shape[1],
        "height": shape[0],
        "channels": channels,
        "units": spec["units"],
        "coordinate_space": spec["coordinate_space"],
        "raw_size_bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "annotator_info": _json_safe(info),
        "captured_at": datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc).isoformat(),
        "timestamp_ns": timestamp_ns,
    }
    metadata.update(_timeline_metadata(adapter))
    return metadata, raw


def _encode_npy(raw: bytes, shape: Sequence[int], dtype: str) -> bytes:
    shape_repr = repr(tuple(shape))
    header = f"{{'descr': '{_NPY_DESCR[dtype]}', 'fortran_order': False, 'shape': {shape_repr}, }}"
    prefix_size = len(b"\x93NUMPY") + 2 + 2
    padding = 16 - ((prefix_size + len(header) + 1) % 16)
    header_bytes = (header + (" " * padding) + "\n").encode("latin1")
    if len(header_bytes) > 65535:
        raise ValueError("NumPy header is too large")
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header_bytes)) + header_bytes + raw


def _decode_npy_header(encoded: bytes) -> Dict[str, Any]:
    """Decode the v1 header emitted by _encode_npy (used by contract tests)."""
    if not encoded.startswith(b"\x93NUMPY\x01\x00"):
        raise ValueError("Not a NumPy v1 artifact")
    header_length = struct.unpack("<H", encoded[8:10])[0]
    return ast.literal_eval(encoded[10 : 10 + header_length].decode("latin1").strip())


def _write_npy_artifact(
    encoded: bytes,
    output_path: Optional[str],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    artifact_id = uuid.uuid4().hex
    managed = output_path is None
    if managed:
        path = _artifact_root() / f"camera-{metadata['output_type']}-{artifact_id}.npy"
    else:
        path = Path(output_path).expanduser().resolve()
        if path.suffix.lower() != ".npy":
            raise ValueError("output_path must end in .npy")
        if not path.parent.is_dir():
            raise ValueError(f"output_path parent does not exist: {path.parent}")

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return {
        "id": artifact_id,
        "handle": f"artifact://camera/{artifact_id}",
        "kind": f"camera.{metadata['output_type']}",
        "managed": managed,
        "path": str(path),
        "format": "npy",
        "mime_type": "application/x-npy",
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        **{
            key: metadata[key] for key in ("dtype", "shape", "width", "height", "channels", "units", "coordinate_space")
        },
        "camera_prim": metadata["camera_prim"],
        "output_type": metadata["output_type"],
        "annotator": metadata["annotator"],
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


def capture_camera_output(
    adapter: IsaacAdapterBase,
    prim_path: str = "/World/Camera",
    output_type: str = "depth",
    output_path: Optional[str] = None,
    return_mode: str = "artifact",
    inline_max_bytes: int = DEFAULT_INLINE_MAX_BYTES,
) -> Dict[str, Any]:
    if output_type not in CAMERA_OUTPUT_SPECS:
        return {
            "status": "error",
            "code": "INVALID_CAMERA_OUTPUT_TYPE",
            "message": f"output_type must be one of {sorted(CAMERA_OUTPUT_SPECS)}, got {output_type!r}",
        }
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
        return {"status": "error", "code": "INVALID_INLINE_LIMIT", "message": "inline_max_bytes must be an integer"}
    if return_mode == "inline" and not 1 <= inline_max_bytes <= MAX_INLINE_MAX_BYTES:
        return {
            "status": "error",
            "code": "INVALID_INLINE_LIMIT",
            "message": f"inline_max_bytes must be between 1 and {MAX_INLINE_MAX_BYTES}",
        }

    try:
        spec = CAMERA_OUTPUT_SPECS[output_type]
        data, info = adapter.capture_camera_output(prim_path, spec["annotator"])
        if data is None or getattr(data, "size", 0) == 0:
            requested = callable(getattr(adapter, "_request_render_frame", None))
            remedy = (
                "A render has been requested; call capture_camera_output again to collect it."
                if requested
                else "Play the simulation, then capture again once a frame has rendered."
            )
            return {
                "status": "error",
                "code": "CAMERA_FRAME_NOT_READY",
                "message": f"No {output_type} frame available from {prim_path}. {remedy}",
            }

        metadata, raw = _camera_output_metadata(adapter, data, info or {}, prim_path, output_type)
        response: Dict[str, Any] = {
            "status": "success",
            "message": f"Camera {output_type} captured",
            "return_mode": return_mode,
            "camera_output": metadata,
        }
        if return_mode == "metadata":
            return response
        if return_mode == "inline":
            if len(raw) > inline_max_bytes:
                return {
                    "status": "error",
                    "code": "INLINE_SIZE_LIMIT_EXCEEDED",
                    "message": f"Raw camera output is {len(raw)} bytes; inline limit is {inline_max_bytes} bytes",
                    "return_mode": return_mode,
                    "camera_output": metadata,
                    "encoded_size_bytes": len(raw),
                    "inline_max_bytes": inline_max_bytes,
                }
            response["inline"] = {
                "encoding": "base64",
                "format": "raw",
                "mime_type": "application/octet-stream",
                "dtype": metadata["dtype"],
                "shape": metadata["shape"],
                "byte_order": "little",
                "size_bytes": len(raw),
                "sha256": metadata["raw_sha256"],
                "data": base64.b64encode(raw).decode("ascii"),
            }
            return response

        encoded = _encode_npy(raw, metadata["shape"], metadata["dtype"])
        artifact = _write_npy_artifact(encoded, output_path, metadata)
        response["message"] = f"Camera {output_type} saved to {artifact['path']}"
        response["output_path"] = artifact["path"]
        response["artifact_handle"] = artifact["handle"]
        response["artifacts"] = [artifact]
        return response
    except NotImplementedError as exc:
        return {
            "status": "unsupported",
            "code": "CAMERA_OUTPUT_UNSUPPORTED",
            "message": str(exc),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def get_camera_calibration(
    adapter: IsaacAdapterBase,
    prim_path: str = "/World/Camera",
) -> Dict[str, Any]:
    try:
        calibration = adapter.get_camera_calibration(prim_path)
        return {"status": "success", "message": "Camera calibration read", "calibration": calibration}
    except NotImplementedError as exc:
        return {
            "status": "unsupported",
            "code": "CAMERA_CALIBRATION_UNSUPPORTED",
            "message": str(exc),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


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
