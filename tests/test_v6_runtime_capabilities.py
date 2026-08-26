from isaac_sim_mcp_extension.adapters.base import IsaacAdapterBase
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.capabilities import CapabilityRuntime


class _Context:
    active_backend = "physx"


def _runtime(context: _Context) -> CapabilityRuntime:
    return CapabilityRuntime(context, IsaacAdapterBase._backend_capability)


def test_capability_runtime_reads_active_backend_for_each_matrix() -> None:
    context = _Context()
    runtime = _runtime(context)

    assert runtime.get_backend_capability_matrix()["active_backend"] == "physx"
    context.active_backend = "newton"
    assert runtime.get_backend_capability_matrix()["active_backend"] == "newton"


def test_capability_runtime_preserves_schema_policy_and_feature_set() -> None:
    matrix = _runtime(_Context()).get_backend_capability_matrix()

    assert matrix["schema_version"] == "1.0"
    assert matrix["policy"] == {
        "supported_requires_live_verification": True,
        "null_supported_means": "untested",
        "false_supported_means": "unsupported",
    }
    assert set(matrix["features"]) == {
        "motion.ik_and_planning",
        "physics.body_authoring",
        "physics.collision_groups",
        "physics.gpu_enabled",
        "physics.gravity",
        "physics.joint_authoring",
        "physics.materials",
        "physics.state",
        "physics.time_step",
        "robot.gripper_profiles",
        "robot.joint_command",
        "robot.joint_drive_config",
        "robot.joint_drive_config.max_velocity",
        "robot.joint_state",
        "robot.mobile_base_profiles",
        "sensor.camera",
        "sensor.lidar",
        "sensor.lifecycle",
        "simulation.reset",
        "simulation.step",
        "simulation.timeline",
    }


def test_v6_facade_forwards_capability_matrix() -> None:
    expected = {"schema_version": "1.0", "active_backend": "physx", "features": {}}
    adapter = object.__new__(IsaacAdapterV6)
    adapter._capability_runtime = type(
        "CapabilityRuntimeStub",
        (),
        {"get_backend_capability_matrix": lambda self: expected},
    )()

    assert adapter.get_backend_capability_matrix() is expected
