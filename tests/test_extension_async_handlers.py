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

    assert response == {"status": "success", "result": {"status": "success", "value": 7}}
