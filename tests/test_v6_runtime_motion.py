from __future__ import annotations

from typing import Any

import pytest
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.motion import MotionRuntime


class _MotionSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._motion_trajectories: dict[str, dict[str, Any]] = {}
        self._motion_jobs: dict[str, dict[str, Any]] = {}
        self._motion_update_subscription = None

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"result:{name}"

        return call


def _adapter(runtime: Any) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    adapter._motion_runtime = runtime
    return adapter


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        ("_motion_base_pose", ("/World/Robot",), {}, "result:_motion_base_pose"),
        (
            "compute_ik",
            ("/World/Robot", [0.4, 0.0, 0.5]),
            {},
            "result:compute_ik",
        ),
        (
            "plan_joint_trajectory",
            ("/World/Robot", [0.0] * 7),
            {},
            "result:plan_joint_trajectory",
        ),
        ("_ensure_motion_subscription", (), {}, None),
        ("execute_trajectory", ("traj-1", 1000), {}, "result:execute_trajectory"),
        ("_on_motion_update", (object(),), {}, None),
        ("cancel_motion", ("motion-1",), {}, "result:cancel_motion"),
        ("get_motion_status", ("motion-1",), {}, "result:get_motion_status"),
        ("shutdown_motion", (), {}, None),
    ],
)
def test_motion_facade_methods_forward_without_contract_changes(method, args, kwargs, expected) -> None:
    runtime = _MotionSpy()

    result = getattr(_adapter(runtime), method)(*args, **kwargs)

    assert result == expected
    assert len(runtime.calls) == 1
    forwarded_method, forwarded_args, forwarded_kwargs = runtime.calls[0]
    assert forwarded_method == method
    assert forwarded_args[: len(args)] == args
    assert forwarded_kwargs == kwargs


def test_motion_runtime_owns_all_motion_state_and_depends_on_robot_runtime() -> None:
    scene = object()
    robots = object()
    runtime = MotionRuntime(scene, robots)
    adapter = _adapter(runtime)

    assert runtime._scene is scene
    assert runtime._robots is robots
    assert adapter._motion_trajectories is runtime._motion_trajectories
    assert adapter._motion_jobs is runtime._motion_jobs
    assert adapter._motion_update_subscription is runtime._motion_update_subscription
    assert "_motion_trajectories" not in adapter.__dict__
    assert "_motion_jobs" not in adapter.__dict__
    assert "_motion_update_subscription" not in adapter.__dict__
    assert not hasattr(runtime, "_job_manager")


def test_shutdown_motion_cancels_active_jobs_and_releases_owned_resources() -> None:
    runtime = MotionRuntime(object(), object())
    runtime._motion_trajectories["traj-1"] = {"id": "traj-1"}
    runtime._motion_jobs.update(
        {
            "queued": {"state": "queued"},
            "running": {"state": "running"},
            "paused": {"state": "paused"},
            "completed": {"state": "completed"},
        }
    )
    runtime._motion_update_subscription = object()

    runtime.shutdown_motion()

    assert [runtime._motion_jobs[key]["state"] for key in ("queued", "running", "paused")] == [
        "cancelled",
        "cancelled",
        "cancelled",
    ]
    assert runtime._motion_jobs["completed"]["state"] == "completed"
    assert runtime._motion_trajectories == {}
    assert runtime._motion_update_subscription is None
