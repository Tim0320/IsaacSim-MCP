# MIT License
# Copyright (c) 2026 whats2000

"""Source-derived inventory for public MCP tools.

The ``@mcp.tool(<name>)`` decorators under :mod:`isaac_mcp.tools` are the
authority for public tool names and counts. Documentation and verification
code consume this module instead of maintaining a separate numeric constant.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parent / "tools"


def inventory() -> list[dict[str, Any]]:
    """Return every named tool with its module, purpose, and public inputs."""
    tools: list[dict[str, Any]] = []
    for path in sorted(TOOLS_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = _tool_name(node)
            if name is None:
                continue
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
            inputs = [
                {
                    "name": argument.arg,
                    "required": default is None,
                    "default": None if default is None else ast.unparse(default),
                }
                for argument, default in zip(node.args.args, defaults)
                if argument.arg != "self"
            ]
            doc = ast.get_docstring(node) or ""
            tools.append(
                {
                    "tool": name,
                    "module": path.stem,
                    "purpose": doc.splitlines()[0].strip() if doc else "Public Isaac Sim MCP operation.",
                    "input": inputs,
                }
            )
    return sorted(tools, key=lambda item: item["tool"])


def tool_names() -> tuple[str, ...]:
    """Return the unique public tool names and fail closed on duplicates."""
    names = tuple(item["tool"] for item in inventory())
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate public MCP tool names found in source decorators")
    return names


def tool_count() -> int:
    """Return the source-derived public tool count."""
    return len(tool_names())


def _tool_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            return decorator.args[0].value
    return None
