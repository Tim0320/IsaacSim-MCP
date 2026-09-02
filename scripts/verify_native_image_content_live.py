#!/usr/bin/env python3
"""Guarded live verification for Camera PNG to MCP ImageContent handoff."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import uuid
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import ImageContent, TextContent

from scripts.verify_camera_rgb_live import _decode_png

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


def _text_envelope(result: Any) -> dict[str, Any]:
    text = next(item.text for item in result.content if isinstance(item, TextContent))
    envelope = json.loads(text)
    assert set(envelope) == REQUIRED_ENVELOPE_FIELDS, sorted(set(envelope) ^ REQUIRED_ENVELOPE_FIELDS)
    return envelope


async def _call(session: ClientSession, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return _text_envelope(await session.call_tool(name, arguments or {}))


async def _verify_session(session: ClientSession) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    root = f"/World/MCP_Native_Image_{run_id}"
    cube_path = f"{root}/Cube"
    light_path = f"{root}/Light"
    camera_path = f"{root}/Camera"
    initial_timeline_state = "unknown"
    cleanup: dict[str, Any] = {}
    listed_tools = await session.list_tools()
    capture_schema = next(tool for tool in listed_tools.tools if tool.name == "capture_camera_output")
    assert capture_schema.inputSchema["properties"]["return_mode"]["enum"] == [
        "metadata",
        "artifact",
        "inline",
        "image",
    ]
    state = await _call(session, "get_simulation_state")
    assert state["status"] == "success", state
    initial_timeline_state = state["data"]["timeline_state"]
    if initial_timeline_state == "playing":
        paused = await _call(session, "pause_simulation")
        assert paused["status"] == "success", paused

    try:
        cube = await _call(
            session,
            "create_object",
            {
                "object_type": "Cube",
                "prim_path": cube_path,
                "position": [0.0, 0.0, 0.0],
                "size": 1.0,
                "color": [0.9, 0.1, 0.1],
                "physics_enabled": False,
            },
        )
        assert cube["status"] == "success", cube
        light = await _call(
            session,
            "create_light",
            {
                "light_type": "DistantLight",
                "prim_path": light_path,
                "rotation": [45.0, 0.0, 45.0],
                "intensity": 5000.0,
            },
        )
        assert light["status"] == "success", light
        camera = await _call(
            session,
            "create_camera",
            {
                "prim_path": camera_path,
                "position": [3.0, 3.0, 2.0],
                "rotation": [65.0, 0.0, 135.0],
                "resolution": [160, 90],
            },
        )
        assert camera["status"] == "success", camera
        readback = await _call(session, "get_prim_info", {"prim_path": camera_path})
        assert readback["status"] == "success" and readback["data"]["path"] == camera_path, readback

        played = await _call(session, "play_simulation")
        assert played["status"] == "success", played
        await asyncio.sleep(1)

        resized = await _call(
            session,
            "create_camera",
            {
                "prim_path": camera_path,
                "position": [3.0, 3.0, 2.0],
                "rotation": [65.0, 0.0, 135.0],
                "resolution": [640, 360],
            },
        )
        assert resized["status"] == "success", resized

        # Deliberately make exactly one public MCP call after the resolution
        # transition. The server owns the bounded frame warm-up and one retry.
        result = await session.call_tool(
            "capture_camera_output",
            {
                "prim_path": camera_path,
                "output_type": "rgb",
                "return_mode": "image",
                "inline_max_bytes": 1024 * 1024,
            },
        )
        envelope = _text_envelope(result)
        assert envelope["status"] == "success", envelope

        image_blocks = [item for item in result.content if isinstance(item, ImageContent)]
        assert len(image_blocks) == 1, result.content
        image_block = image_blocks[0]
        assert image_block.mimeType == "image/png"
        png = base64.b64decode(image_block.data, validate=True)
        width, height, channels, pixels = _decode_png(png)
        inline = envelope["data"]["inline"]
        warmup = envelope["data"]["camera_warmup"]
        assert "data" not in inline
        assert inline["size_bytes"] == len(png)
        assert inline["sha256"] == hashlib.sha256(png).hexdigest()
        assert [height, width, channels] == envelope["data"]["image"]["shape"] == [360, 640, 3]
        assert warmup == {"attempted": True, "capture_attempts": 2, "delay_ms": 500}
        assert any(pixels), "captured RGB image is entirely black"
        assert result.structuredContent == {
            "result": next(item.text for item in result.content if isinstance(item, TextContent))
        }

        summary = {
            "isaac_sim_version": state["data"]["isaacsim_version"],
            "physics_backend": state["data"]["engine"],
            "initial_timeline_state": initial_timeline_state,
            "camera_prim": camera_path,
            "shape": [height, width, channels],
            "png_bytes": len(png),
            "png_sha256": hashlib.sha256(png).hexdigest(),
            "native_image_content": True,
            "metadata_contains_base64": False,
            "nonzero_rgb_bytes": sum(value != 0 for value in pixels),
            "schema_return_mode_enum": ["metadata", "artifact", "inline", "image"],
            "resolution_transition": [[160, 90], [640, 360]],
            "public_capture_calls": 1,
            "camera_warmup": warmup,
        }
    finally:
        cleanup["pause"] = await _call(session, "pause_simulation")
        cleanup["camera"] = await _call(
            session,
            "delete_sensor",
            {"prim_path": camera_path, "post_delete_updates": 16},
        )
        cleanup["root"] = await _call(session, "delete_object", {"prim_path": root})
        absent = await _call(session, "get_prim_info", {"prim_path": root})
        cleanup["root_absent"] = absent["status"] != "success"

        if initial_timeline_state == "playing":
            cleanup["timeline_restore"] = await _call(session, "play_simulation")
        elif initial_timeline_state == "paused":
            cleanup["timeline_restore"] = await _call(session, "pause_simulation")
        else:
            cleanup["timeline_restore"] = await _call(session, "stop_simulation")

    assert cleanup["camera"]["status"] == "success", cleanup
    assert cleanup["root_absent"] is True, cleanup
    assert cleanup["timeline_restore"]["status"] == "success", cleanup
    summary["cleanup_verified"] = True
    return summary


async def main() -> int:
    url = os.getenv("ISAAC_MCP_VERIFIER_URL")
    if url:
        async with streamable_http_client(url) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                summary = await _verify_session(session)
        summary["transport"] = "streamable-http"
    else:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "isaac_mcp.server"],
            env={
                **os.environ,
                "ISAAC_MCP_HOST": "127.0.0.1",
                "ISAAC_MCP_PORT": "8766",
                "ISAAC_MCP_TOOL_PROFILE": "legacy",
            },
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                summary = await _verify_session(session)
        summary["transport"] = "stdio"

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
