"""Single-source-of-truth contracts for tools, versions, and capabilities."""

from __future__ import annotations

import re
from pathlib import Path

from isaac_mcp.tool_inventory import extension_tool_count, tool_count, tool_names
from isaac_mcp.tools import register_all_tools

ROOT = Path(__file__).resolve().parents[1]


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


def test_registered_tools_equal_source_decorator_inventory():
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: None)
    assert set(mcp.tools) == set(tool_names())
    assert len(mcp.tools) == tool_count()


def test_package_metadata_does_not_hardcode_a_tool_count():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    description = re.search(r'^description\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert description
    assert not re.search(r"\b\d+\s+tools?\b", description.group(1), re.IGNORECASE)


def test_mcp_local_runtime_status_is_not_counted_as_an_extension_command():
    assert "get_runtime_status" in tool_names()
    assert extension_tool_count() == tool_count() - 1


def test_authority_document_separates_source_runtime_and_history():
    authority = (ROOT / "docs" / "reference" / "AUTHORITY.md").read_text(encoding="utf-8")
    for value in ("@mcp.tool", "isaac_mcp.__version__", "get_capabilities", "docs/research/"):
        assert value in authority
