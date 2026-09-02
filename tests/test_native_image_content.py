"""Protocol-level contract for MCP-native camera image responses."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ImageContent, TextContent

from isaac_mcp.responses import normalize_response
from isaac_mcp.tools import register_all_tools


class _ImageConnection:
    port = 8766

    def send_command(self, command, params=None):
        assert command == "sensors.capture_image"
        assert params == {
            "prim_path": "/World/Camera",
            "return_mode": "inline",
            "inline_max_bytes": 1024 * 1024,
        }
        png = b"protocol-image-payload"
        return normalize_response(
            {
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
        )


def test_mcp_protocol_returns_text_metadata_and_native_image_content():
    async def exercise():
        mcp = FastMCP("native-image-contract")
        register_all_tools(mcp, lambda: _ImageConnection())
        tool = mcp._tool_manager.get_tool("capture_camera_output")
        assert tool is not None
        assert tool.output_schema["properties"]["result"]["type"] == "string"
        assert tool.parameters["properties"]["return_mode"]["enum"] == [
            "metadata",
            "artifact",
            "inline",
            "image",
        ]
        capture_image = mcp._tool_manager.get_tool("capture_image")
        assert capture_image is not None
        assert capture_image.parameters["properties"]["return_mode"]["enum"] == [
            "metadata",
            "artifact",
            "inline",
            "image",
        ]

        async with create_connected_server_and_client_session(mcp) as session:
            result = await session.call_tool(
                "capture_camera_output",
                {"prim_path": "/World/Camera", "output_type": "rgb", "return_mode": "image"},
            )

        assert result.isError is False
        assert len(result.content) == 2
        assert isinstance(result.content[0], TextContent)
        assert isinstance(result.content[1], ImageContent)
        assert result.content[1].mimeType == "image/png"
        assert base64.b64decode(result.content[1].data, validate=True) == b"protocol-image-payload"

        envelope = json.loads(result.content[0].text)
        assert envelope["status"] == "success"
        assert envelope["data"]["return_mode"] == "image"
        assert "data" not in envelope["data"]["inline"]
        assert result.structuredContent == {"result": result.content[0].text}

    asyncio.run(exercise())
