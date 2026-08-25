"""Contract tests for the unified bounded job lifecycle."""

import asyncio

import pytest
from isaac_sim_mcp_extension.handlers import jobs


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs._JOBS.clear()
    jobs._REGISTRY = {}
    yield
    jobs._JOBS.clear()
    jobs._REGISTRY = {}


def test_managed_job_completes_and_requery_does_not_execute_twice():
    calls = []

    async def run():
        async def capture(**params):
            calls.append(params)
            await asyncio.sleep(0)
            return {"status": "success", "data": {"shape": [1, 1, 4]}}

        jobs._REGISTRY = {"sensors.capture_image": capture}
        started = jobs.start_job("sensors.capture_image", {"prim_path": "/World/Camera"}, 1000)
        job_id = started["data"]["job_id"]
        await jobs._JOBS[job_id]["task"]
        first = jobs.get_job_status(job_id)
        second = jobs.get_job_status(job_id)
        return first, second

    first, second = asyncio.run(run())
    assert first["data"]["state"] == "succeeded"
    assert second["data"]["result"] == first["data"]["result"]
    assert len(calls) == 1


def test_cancel_reaches_predictable_terminal_state():
    async def run():
        async def slow(**_params):
            await asyncio.Event().wait()

        jobs._REGISTRY = {"assets.load_usd": slow}
        started = jobs.start_job("assets.load_usd", {"usd_url": "safe.usd"}, 1000)
        job_id = started["data"]["job_id"]
        cancelled = jobs.cancel_job(job_id)
        await asyncio.sleep(0)
        return cancelled, jobs.get_job_status(job_id)

    cancelled, status = asyncio.run(run())
    assert cancelled["status"] == "cancelled"
    assert status["data"]["state"] == "cancelled"
    assert status["data"]["terminal"] is True


def test_deadline_and_allowlist_fail_closed():
    jobs._REGISTRY = {"simulation.execute_script": lambda **_p: {"status": "success"}}
    denied = jobs.start_job("simulation.execute_script", {}, 1000)
    invalid = jobs.start_job("sensors.capture_image", {}, 0)
    assert denied["code"] == "JOB_COMMAND_NOT_ALLOWED"
    assert invalid["code"] == "INVALID_JOB_REQUEST"


def test_motion_and_sdg_ids_route_to_existing_providers():
    jobs._REGISTRY = {
        "motion.get_status": lambda **p: {"status": "success", "job_id": p["job_id"]},
        "motion.cancel": lambda **p: {"status": "cancelled", "job_id": p["job_id"]},
        "replicator.get_job_status": lambda **p: {"status": "success", "job_id": p["job_id"]},
        "replicator.cancel_job": lambda **p: {"status": "success", "job_id": p["job_id"], "preview": p["preview"]},
    }
    assert jobs.get_job_status("motion-1")["job_id"] == "motion-1"
    assert jobs.cancel_job("motion-1")["status"] == "cancelled"
    assert jobs.get_job_status("sdg-1")["job_id"] == "sdg-1"
    assert jobs.cancel_job("sdg-1")["preview"] is False
