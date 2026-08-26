"""Documentation information-architecture and local-link contracts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EXPECTED_SECTIONS = {"getting-started", "concepts", "reference", "development", "research"}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def test_docs_root_is_an_index_plus_the_five_authoritative_sections():
    assert {path.name for path in DOCS.iterdir() if path.is_dir()} == EXPECTED_SECTIONS
    assert {path.name for path in DOCS.iterdir() if path.is_file()} == {"README.md"}


def test_all_local_markdown_links_resolve():
    broken = []
    for path in (ROOT / "docs").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if target and not (path.parent / target).resolve().exists():
                line = text.count("\n", 0, match.start()) + 1
                broken.append(f"{path.relative_to(ROOT)}:{line} -> {match.group(1)}")
    assert not broken, "\n".join(broken)
