"""Contract tests for the unified 128-tool evidence artifact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_all_tools_report.py"
RESULT = ROOT / "docs" / "ALL_TOOLS_TEST_RESULTS.json"


def _module():
    spec = importlib.util.spec_from_file_location("generate_all_tools_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_inventory_and_evidence_cover_all_128_named_tools():
    report = _module().build(None)
    assert report["tool_count"] == 128
    assert len({item["tool"] for item in report["results"]}) == 128
    assert all(item["purpose"] and item["input"] is not None for item in report["results"])
    assert all(item["readback"] and item["evidence"]["source"] for item in report["results"])


def test_status_taxonomy_keeps_external_blockers_separate_from_failures():
    report = _module().build(None)
    by_name = {item["tool"]: item for item in report["results"]}
    assert by_name["search_usd"]["status"] == "blocked"
    assert by_name["generate_3d"]["status"] == "blocked"
    assert by_name["spawn_nvidia_asset"]["status"] == "blocked"
    assert by_name["search_usd"]["blocker"]["type"] == "external_configuration"
    assert by_name["spawn_nvidia_asset"]["blocker"]["type"] == "runtime_prerequisite"
    assert report["counts"].get("fail", 0) == 0


def test_tracked_machine_artifact_has_no_missing_or_extra_tools():
    artifact = json.loads(RESULT.read_text(encoding="utf-8"))
    source_names = {item["tool"] for item in _module().inventory()}
    artifact_names = {item["tool"] for item in artifact["results"]}
    assert artifact["tool_count"] == 128
    assert artifact_names == source_names


def test_every_static_evidence_source_exists_in_the_repository():
    report = _module().build(None)
    for item in report["results"]:
        source = item["evidence"]["source"]
        assert (ROOT / source).exists(), f"missing evidence source for {item['tool']}: {source}"
