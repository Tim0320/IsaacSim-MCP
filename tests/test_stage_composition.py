# MIT License
# Copyright (c) 2026 whats2000

"""Contracts for guarded Stage/layer/composition MCP operations."""

from __future__ import annotations

from pathlib import Path

from isaac_sim_mcp_extension.handlers import stage_composition


class _Adapter:
    def __init__(self, *, playing: bool = False):
        self.playing = playing

    def get_simulation_state(self):
        return {"timeline_state": "playing" if self.playing else "stopped", "playing": self.playing}


def test_register_exposes_all_twelve_stage_commands():
    registry = {}
    stage_composition.register(registry, _Adapter())

    assert sorted(registry) == [
        "stage.apply_batch",
        "stage.edit_composition_arc",
        "stage.edit_sublayer",
        "stage.get_attribute",
        "stage.get_composition",
        "stage.get_semantics",
        "stage.new",
        "stage.open",
        "stage.save_as",
        "stage.set_attribute",
        "stage.set_semantics",
        "stage.set_variant",
    ]


def test_destructive_stage_lifecycle_fails_closed_without_scratch_guard(tmp_path):
    adapter = _Adapter()

    assert stage_composition.new_stage(adapter)["code"] == "SCRATCH_STAGE_REQUIRED"
    assert stage_composition.open_stage(adapter, str(tmp_path / "input.usda"))["code"] == "SCRATCH_STAGE_REQUIRED"
    assert stage_composition.save_stage_as(adapter, str(tmp_path / "output.usda"))["code"] == "SCRATCH_STAGE_REQUIRED"


def test_scratch_path_cannot_escape_declared_root(tmp_path):
    root = tmp_path / "guard"
    root.mkdir()
    outside = tmp_path / "outside.usda"
    outside.write_text("#usda 1.0\n", encoding="utf-8")

    result = stage_composition.open_stage(
        _Adapter(), str(outside), scratch_stage=True, scratch_root=str(root), preview=True
    )

    assert result["status"] == "error"
    assert result["code"] == "PATH_OUTSIDE_SCRATCH_ROOT"


def test_open_preview_requires_existing_file_inside_scratch_root(tmp_path):
    result = stage_composition.open_stage(
        _Adapter(),
        str(tmp_path / "missing.usda"),
        scratch_stage=True,
        scratch_root=str(tmp_path),
        preview=True,
    )

    assert result["code"] == "STAGE_FILE_NOT_FOUND"


def test_lifecycle_requires_existing_scratch_directory(tmp_path):
    missing_root = tmp_path / "missing"

    result = stage_composition.new_stage(_Adapter(), scratch_stage=True, scratch_root=str(missing_root), preview=True)

    assert result["code"] == "SCRATCH_ROOT_NOT_FOUND"


def test_open_preview_rejects_non_usd_extension(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("#usda 1.0\n", encoding="utf-8")

    result = stage_composition.open_stage(
        _Adapter(), str(source), scratch_stage=True, scratch_root=str(tmp_path), preview=True
    )

    assert result["code"] == "INVALID_STAGE_EXTENSION"


def test_save_as_preview_rejects_non_usd_extension(tmp_path):
    result = stage_composition.save_stage_as(
        _Adapter(),
        str(tmp_path / "output.txt"),
        scratch_stage=True,
        scratch_root=str(tmp_path),
        preview=True,
    )

    assert result["code"] == "INVALID_STAGE_EXTENSION"


def test_writes_require_stopped_timeline(tmp_path):
    result = stage_composition.new_stage(
        _Adapter(playing=True), scratch_stage=True, scratch_root=str(tmp_path), preview=True
    )

    assert result["code"] == "TIMELINE_NOT_STOPPED"


def test_batch_rejects_empty_oversized_and_stage_lifecycle_operations():
    adapter = _Adapter()

    assert stage_composition.apply_stage_batch(adapter, [])["code"] == "INVALID_BATCH"
    assert (
        stage_composition.apply_stage_batch(adapter, [{"operation": "set_attribute"}] * 101)["code"]
        == "BATCH_TOO_LARGE"
    )
    result = stage_composition.apply_stage_batch(adapter, [{"operation": "open_stage", "path": "x.usda"}])
    assert result["code"] == "INVALID_BATCH_OPERATION"


def test_semantic_validation_requires_unique_non_empty_label_array():
    adapter = _Adapter()

    assert stage_composition.set_semantic_labels(adapter, "/World/X", "class", [])["code"] == "INVALID_SEMANTIC_LABEL"
    assert (
        stage_composition.set_semantic_labels(adapter, "/World/X", "class", ["box", "box"])["code"]
        == "INVALID_SEMANTIC_LABEL"
    )
    assert stage_composition.set_semantic_labels(adapter, "/World/X", "class", [1])["code"] == (
        "INVALID_SEMANTIC_LABEL"
    )
    assert stage_composition.set_semantic_labels(adapter, "/World/X", "", ["box"])["code"] == "INVALID_SEMANTIC_LABEL"


def test_guarded_path_accepts_nested_target_and_normalizes_it(tmp_path):
    root = tmp_path / "scratch"
    target = root / "nested" / "stage.usda"

    assert stage_composition._guarded_path(str(target), str(root)) == Path(target).resolve(strict=False)
