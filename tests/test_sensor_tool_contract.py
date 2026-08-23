"""MCP-facing sensor argument forwarding tests."""

from __future__ import annotations

import json

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
