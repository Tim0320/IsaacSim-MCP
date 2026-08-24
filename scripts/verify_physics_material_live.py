#!/usr/bin/env python3
"""Scratch-only live acceptance for item 14 physics material schema."""

from __future__ import annotations

import json

from isaac_mcp.connection import IsaacConnection

ROOT = "/World/MCP_Task_3_4"
LOW = f"{ROOT}/Materials/Low"
HIGH = f"{ROOT}/Materials/High"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _readback(response: dict) -> dict:
    assert response["status"] == "success", response
    assert isinstance(response.get("readback"), dict), response
    return response["readback"]


def main() -> int:
    connection = IsaacConnection(port=8766)
    bodies = {
        "LowSlide": ([-6, -3, 0.55], "Cube"),
        "HighSlide": ([-6, 3, 0.55], "Cube"),
        "LowBounce": ([20, -3, 5], "Sphere"),
        "HighBounce": ([20, 3, 5], "Sphere"),
    }
    grounds = {
        "LowSlideGround": ([0, -3, -0.25], [15, 2, 0.25]),
        "HighSlideGround": ([0, 3, -0.25], [15, 2, 0.25]),
        "LowBounceGround": ([20, -3, -0.25], [3, 2, 0.25]),
        "HighBounceGround": ([20, 3, -0.25], [3, 2, 0.25]),
    }
    try:
        _data(connection.send_command("simulation.stop"))
        if connection.send_command("scene.get_prim_info", {"prim_path": ROOT})["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))

        low = _readback(
            connection.send_command(
                "materials.create",
                {
                    "material_type": "physics",
                    "prim_path": LOW,
                    "static_friction": 0.0,
                    "dynamic_friction": 0.0,
                    "restitution": 0.0,
                },
            )
        )
        high = _readback(
            connection.send_command(
                "materials.create",
                {
                    "material_type": "physics",
                    "prim_path": HIGH,
                    "static_friction": 1.0,
                    "dynamic_friction": 0.8,
                    "restitution": 0.9,
                },
            )
        )

        for name, (position, scale) in grounds.items():
            path = f"{ROOT}/{name}"
            _data(
                connection.send_command(
                    "objects.create",
                    {
                        "object_type": "Cube",
                        "prim_path": path,
                        "position": position,
                        "scale": scale,
                        "physics_enabled": False,
                    },
                )
            )
            _readback(
                connection.send_command(
                    "physics.configure_body",
                    {
                        "prim_path": path,
                        "body_type": "static",
                        "collider_enabled": True,
                    },
                )
            )
        for name, (position, object_type) in bodies.items():
            path = f"{ROOT}/{name}"
            _data(
                connection.send_command(
                    "objects.create",
                    {
                        "object_type": object_type,
                        "prim_path": path,
                        "position": position,
                        "size": 1.0,
                        "physics_enabled": False,
                    },
                )
            )
            _readback(
                connection.send_command(
                    "physics.configure_body",
                    {
                        "prim_path": path,
                        "body_type": "dynamic",
                        "collider_enabled": True,
                        "mass_kg": 1.0,
                    },
                )
            )

        low_targets = [f"{ROOT}/LowSlideGround", f"{ROOT}/LowBounceGround", f"{ROOT}/LowSlide", f"{ROOT}/LowBounce"]
        high_targets = [
            f"{ROOT}/HighSlideGround",
            f"{ROOT}/HighBounceGround",
            f"{ROOT}/HighSlide",
            f"{ROOT}/HighBounce",
        ]
        binding_evidence = []
        for material_path, targets in ((LOW, low_targets), (HIGH, high_targets)):
            for target in targets:
                binding = _readback(
                    connection.send_command(
                        "materials.apply",
                        {
                            "material_path": material_path,
                            "target_prim_path": target,
                            "material_purpose": "auto",
                        },
                    )
                )
                queried = _data(
                    connection.send_command(
                        "materials.get_binding",
                        {
                            "target_prim_path": target,
                            "material_purpose": "physics",
                        },
                    )
                )
                assert binding["material_path"] == material_path
                assert queried["material_path"] == material_path
                assert queried["relationship"].endswith("material:binding:physics")
                binding_evidence.append(queried)

        observed = [f"{ROOT}/{name}" for name in bodies]
        _data(connection.send_command("simulation.step", {"num_steps": 1, "observe_prims": observed}))
        velocity_code = f"""
import json
import numpy as np
import warp as wp
from isaacsim.core.simulation_manager import SimulationManager
view = SimulationManager.get_physics_simulation_view()
readback = {{}}
for path in ({f"{ROOT}/LowSlide"!r}, {f"{ROOT}/HighSlide"!r}):
    rigid = view.create_rigid_body_view([path])
    values = wp.array([[4, 0, 0, 0, 0, 0]], dtype=wp.float32, device=view.device)
    indices = wp.array([0], dtype=wp.uint32, device=view.device)
    rigid.set_velocities(values, indices)
    value = rigid.get_velocities()
    value = value.numpy() if hasattr(value, "numpy") else np.asarray(value)
    readback[path] = [float(item) for item in value.reshape(-1)[:6]]
print(json.dumps(readback))
"""
        velocity_result = _data(connection.send_command("simulation.execute_script", {"code": velocity_code}))
        assert "4.0" in velocity_result["stdout"], velocity_result

        contact = {"LowBounce": False, "HighBounce": False}
        post_contact_max = {"LowBounce": 0.0, "HighBounce": 0.0}
        final_positions = {}
        for _sample in range(36):
            stepped = _data(connection.send_command("simulation.step", {"num_steps": 5, "observe_prims": observed}))
            states = {item["prim_path"].rsplit("/", 1)[-1]: item["position"] for item in stepped["prim_states"]}
            final_positions = states
            for name in contact:
                z = float(states[name][2])
                if z <= 0.7:
                    contact[name] = True
                elif contact[name]:
                    post_contact_max[name] = max(post_contact_max[name], z)

        slide_delta = float(final_positions["LowSlide"][0]) - float(final_positions["HighSlide"][0])
        assert contact == {"LowBounce": True, "HighBounce": True}, contact
        assert slide_delta > 2.0, {"positions": final_positions, "slide_delta": slide_delta}
        assert post_contact_max["HighBounce"] > 1.5, post_contact_max
        assert post_contact_max["HighBounce"] - post_contact_max["LowBounce"] > 1.0, post_contact_max

        _data(connection.send_command("simulation.stop"))
        invalid = connection.send_command(
            "materials.create",
            {
                "material_type": "physics",
                "prim_path": f"{ROOT}/Materials/Invalid",
                "static_friction": 0.2,
                "dynamic_friction": 0.3,
                "restitution": 0.0,
            },
        )
        assert invalid["status"] == "error" and invalid["code"] == "INVALID_MATERIAL", invalid
        assert (
            connection.send_command("scene.get_prim_info", {"prim_path": f"{ROOT}/Materials/Invalid"})["status"]
            == "error"
        )

        print(
            json.dumps(
                {
                    "status": "success",
                    "scratch_root": ROOT,
                    "materials": {"low": low, "high": high},
                    "binding_count": len(binding_evidence),
                    "final_positions_after_181_steps": final_positions,
                    "low_minus_high_slide_x_m": slide_delta,
                    "post_contact_max_z_m": post_contact_max,
                },
                indent=2,
            )
        )
        return 0
    finally:
        connection.send_command("simulation.stop")
        deleted = connection.send_command("objects.delete", {"prim_path": ROOT})
        assert deleted["status"] == "success", deleted
        survivor = connection.send_command("scene.get_prim_info", {"prim_path": ROOT})
        assert survivor["status"] == "error", survivor


if __name__ == "__main__":
    raise SystemExit(main())
