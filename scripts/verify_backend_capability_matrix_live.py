#!/usr/bin/env python3
"""Read-only Isaac Sim 6.0.1 live acceptance for Task 3.2."""

from __future__ import annotations

import json

from isaac_mcp.connection import IsaacConnection

EXPECTED_FEATURES = {
    "simulation.timeline",
    "simulation.step",
    "simulation.reset",
    "physics.state",
    "physics.gravity",
    "physics.time_step",
    "physics.gpu_enabled",
    "sensor.camera",
    "sensor.lidar",
    "sensor.lifecycle",
    "robot.joint_state",
    "robot.joint_command",
    "robot.joint_drive_config",
    "robot.joint_drive_config.max_velocity",
    "motion.ik_and_planning",
    "robot.gripper_profiles",
    "robot.mobile_base_profiles",
}

NEWTON_UNSUPPORTED = {
    "physics.time_step",
    "physics.gpu_enabled",
    "robot.joint_drive_config.max_velocity",
}


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    assert response["schema_version"] == "1.0", response
    return response["data"]


def main() -> int:
    connection = IsaacConnection(port=8766)
    scene_before = _data(connection.send_command("scene.get_info"))
    state_before = _data(connection.send_command("simulation.get_state"))
    capabilities = _data(connection.send_command("system.get_capabilities"))
    scene_after = _data(connection.send_command("scene.get_info"))
    state_after = _data(connection.send_command("simulation.get_state"))

    runtime = capabilities["runtime"]
    matrix = capabilities["backend_matrix"]
    features = matrix["features"]

    assert capabilities["capability_schema_version"] == "1.1"
    assert runtime["isaac_sim_version"].startswith("6.0.1"), runtime
    assert runtime["adapter"] == "IsaacAdapterV6", runtime
    assert runtime["physics_backend"] == "physx", runtime
    assert matrix["schema_version"] == "1.0"
    assert matrix["active_backend"] == "physx"
    assert matrix["policy"]["supported_requires_live_verification"] is True
    assert set(features) == EXPECTED_FEATURES

    for name, record in features.items():
        assert record["physx_supported"] is True, {name: record}
        assert record["backends"]["physx"]["state"] == "supported", {name: record}
        assert record["backends"]["physx"]["verification"] == "verified", {name: record}
        if name in NEWTON_UNSUPPORTED:
            assert record["newton_supported"] is False, {name: record}
            assert record["untested"] == [], {name: record}
            assert record["backends"]["newton"]["state"] == "unsupported", {name: record}
        else:
            assert record["newton_supported"] is None, {name: record}
            assert record["untested"] == ["newton"], {name: record}
            assert record["backends"]["newton"]["state"] == "untested", {name: record}
        assert record["backends"]["newton"]["verification"] == "untested", {name: record}

    flags = capabilities["feature_flags"]
    assert flags["simulation.timeline"]["state"] == "supported"
    assert flags["simulation.step"]["state"] == "supported"
    assert flags["simulation.reset"]["state"] == "supported"
    assert flags["physics.state"]["state"] == "supported"
    assert flags["physics.time_step"]["state"] == "supported"
    assert flags["physics.gpu_enabled"]["state"] == "supported"
    assert flags["camera.rgb_pixels"]["state"] == "supported"
    assert flags["lidar.point_cloud"]["state"] == "supported"
    assert flags["robot.joint_command"]["state"] == "supported"

    assert scene_after == scene_before, {"before": scene_before, "after": scene_after}
    assert state_after == state_before, {"before": state_before, "after": state_after}

    print(
        json.dumps(
            {
                "pass": True,
                "runtime": runtime,
                "capability_schema_version": capabilities["capability_schema_version"],
                "matrix_schema_version": matrix["schema_version"],
                "feature_count": len(features),
                "physx_verified": len(features),
                "newton_supported": 0,
                "newton_untested": len(features) - len(NEWTON_UNSUPPORTED),
                "newton_unsupported": len(NEWTON_UNSUPPORTED),
                "scene_unchanged": True,
                "simulation_state_unchanged": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
