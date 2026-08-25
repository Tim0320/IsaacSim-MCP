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

"""The command router must await asynchronous handlers such as spawn_human."""

import asyncio
from unittest.mock import MagicMock

from isaac_sim_mcp_extension.extension import MCPExtension


def test_execute_command_awaits_async_handler():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = MagicMock()

    async def handler(**params):
        await asyncio.sleep(0)
        return {"status": "success", "value": params["value"]}

    extension._registry = {"async.test": handler}
    response = asyncio.run(extension._execute_command({"type": "async.test", "params": {"value": 7}}))

    assert response["status"] == "success"
    assert response["code"] == "OK"
    assert response["data"]["value"] == 7
    assert response["data"]["command"]["write"] is True
    assert response["data"]["command"]["apply_state"] == "applied"
    assert response["command_id"]
    assert response["timing"]["extension_ms"] >= 0


def test_capabilities_are_available_before_the_stage_exists():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = None
    extension._registry = {"system.get_capabilities": lambda **_params: {"status": "success", "schema_version": "1.0"}}

    response = asyncio.run(extension._execute_command({"type": "system.get_capabilities", "params": {}}))

    assert response["status"] == "success"
    assert response["data"]["command"]["write"] is False
    assert response["data"]["command"]["apply_state"] == "not_applicable"


def test_execute_command_preserves_non_success_statuses():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = MagicMock()
    extension._registry = {
        "partial.test": lambda **_params: {
            "status": "error",
            "message": "One field was ignored",
            "applied": ["gravity"],
            "unsupported": ["time_step"],
        },
        "cancel.test": lambda **_params: {"status": "cancelled", "message": "Stopped"},
    }

    partial = asyncio.run(extension._execute_command({"type": "partial.test", "params": {}}))
    cancelled = asyncio.run(extension._execute_command({"type": "cancel.test", "params": {}}))

    assert partial["status"] == "partial"
    assert partial["code"] == "PARTIAL_SUCCESS"
    assert partial["data"]["unsupported"] == ["time_step"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["code"] == "CANCELLED"


def test_execute_command_returns_stable_codes_for_router_errors():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = None
    extension._registry = {"scene.test": lambda **_params: {"status": "success"}}

    pending = asyncio.run(extension._execute_command({"type": "scene.test", "params": {}, "command_id": "same-id"}))
    unknown = asyncio.run(extension._execute_command({"type": "missing.test", "params": {}}))

    assert pending["status"] == "error"
    assert pending["code"] == "STAGE_NOT_READY"
    assert pending["command_id"] == "same-id"
    assert unknown["status"] == "error"
    assert unknown["code"] == "UNKNOWN_COMMAND"


def test_idempotency_replays_once_and_rejects_key_reuse_for_another_payload():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = MagicMock()
    calls = []

    def handler(**params):
        calls.append(params)
        return {"status": "success", "data": {"created": f"/World/Cube_{len(calls)}"}, "readback": {"exists": True}}

    extension._registry = {"object.create": handler}
    first = asyncio.run(
        extension._execute_command(
            {"type": "object.create", "params": {"name": "cube"}, "command_id": "cmd-1", "idempotency_key": "cube-1"}
        )
    )
    replay = asyncio.run(
        extension._execute_command(
            {"type": "object.create", "params": {"name": "cube"}, "command_id": "cmd-2", "idempotency_key": "cube-1"}
        )
    )
    conflict = asyncio.run(
        extension._execute_command(
            {"type": "object.create", "params": {"name": "sphere"}, "command_id": "cmd-3", "idempotency_key": "cube-1"}
        )
    )

    assert len(calls) == 1
    assert first["data"]["created"] == "/World/Cube_1"
    assert first["data"]["command"]["replayed"] is False
    assert replay["command_id"] == "cmd-2"
    assert replay["data"]["created"] == "/World/Cube_1"
    assert replay["data"]["command"]["replayed"] is True
    assert replay["data"]["command"]["original_command_id"] == "cmd-1"
    assert conflict["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_command_metadata_fails_closed_before_dispatch():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = MagicMock()
    handler = MagicMock(return_value={"status": "success"})
    extension._registry = {"object.create": handler}

    bad_key = asyncio.run(
        extension._execute_command(
            {"type": "object.create", "params": {}, "command_id": "cmd", "idempotency_key": "contains spaces"}
        )
    )
    bad_params = asyncio.run(extension._execute_command({"type": "object.create", "params": [], "command_id": "cmd"}))

    assert bad_key["code"] == "INVALID_COMMAND_METADATA"
    assert bad_key["data"]["command"]["apply_state"] == "not_applied"
    assert bad_params["code"] == "INVALID_COMMAND_PARAMS"
    assert bad_params["data"]["command"]["apply_state"] == "not_applied"
    handler.assert_not_called()


def test_preview_write_is_not_reported_as_applied():
    extension = MCPExtension()
    extension._adapter = MagicMock()
    extension._adapter.get_stage.return_value = MagicMock()
    extension._registry = {"stage.set_attribute": lambda **_params: {"status": "success", "preview": True}}

    response = asyncio.run(
        extension._execute_command({"type": "stage.set_attribute", "params": {"preview": True}, "command_id": "cmd"})
    )

    assert response["data"]["command"]["write"] is True
    assert response["data"]["command"]["apply_state"] == "preview"
