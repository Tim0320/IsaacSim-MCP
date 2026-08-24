"""Replicator handler validation, deterministic trace, and lifecycle tests."""

import asyncio
from types import SimpleNamespace

import pytest
from isaac_sim_mcp_extension.handlers import replicator


@pytest.fixture(autouse=True)
def clean_jobs():
    replicator._JOBS.clear()
    replicator._ACTIVE_JOB = None
    yield
    replicator._JOBS.clear()
    replicator._ACTIVE_JOB = None


def _valid_config(**overrides):
    value = {
        "camera_prim_path": "/World/Camera",
        "frame_count": 2,
        "annotations": ["rgb", "semantic_segmentation"],
        "resolution": [320, 240],
        "seed": 7,
        "randomizers": [
            {
                "type": "transform",
                "prim_paths": ["/World/Cube"],
                "position_min": [-1, 0, 0],
                "position_max": [1, 0, 0],
            }
        ],
        "rt_subframes": 1,
        "delta_time": 0.0,
    }
    value.update(overrides)
    return value


def test_preview_normalizes_writer_trigger_annotations_and_randomizer_graph():
    result = replicator.create_job(**_valid_config(), preview=True)

    assert result["status"] == "success"
    config = result["data"]["would_create"]
    assert config["writer"] == {"name": "BasicWriter", "managed_artifacts": True}
    assert config["trigger"] == {"mode": "manual", "count": 2}
    assert config["annotations"] == ["rgb", "semantic_segmentation"]
    assert config["randomizers"][0]["position_range"] == [[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]


@pytest.mark.parametrize(
    "override,message",
    [
        ({"frame_count": 0}, "frame_count"),
        ({"annotations": ["rgb", "rgb"]}, "duplicates"),
        ({"annotations": ["not_real"]}, "unsupported annotations"),
        ({"annotations": ["bounding_box_2d_tight"]}, "unsupported annotations"),
        ({"resolution": [5000, 10]}, "resolution"),
        ({"seed": -1}, "seed"),
        ({"randomizers": [{"type": "script", "prim_paths": ["/World/Cube"]}]}, "type"),
    ],
)
def test_invalid_configs_fail_closed_without_creating_jobs(override, message):
    result = replicator.create_job(**_valid_config(**override), preview=False)

    assert result["code"] == "INVALID_SDG_CONFIG"
    assert message in result["message"]
    assert replicator._JOBS == {}


def test_fixed_seed_produces_identical_randomization_trace(monkeypatch):
    class _Attr:
        def __init__(self):
            self.value = (0.0, 0.0, 0.0)

        def Get(self):
            return self.value

        def Set(self, value):
            self.value = value
            return True

    attrs = {}
    monkeypatch.setattr(replicator, "_stage_attribute", lambda path, name: attrs.setdefault((path, name), _Attr()))
    config = replicator._validate_config(**_valid_config())

    def run():
        job = {"config": config}
        rng = __import__("random").Random(config["seed"])
        return [replicator._randomized_values(job, frame, rng) for frame in range(3)]

    assert run() == run()


def test_start_is_non_blocking_and_single_active_job_is_enforced(monkeypatch):
    async def exercise():
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_run(job):
            job["state"] = "running"
            started.set()
            await release.wait()
            job["state"] = "completed"
            job["finished_epoch"] = 1.0
            job["manifest"] = {"job_id": job["job_id"]}
            replicator._ACTIVE_JOB = None

        monkeypatch.setattr(replicator, "_run_job", fake_run)
        job = {
            "job_id": "sdg-one",
            "state": "configured",
            "config": replicator._validate_config(**_valid_config()),
            "frames_requested": 2,
            "frames_completed": 0,
            "created_epoch": 0.0,
            "started_epoch": None,
            "finished_epoch": None,
            "manifest": None,
            "artifacts": [],
            "cleanup": {"writer_detached": True, "render_product_destroyed": True, "trigger_removed": True},
            "cancel_requested": False,
            "task": None,
        }
        replicator._JOBS[job["job_id"]] = job

        result = replicator.start_job("sdg-one", preview=False)
        await started.wait()
        conflict = replicator.start_job("sdg-one", preview=False)

        assert result["readback"] == {"active_job_id": "sdg-one", "state": "starting"}
        assert conflict["code"] == "SDG_JOB_STATE_CONFLICT"
        release.set()
        await job["task"]

    asyncio.run(exercise())


def test_configured_job_cancel_is_terminal_and_delete_has_readback(monkeypatch):
    monkeypatch.setattr(replicator, "_make_manifest", lambda job, **_kw: {"job_id": job["job_id"]})
    job = {
        "job_id": "sdg-cancel",
        "state": "configured",
        "config": {},
        "frames_requested": 2,
        "frames_completed": 0,
        "created_epoch": 0.0,
        "started_epoch": None,
        "finished_epoch": None,
        "manifest": None,
        "artifacts": [],
        "cleanup": {"writer_detached": True, "render_product_destroyed": True, "trigger_removed": True},
        "cancel_requested": False,
        "task": None,
    }
    replicator._JOBS[job["job_id"]] = job

    cancelled = replicator.cancel_job(job["job_id"], preview=False)
    deleted = replicator.delete_job(job["job_id"], preview=False)

    assert cancelled["readback"]["state"] == "cancelled"
    assert deleted["readback"] == {"job_exists": False}
    assert replicator._JOBS == {}


def test_status_reports_no_owned_writer_or_trigger_when_idle(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "omni.kit.app", SimpleNamespace())
    result = replicator.get_status()

    assert result["data"]["active_job_count"] == 0
    assert result["data"]["writer_attached"] is False
    assert result["data"]["trigger_active"] is False
