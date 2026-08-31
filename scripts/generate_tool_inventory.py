#!/usr/bin/env python3
"""Generate or verify the source-derived public tool inventory."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from isaac_mcp import __version__
from isaac_mcp.tool_inventory import inventory

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = {
    "legacy": ROOT / "docs" / "reference" / "TOOL_INVENTORY.md",
    "consolidated": ROOT / "docs" / "reference" / "TOOL_INVENTORY_CONSOLIDATED.md",
}


def render(profile: str = "legacy") -> str:
    tools = inventory(profile)
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in tools:
        grouped[item["module"]].append(item["tool"])
    lines = [
        "# MCP Tool Inventory",
        "",
        "> 由 `scripts/generate_tool_inventory.py` 從 `isaac_mcp/tools/*.py` 與 `isaac_mcp/tool_profiles.py` 自動產生，請勿手工修改。",
        "",
        f"Package version：`{__version__}`",
        f"Tool profile：`{profile}`",
        f"Source-derived tool count：`{len(tools)}`",
        "",
        "| Module | 數量 | Named tools |",
        "|---|---:|---|",
    ]
    for module, names in sorted(grouped.items()):
        lines.append(f"| `{module}` | {len(names)} | " + ", ".join(f"`{name}`" for name in names) + " |")
    lines.extend(
        [
            "",
            "這份 inventory 證明 source 的 registration intent。目前 runtime support、backend state 與 prerequisites 以 `get_capabilities` 為準；live success 必須有 guarded read-back evidence。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the tracked inventory differs from source")
    args = parser.parse_args()
    counts = []
    for profile, output in OUTPUTS.items():
        expected = render(profile)
        if args.check:
            actual = output.read_text(encoding="utf-8") if output.exists() else ""
            if actual != expected:
                raise SystemExit(f"tracked {profile} tool inventory is stale; run scripts/generate_tool_inventory.py")
        else:
            output.write_text(expected, encoding="utf-8")
        counts.append(f"{profile}={len(inventory(profile))}")
    print(f"tools={','.join(counts)}; mode={'check' if args.check else 'write'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
