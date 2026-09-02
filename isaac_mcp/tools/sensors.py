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

"""Sensor MCP tools."""

import base64
import binascii
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Mapping, Optional, Union

from mcp.server.fastmcp import FastMCP

from isaac_mcp.command_context import idempotency_key_var
from isaac_mcp.responses import NativeImageResponse

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


CAMERA_WARMUP_RETRY_DELAY_SECONDS = 0.5
CameraReturnMode = Literal["metadata", "artifact", "inline", "image"]


def _camera_frame_not_ready(result: Mapping[str, Any]) -> bool:
    """Recognize both current and rolling-upgrade frame warm-up responses."""
    if result.get("code") == "CAMERA_FRAME_NOT_READY":
        return True
    if str(result.get("status", "success")).lower() == "success":
        return False
    message = str(result.get("message", "")).lower()
    return "no frame available" in message or "no rgb frame available" in message


def _with_camera_warmup_evidence(result: Mapping[str, Any]) -> Mapping[str, Any]:
    annotated = dict(result)
    evidence = {
        "attempted": True,
        "capture_attempts": 2,
        "delay_ms": round(CAMERA_WARMUP_RETRY_DELAY_SECONDS * 1000),
    }
    data = result.get("data")
    if isinstance(data, Mapping):
        annotated_data = dict(data)
        annotated_data["camera_warmup"] = evidence
        annotated["data"] = annotated_data
    else:
        annotated["camera_warmup"] = evidence
    return annotated


def _capture_with_warmup_retry(
    connection: "IsaacConnection",
    command: str,
    params: Dict[str, Any],
) -> Mapping[str, Any]:
    """Capture once, allow one Kit render tick, then retry one time if needed.

    Camera capture is a time-dependent observation. Suppress inherited
    idempotency caching for both attempts so a transient not-ready response is
    not replayed in place of the rendered frame.
    """
    token = idempotency_key_var.set(None)
    try:
        result = connection.send_command(command, params)
        if not _camera_frame_not_ready(result):
            return result
        time.sleep(CAMERA_WARMUP_RETRY_DELAY_SECONDS)
        return _with_camera_warmup_evidence(connection.send_command(command, params))
    finally:
        idempotency_key_var.reset(token)


def _image_content_error(message: str) -> str:
    return json.dumps(
        {
            "status": "error",
            "code": "MCP_IMAGE_CONTENT_INVALID",
            "message": message,
        },
        indent=2,
    )


def _native_png_response(result: Mapping[str, Any]) -> str | NativeImageResponse:
    if str(result.get("status", "success")).lower() != "success":
        return json.dumps(dict(result), indent=2)

    nested_data = result.get("data")
    nested_envelope = isinstance(nested_data, Mapping)
    inline = nested_data.get("inline") if nested_envelope else result.get("inline")
    if not isinstance(inline, Mapping):
        return _image_content_error("Camera response did not include an inline PNG payload")
    if inline.get("encoding") != "base64" or inline.get("format") != "png":
        return _image_content_error("Camera response inline payload is not a base64 PNG")
    if inline.get("mime_type") != "image/png":
        return _image_content_error("Camera response MIME type must be image/png")

    data_base64 = inline.get("data")
    if not isinstance(data_base64, str):
        return _image_content_error("Camera response inline PNG data must be a base64 string")
    try:
        png_bytes = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError):
        return _image_content_error("Camera response contained invalid base64 PNG data")

    size_bytes = inline.get("size_bytes")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes != len(png_bytes):
        return _image_content_error("Camera response PNG size does not match its declared size_bytes")
    sha256 = inline.get("sha256")
    if not isinstance(sha256, str) or hashlib.sha256(png_bytes).hexdigest() != sha256.lower():
        return _image_content_error("Camera response PNG SHA-256 verification failed")

    metadata = dict(result)
    inline_metadata = {key: value for key, value in inline.items() if key != "data"}
    if nested_envelope:
        data = dict(nested_data)
        data["return_mode"] = "image"
        data["inline"] = inline_metadata
        metadata["data"] = data
    else:
        metadata["return_mode"] = "image"
        metadata["inline"] = inline_metadata
    return NativeImageResponse(response=metadata, data_base64=data_base64, mime_type="image/png")


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    @mcp.tool("delete_sensor")
    def delete_sensor(prim_path: str, post_delete_updates: int = 8) -> str:
        """Release and delete one Camera or LiDAR, then verify it stays absent.

        Args:
            prim_path: Managed Camera or LiDAR prim path.
            post_delete_updates: Kit updates used to detect delayed prim or render-product reappearance. Range 1 to 240.
        """
        try:
            result = get_connection().send_command(
                "sensors.delete",
                {"prim_path": prim_path, "post_delete_updates": post_delete_updates},
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("create_camera")
    def create_camera(
        prim_path: str = "/World/Camera",
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        resolution: Optional[List[int]] = None,
    ) -> str:
        """Add a camera sensor to the scene.

        Args:
            prim_path: Prim path for the camera.
            position: [x, y, z] world position.
            rotation: [rx, ry, rz] rotation in degrees.
            resolution: [width, height] image resolution. Default 1280x720.
        """
        try:
            conn = get_connection()
            params = {"prim_path": prim_path}
            if position:
                params["position"] = position
            if rotation:
                params["rotation"] = rotation
            if resolution:
                params["resolution"] = resolution
            result = conn.send_command("sensors.create_camera", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("capture_image")
    def capture_image(
        prim_path: str = "/World/Camera",
        output_path: Optional[str] = None,
        return_mode: CameraReturnMode = "artifact",
        inline_max_bytes: int = 1024 * 1024,
    ) -> str:
        """Capture an RGB image from a camera sensor.

        Args:
            prim_path: Prim path of the camera.
            output_path: Optional explicit .png path for artifact mode. If omitted, uses the managed artifact root.
            return_mode: metadata, artifact, inline, or image. Image returns MCP-native ImageContent.
            inline_max_bytes: Maximum PNG bytes allowed in inline mode. Maximum configurable value is 4 MiB.
        """
        try:
            conn = get_connection()
            native_image = return_mode.strip().lower() == "image"
            params = {
                "prim_path": prim_path,
                "return_mode": "inline" if native_image else return_mode,
                "inline_max_bytes": inline_max_bytes,
            }
            if output_path:
                params["output_path"] = output_path
            result = _capture_with_warmup_retry(conn, "sensors.capture_image", params)
            if native_image:
                return _native_png_response(result)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("capture_camera_output")
    def capture_camera_output(
        prim_path: str = "/World/Camera",
        output_type: str = "depth",
        output_path: Optional[str] = None,
        return_mode: CameraReturnMode = "artifact",
        inline_max_bytes: int = 1024 * 1024,
    ) -> str:
        """Capture RGB or a typed RTX camera annotator output.

        Args:
            prim_path: Prim path of the camera.
            output_type: rgb, depth, distance_to_image_plane, semantic_segmentation,
                instance_segmentation, instance_id_segmentation, normals, or motion_vectors.
            output_path: Optional RGB image path or typed-output .npy path for artifact mode.
            return_mode: metadata, artifact, inline, or image. Image is supported for RGB only.
            inline_max_bytes: Maximum raw bytes allowed in inline mode. Maximum is 4 MiB.
        """
        try:
            normalized_output_type = output_type.strip().lower()
            native_image = return_mode.strip().lower() == "image"
            if native_image and normalized_output_type != "rgb":
                return json.dumps(
                    {
                        "status": "unsupported",
                        "code": "CAMERA_IMAGE_CONTENT_UNSUPPORTED",
                        "message": "return_mode='image' is only supported for output_type='rgb'",
                    },
                    indent=2,
                )
            conn = get_connection()
            params = {
                "prim_path": prim_path,
                "return_mode": "inline" if native_image else return_mode,
                "inline_max_bytes": inline_max_bytes,
            }
            if output_path:
                params["output_path"] = output_path
            if normalized_output_type == "rgb":
                result = _capture_with_warmup_retry(conn, "sensors.capture_image", params)
            else:
                params["output_type"] = output_type
                result = _capture_with_warmup_retry(conn, "sensors.capture_camera_output", params)
            if native_image:
                return _native_png_response(result)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_camera_calibration")
    def get_camera_calibration(prim_path: str = "/World/Camera") -> str:
        """Read camera intrinsics, extrinsics, projection, resolution, and units."""
        try:
            conn = get_connection()
            result = conn.send_command("sensors.get_camera_calibration", {"prim_path": prim_path})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("create_lidar")
    def create_lidar(
        prim_path: str = "/World/Lidar",
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        config: Optional[str] = None,
        variant: Optional[Union[str, Dict[str, str]]] = None,
        horizontal_fov_deg: Optional[float] = None,
        vertical_fov_deg: Optional[float] = None,
        horizontal_resolution_deg: Optional[float] = None,
        vertical_resolution_deg: Optional[float] = None,
        rotation_rate_hz: Optional[float] = None,
        min_range_m: Optional[float] = None,
        max_range_m: Optional[float] = None,
    ) -> str:
        """Add a lidar sensor to the scene.

        Args:
            prim_path: Prim path for the lidar.
            position: [x, y, z] world position.
            rotation: [rx, ry, rz] rotation in degrees.
            config: Isaac Sim 6 supported preset name, such as Example_Rotary or OS1.
            variant: Optional preset variant string or variant-set mapping.
            horizontal_fov_deg: Generic sensor horizontal field of view in degrees.
            vertical_fov_deg: Generic sensor vertical field of view in degrees.
            horizontal_resolution_deg: Generic sensor horizontal angular resolution.
            vertical_resolution_deg: Generic sensor vertical angular resolution.
            rotation_rate_hz: Integer generic rotary scan rate from 1 to 100 Hz.
            min_range_m: Generic sensor minimum range in meters.
            max_range_m: Generic sensor maximum range in meters.
        """
        try:
            conn = get_connection()
            params = {"prim_path": prim_path}
            if position:
                params["position"] = position
            if rotation:
                params["rotation"] = rotation
            if config:
                params["config"] = config
            if variant is not None:
                params["variant"] = variant
            optional_settings = {
                "horizontal_fov_deg": horizontal_fov_deg,
                "vertical_fov_deg": vertical_fov_deg,
                "horizontal_resolution_deg": horizontal_resolution_deg,
                "vertical_resolution_deg": vertical_resolution_deg,
                "rotation_rate_hz": rotation_rate_hz,
                "min_range_m": min_range_m,
                "max_range_m": max_range_m,
            }
            params.update({name: value for name, value in optional_settings.items() if value is not None})
            result = conn.send_command("sensors.create_lidar", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_lidar_config")
    def get_lidar_config(prim_path: str = "/World/Lidar") -> str:
        """Read effective LiDAR FOV, angular resolution, rate, range, and USD schema values."""
        try:
            conn = get_connection()
            result = conn.send_command("sensors.get_lidar_config", {"prim_path": prim_path})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_lidar_point_cloud")
    def get_lidar_point_cloud(
        prim_path: str = "/World/Lidar",
        output_path: Optional[str] = None,
        return_mode: str = "artifact",
        inline_max_bytes: int = 1024 * 1024,
    ) -> str:
        """Get typed point cloud fields from a lidar sensor.

        Args:
            prim_path: Prim path of the lidar sensor.
            output_path: Optional explicit .npz path for artifact mode.
            return_mode: metadata, artifact, or inline. Defaults to artifact.
            inline_max_bytes: Maximum encoded NPZ bytes allowed in inline mode.
        """
        try:
            conn = get_connection()
            params = {
                "prim_path": prim_path,
                "return_mode": return_mode,
                "inline_max_bytes": inline_max_bytes,
            }
            if output_path:
                params["output_path"] = output_path
            result = conn.send_command("sensors.get_point_cloud", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})
