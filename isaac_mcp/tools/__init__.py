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
from typing import TYPE_CHECKING, Any, Callable, Optional, get_type_hints

from mcp.types import CallToolResult, ImageContent, TextContent

from isaac_mcp.command_context import command_id_var, idempotency_key_var
from isaac_mcp.responses import NativeImageResponse, normalize_response
from isaac_mcp.runtime_status import IsaacRuntimeUnavailableError
from isaac_mcp.tool_profiles import ADDED_CONSOLIDATED_TOOLS, REPLACED_LEGACY_TOOLS, resolve_tool_profile

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
        consolidated,
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
    profile = resolve_tool_profile()
    schema_mcp.tool_profile = profile
    runtime_aware_connection = _runtime_aware_connection_provider(get_connection)

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
        consolidated,
    ]:
        module.register_tools(schema_mcp, runtime_aware_connection)

    hidden = (
        ADDED_CONSOLIDATED_TOOLS if profile == "legacy" else REPLACED_LEGACY_TOOLS if profile == "consolidated" else ()
    )
    for name in hidden:
        _remove_registered_tool(mcp, name)


def _remove_registered_tool(mcp: FastMCP, name: str) -> None:
    """Remove a tool from real FastMCP or the lightweight contract-test fake."""
    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None and hasattr(manager, "remove_tool"):
        manager.remove_tool(name)
        return
    tools = getattr(mcp, "tools", None)
    if isinstance(tools, dict):
        tools.pop(name, None)
        return
    raise TypeError(f"MCP implementation cannot remove profile-hidden tool {name!r}")


class _RuntimeAwareConnection:
    """Keep legacy tool-local catch blocks from discarding runtime diagnostics."""

    def __init__(self, connection: IsaacConnection | None, unavailable: IsaacRuntimeUnavailableError | None = None):
        self._connection = connection
        self._unavailable = unavailable

    def __getattr__(self, name: str) -> Any:
        if self._connection is not None:
            return getattr(self._connection, name)
        if name == "port" and self._unavailable is not None:
            return self._unavailable.status.get("port", 8766)
        raise AttributeError(name)

    def send_command(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self._unavailable is not None:
            return self._unavailable.to_response()
        if self._connection is None:  # pragma: no cover - guarded by provider construction
            raise RuntimeError("runtime-aware connection has no underlying connection")
        try:
            return self._connection.send_command(*args, **kwargs)
        except IsaacRuntimeUnavailableError as exc:
            return exc.to_response()


def _runtime_aware_connection_provider(
    get_connection: Callable[[], IsaacConnection],
) -> Callable[[], _RuntimeAwareConnection]:
    def provide() -> _RuntimeAwareConnection:
        try:
            return _RuntimeAwareConnection(get_connection())
        except IsaacRuntimeUnavailableError as exc:
            return _RuntimeAwareConnection(None, exc)

    return provide


def _serialize_tool_response(value: Any, elapsed_ms: float) -> str | CallToolResult:
    native_image = value if isinstance(value, NativeImageResponse) else None
    response = native_image.response if native_image is not None else value
    envelope = normalize_response(response, timing={"mcp_tool_ms": round(elapsed_ms, 3)})
    serialized = json.dumps(envelope, indent=2, sort_keys=True)
    if native_image is None:
        return serialized
    return CallToolResult(
        content=[
            TextContent(type="text", text=serialized),
            ImageContent(type="image", data=native_image.data_base64, mimeType=native_image.mime_type),
        ],
        structuredContent={"result": serialized},
    )


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
        async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            tokens = enter_command_context(kwargs)
            try:
                value = await function(*args, **kwargs)
            except asyncio.CancelledError:
                value = {"status": "cancelled", "code": "CANCELLED", "message": "Tool execution was cancelled"}
            except TimeoutError as exc:
                value = {"status": "timeout", "code": "TIMEOUT", "message": str(exc)}
            except IsaacRuntimeUnavailableError as exc:
                value = exc.to_response()
            except Exception as exc:
                value = {"status": "error", "code": "MCP_TOOL_ERROR", "message": str(exc)}
            finally:
                exit_command_context(tokens)
            return _serialize_tool_response(value, (time.perf_counter() - started) * 1000)

        wrapped = async_wrapped

    else:

        @functools.wraps(function)
        def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            tokens = enter_command_context(kwargs)
            try:
                value = function(*args, **kwargs)
            except TimeoutError as exc:
                value = {"status": "timeout", "code": "TIMEOUT", "message": str(exc)}
            except IsaacRuntimeUnavailableError as exc:
                value = exc.to_response()
            except Exception as exc:
                value = {"status": "error", "code": "MCP_TOOL_ERROR", "message": str(exc)}
            finally:
                exit_command_context(tokens)
            return _serialize_tool_response(value, (time.perf_counter() - started) * 1000)

        wrapped = sync_wrapped

    original = inspect.signature(function)
    try:
        resolved_hints = get_type_hints(function)
    except (NameError, TypeError):
        resolved_hints = {}
    parameters = [
        parameter.replace(annotation=resolved_hints.get(parameter.name, parameter.annotation))
        for parameter in original.parameters.values()
    ]
    insertion = len(parameters)
    for index, parameter in enumerate(parameters):
        if parameter.kind in (Parameter.VAR_KEYWORD,):
            insertion = index
            break
    metadata = [
        Parameter("command_id", kind=Parameter.KEYWORD_ONLY, default=None, annotation=Optional[str]),
        Parameter("idempotency_key", kind=Parameter.KEYWORD_ONLY, default=None, annotation=Optional[str]),
    ]
    wrapped.__signature__ = Signature(
        parameters[:insertion] + metadata + parameters[insertion:],
        return_annotation=resolved_hints.get("return", str),
    )
    return wrapped


class _ResponseSchemaMCP:
    """Proxy FastMCP so every registered tool receives the same envelope."""

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp
        self._original_tools: dict[str, Callable[..., Any]] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mcp, name)

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        register = self._mcp.tool(*args, **kwargs)

        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            name = args[0] if args else kwargs.get("name") or function.__name__
            self._original_tools[str(name)] = function
            return register(_wrap_tool(function))

        return decorator

    def call_registered_tool(self, name: str, **kwargs: Any) -> Any:
        """Invoke an unwrapped tool implementation for consolidated dispatch."""
        try:
            function = self._original_tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown registered tool {name!r}") from exc
        return function(**kwargs)
