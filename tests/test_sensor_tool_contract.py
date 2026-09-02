"""MCP-facing sensor argument forwarding tests."""

from __future__ import annotations

import base64
import hashlib
import json

from isaac_mcp.command_context import idempotency_key_var
from isaac_mcp.responses import NativeImageResponse
from isaac_mcp.tools.sensors import register_tools


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    def __init__(self):
        self.calls = []

    def send_command(self, command, params=None):
        self.calls.append((command, params))
        return {"status": "success", "data": {}}


def _inline_png_response(png: bytes = b"valid-png-payload"):
    return {
        "status": "success",
        "message": "Camera image captured",
        "return_mode": "inline",
        "image": {"width": 1, "height": 1, "channels": 3},
        "inline": {
            "encoding": "base64",
            "format": "png",
            "mime_type": "image/png",
            "size_bytes": len(png),
            "sha256": hashlib.sha256(png).hexdigest(),
            "data": base64.b64encode(png).decode("ascii"),
        },
    }


def test_delete_sensor_forwards_lifecycle_verification_window():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(mcp.tools["delete_sensor"](prim_path="/World/TestCamera", post_delete_updates=32))

    assert response["status"] == "success"
    assert connection.calls == [("sensors.delete", {"prim_path": "/World/TestCamera", "post_delete_updates": 32})]


def test_create_lidar_forwards_preset_variant_and_generic_settings():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(
        mcp.tools["create_lidar"](
            prim_path="/World/TestLidar",
            position=[1.0, 2.0, 3.0],
            config=None,
            horizontal_fov_deg=120.0,
            vertical_fov_deg=20.0,
            horizontal_resolution_deg=0.5,
            vertical_resolution_deg=2.0,
            rotation_rate_hz=10,
            min_range_m=0.5,
            max_range_m=80.0,
        )
    )

    assert response["status"] == "success"
    assert connection.calls == [
        (
            "sensors.create_lidar",
            {
                "prim_path": "/World/TestLidar",
                "position": [1.0, 2.0, 3.0],
                "horizontal_fov_deg": 120.0,
                "vertical_fov_deg": 20.0,
                "horizontal_resolution_deg": 0.5,
                "vertical_resolution_deg": 2.0,
                "rotation_rate_hz": 10,
                "min_range_m": 0.5,
                "max_range_m": 80.0,
            },
        )
    ]


def test_get_lidar_config_forwards_lidar_path():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(mcp.tools["get_lidar_config"](prim_path="/World/TestLidar"))

    assert response["status"] == "success"
    assert connection.calls == [("sensors.get_lidar_config", {"prim_path": "/World/TestLidar"})]


def test_capture_image_forwards_return_mode_limit_and_output_path():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(
        mcp.tools["capture_image"](
            prim_path="/World/TestCamera",
            output_path="D:/captures/frame.png",
            return_mode="artifact",
            inline_max_bytes=12345,
        )
    )

    assert response["status"] == "success"
    assert connection.calls == [
        (
            "sensors.capture_image",
            {
                "prim_path": "/World/TestCamera",
                "return_mode": "artifact",
                "inline_max_bytes": 12345,
                "output_path": "D:/captures/frame.png",
            },
        )
    ]


def test_capture_image_maps_image_mode_to_verified_native_png_content():
    mcp = _MCP()
    connection = _Connection()
    connection.send_command = lambda command, params: (
        connection.calls.append((command, params)) or _inline_png_response()
    )
    register_tools(mcp, lambda: connection)

    response = mcp.tools["capture_image"](
        prim_path="/World/TestCamera",
        return_mode="image",
        inline_max_bytes=12345,
    )

    assert isinstance(response, NativeImageResponse)
    assert response.mime_type == "image/png"
    assert "data" not in response.response["inline"]
    assert response.response["return_mode"] == "image"
    assert connection.calls == [
        (
            "sensors.capture_image",
            {
                "prim_path": "/World/TestCamera",
                "return_mode": "inline",
                "inline_max_bytes": 12345,
            },
        )
    ]


def test_capture_image_fails_closed_when_inline_png_integrity_is_invalid():
    mcp = _MCP()
    connection = _Connection()
    invalid = _inline_png_response()
    invalid["inline"]["sha256"] = "0" * 64
    connection.send_command = lambda _command, _params: invalid
    register_tools(mcp, lambda: connection)

    response = json.loads(mcp.tools["capture_image"](return_mode="image"))

    assert response["status"] == "error"
    assert response["code"] == "MCP_IMAGE_CONTENT_INVALID"


def test_capture_camera_output_rejects_native_image_for_non_rgb_output():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(
        mcp.tools["capture_camera_output"](
            output_type="depth",
            return_mode="image",
        )
    )

    assert response["status"] == "unsupported"
    assert response["code"] == "CAMERA_IMAGE_CONTENT_UNSUPPORTED"
    assert connection.calls == []


def test_capture_camera_output_routes_rgb_image_mode_to_native_png_content():
    mcp = _MCP()
    connection = _Connection()
    connection.send_command = lambda command, params: (
        connection.calls.append((command, params)) or _inline_png_response()
    )
    register_tools(mcp, lambda: connection)

    response = mcp.tools["capture_camera_output"](
        prim_path="/World/TestCamera",
        output_type="rgb",
        return_mode="image",
    )

    assert isinstance(response, NativeImageResponse)
    assert connection.calls == [
        (
            "sensors.capture_image",
            {
                "prim_path": "/World/TestCamera",
                "return_mode": "inline",
                "inline_max_bytes": 1024 * 1024,
            },
        )
    ]


def test_capture_camera_output_warms_up_and_retries_within_one_tool_call(monkeypatch):
    class _WarmupConnection:
        def __init__(self):
            self.calls = []
            self.keys = []

        def send_command(self, command, params=None):
            self.calls.append((command, params))
            self.keys.append(idempotency_key_var.get())
            if len(self.calls) == 1:
                return {
                    "status": "error",
                    "code": "CAMERA_FRAME_NOT_READY",
                    "message": "A render has been requested",
                }
            return _inline_png_response()

    mcp = _MCP()
    connection = _WarmupConnection()
    monkeypatch.setattr("isaac_mcp.tools.sensors.time.sleep", lambda seconds: None)
    register_tools(mcp, lambda: connection)
    context_token = idempotency_key_var.set("camera-request")
    try:
        response = mcp.tools["capture_camera_output"](
            prim_path="/World/TestCamera",
            output_type="rgb",
            return_mode="image",
        )
        assert idempotency_key_var.get() == "camera-request"
    finally:
        idempotency_key_var.reset(context_token)

    assert isinstance(response, NativeImageResponse)
    assert len(connection.calls) == 2
    assert connection.calls[0] == connection.calls[1]
    assert connection.keys == [None, None]
    assert response.response["camera_warmup"] == {
        "attempted": True,
        "capture_attempts": 2,
        "delay_ms": 500,
    }


def test_capture_image_retries_at_most_once_when_frame_remains_unavailable(monkeypatch):
    mcp = _MCP()
    connection = _Connection()
    response = {
        "status": "error",
        "message": "No frame available from /World/TestCamera yet. A render has been requested",
    }
    connection.send_command = lambda command, params: connection.calls.append((command, params)) or response
    monkeypatch.setattr("isaac_mcp.tools.sensors.time.sleep", lambda seconds: None)
    register_tools(mcp, lambda: connection)

    result = json.loads(mcp.tools["capture_image"](prim_path="/World/TestCamera", return_mode="metadata"))

    assert result["status"] == "error"
    assert result["camera_warmup"] == {
        "attempted": True,
        "capture_attempts": 2,
        "delay_ms": 500,
    }
    assert len(connection.calls) == 2


def test_capture_camera_output_forwards_typed_annotator_arguments():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(
        mcp.tools["capture_camera_output"](
            prim_path="/World/TestCamera",
            output_type="normals",
            output_path="D:/captures/normals.npy",
            return_mode="artifact",
            inline_max_bytes=54321,
        )
    )

    assert response["status"] == "success"
    assert connection.calls == [
        (
            "sensors.capture_camera_output",
            {
                "prim_path": "/World/TestCamera",
                "output_type": "normals",
                "return_mode": "artifact",
                "inline_max_bytes": 54321,
                "output_path": "D:/captures/normals.npy",
            },
        )
    ]


def test_get_camera_calibration_forwards_camera_path():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(mcp.tools["get_camera_calibration"](prim_path="/World/TestCamera"))

    assert response["status"] == "success"
    assert connection.calls == [("sensors.get_camera_calibration", {"prim_path": "/World/TestCamera"})]


def test_get_lidar_point_cloud_forwards_transfer_contract():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    response = json.loads(
        mcp.tools["get_lidar_point_cloud"](
            prim_path="/World/TestLidar",
            output_path="D:/captures/cloud.npz",
            return_mode="artifact",
            inline_max_bytes=123456,
        )
    )

    assert response["status"] == "success"
    assert connection.calls == [
        (
            "sensors.get_point_cloud",
            {
                "prim_path": "/World/TestLidar",
                "return_mode": "artifact",
                "inline_max_bytes": 123456,
                "output_path": "D:/captures/cloud.npz",
            },
        )
    ]
