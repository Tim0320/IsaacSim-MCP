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

"""MCP tool modules for Isaac Sim."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import time
from inspect import Parameter, Signature
from typing import TYPE_CHECKING, Any, Callable, Optional

from isaac_mcp.command_context import command_id_var, idempotency_key_var
from isaac_mcp.responses import normalize_response

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from isaac_mcp.connection import IsaacConnection


def register_all_tools(mcp: FastMCP, get_connection: Callable[[], IsaacConnection]) -> None:
    """Register all MCP tools from submodules.

    Args:
        mcp: FastMCP server instance.
        get_connection: Callable that returns an IsaacConnection.
    """
    from . import (
        artifacts,
        assets,
        capabilities,
        controllers,
        graphs,
        humans,
        jobs,
        lighting,
        materials,
        motion,
        objects,
        physics,
        replicator,
        robots,
        ros2,
        scene,
        sensors,
        simulation,
    )

    schema_mcp = _ResponseSchemaMCP(mcp)

    for module in [
        capabilities,
        controllers,
        artifacts,
        scene,
        objects,
        physics,
        replicator,
        ros2,
        humans,
        jobs,
        lighting,
        robots,
        motion,
        sensors,
        materials,
        assets,
        simulation,
        graphs,
    ]:
        module.register_tools(schema_mcp, get_connection)


def _serialize_tool_response(value: Any, elapsed_ms: float) -> str:
    envelope = normalize_response(value, timing={"mcp_tool_ms": round(elapsed_ms, 3)})
    return json.dumps(envelope, indent=2, sort_keys=True)


def _wrap_tool(function: Callable[..., Any]) -> Callable[..., Any]:
    def enter_command_context(kwargs: dict[str, Any]) -> tuple[Any, Any]:
        command_id = kwargs.pop("command_id", None)
        idempotency_key = kwargs.pop("idempotency_key", None)
        return command_id_var.set(command_id), idempotency_key_var.set(idempotency_key)

    def exit_command_context(tokens: tuple[Any, Any]) -> None:
        command_id_var.reset(tokens[0])
        idempotency_key_var.reset(tokens[1])

    if inspect.iscoroutinefunction(function):

        @functools.wraps(function)
        async def async_wrapped(*args: Any, **kwargs: Any) -> str:
            started = time.perf_counter()
            tokens = enter_command_context(kwargs)
            try:
                value = await function(*args, **kwargs)
            except asyncio.CancelledError:
                value = {"status": "cancelled", "code": "CANCELLED", "message": "Tool execution was cancelled"}
            except TimeoutError as exc:
                value = {"status": "timeout", "code": "TIMEOUT", "message": str(exc)}
            except Exception as exc:
                value = {"status": "error", "code": "MCP_TOOL_ERROR", "message": str(exc)}
            finally:
                exit_command_context(tokens)
            return _serialize_tool_response(value, (time.perf_counter() - started) * 1000)

        wrapped = async_wrapped

    else:

        @functools.wraps(function)
        def sync_wrapped(*args: Any, **kwargs: Any) -> str:
            started = time.perf_counter()
            tokens = enter_command_context(kwargs)
            try:
                value = function(*args, **kwargs)
            except TimeoutError as exc:
                value = {"status": "timeout", "code": "TIMEOUT", "message": str(exc)}
            except Exception as exc:
                value = {"status": "error", "code": "MCP_TOOL_ERROR", "message": str(exc)}
            finally:
                exit_command_context(tokens)
            return _serialize_tool_response(value, (time.perf_counter() - started) * 1000)

        wrapped = sync_wrapped

    original = inspect.signature(function)
    parameters = list(original.parameters.values())
    insertion = len(parameters)
    for index, parameter in enumerate(parameters):
        if parameter.kind in (Parameter.VAR_KEYWORD,):
            insertion = index
            break
    metadata = [
        Parameter("command_id", kind=Parameter.KEYWORD_ONLY, default=None, annotation=Optional[str]),
        Parameter("idempotency_key", kind=Parameter.KEYWORD_ONLY, default=None, annotation=Optional[str]),
    ]
    wrapped.__signature__ = Signature(parameters[:insertion] + metadata + parameters[insertion:], return_annotation=str)
    return wrapped


class _ResponseSchemaMCP:
    """Proxy FastMCP so every registered tool receives the same envelope."""

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mcp, name)

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        register = self._mcp.tool(*args, **kwargs)

        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            return register(_wrap_tool(function))

        return decorator
