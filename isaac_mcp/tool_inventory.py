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

from isaac_mcp.tool_profiles import resolve_tool_profile, select_tool_names

TOOLS_ROOT = Path(__file__).resolve().parent / "tools"
MCP_LOCAL_TOOL_NAMES = frozenset({"get_runtime_status"})


def _full_inventory() -> list[dict[str, Any]]:
    """Return every decorated tool before profile filtering."""
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


def inventory(profile: str | None = "legacy") -> list[dict[str, Any]]:
    """Return named tools for one public profile; legacy remains the default."""
    records = _full_inventory()
    selected = set(select_tool_names((item["tool"] for item in records), resolve_tool_profile(profile)))
    return [item for item in records if item["tool"] in selected]


def all_tool_names() -> tuple[str, ...]:
    """Return every decorated tool across all profiles."""
    names = tuple(item["tool"] for item in _full_inventory())
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate public MCP tool names found in source decorators")
    return names


def tool_names(profile: str | None = "legacy") -> tuple[str, ...]:
    """Return the unique public tool names for one profile."""
    names = all_tool_names()
    return select_tool_names(names, resolve_tool_profile(profile))


def tool_count(profile: str | None = "legacy") -> int:
    """Return the source-derived public tool count."""
    return len(tool_names(profile))


def extension_tool_names(profile: str | None = "legacy") -> tuple[str, ...]:
    """Return public tools whose implementation requires an extension command."""
    names = tool_names(profile)
    unknown = MCP_LOCAL_TOOL_NAMES.difference(names)
    if unknown:
        raise RuntimeError(f"unknown MCP-local tools: {sorted(unknown)}")
    return tuple(name for name in names if name not in MCP_LOCAL_TOOL_NAMES)


def extension_tool_count(profile: str | None = "legacy") -> int:
    """Return the expected active extension command count."""
    return len(extension_tool_names(profile))


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
