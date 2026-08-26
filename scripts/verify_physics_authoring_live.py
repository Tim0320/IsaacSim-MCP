#!/usr/bin/env python3
"""Scratch-only live acceptance for Task 3.3 typed physics authoring."""

from __future__ import annotations

import json

from isaac_mcp.connection import IsaacConnection

ROOT = "/World/MCP_Task_3_3"
GROUND_PLANE = "/World/groundPlane"


def _data(response: dict) -> dict:
    assert response["status"] == "success", response
    return response["data"]


def _readback(response: dict) -> dict:
    assert response["status"] == "success", response
    assert isinstance(response.get("readback"), dict), response
    return response["readback"]


def main() -> int:
    connection = IsaacConnection(port=8766)
    evidence = {}
    remove_generated_ground_plane = False
    try:
        _data(connection.send_command("simulation.stop"))
        ground_plane_before = connection.send_command("scene.get_prim_info", {"prim_path": GROUND_PLANE})
        if ground_plane_before["status"] == "success":
            evidence["ground_plane_preexisting"] = True
        else:
            assert "Prim not found" in ground_plane_before.get("message", ""), ground_plane_before
            evidence["ground_plane_preexisting"] = False
            remove_generated_ground_plane = True
        existing = connection.send_command("scene.get_prim_info", {"prim_path": ROOT})
        if existing["status"] == "success":
            _data(connection.send_command("objects.delete", {"prim_path": ROOT}))

        setup = r'''
import json
import omni.usd
from pxr import Gf, UsdGeom
stage = omni.usd.get_context().get_stage()
root = UsdGeom.Xform.Define(stage, "/World/MCP_Task_3_3")
mesh = UsdGeom.Mesh.Define(stage, "/World/MCP_Task_3_3/MeshCollider")
mesh.CreatePointsAttr([Gf.Vec3f(-0.5, -0.5, 0), Gf.Vec3f(0.5, -0.5, 0), Gf.Vec3f(0, 0.5, 0)])
mesh.CreateFaceVertexCountsAttr([3])
mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
print(json.dumps({"root": str(root.GetPath()), "mesh": str(mesh.GetPath())}))
'''
        _data(connection.send_command("simulation.execute_script", {"code": setup}))
        _data(connection.send_command("scene.create_physics", {"gravity": [0, 0, -9.81]}))
        for name, position in (
            ("GroupCollider", [0, 0, 0]),
            ("FixedAnchor", [5, 0, 3]),
            ("FixedBody", [5, 0, 3]),
            ("RevoluteBody", [8, 0, 3]),
            ("PrismaticBody", [11, 0, 3]),
        ):
            _data(connection.send_command("objects.create", {
                "object_type": "Cube", "prim_path": f"{ROOT}/{name}", "position": position,
                "size": 0.5, "physics_enabled": False,
            }))

        evidence["mesh_body"] = _readback(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/MeshCollider", "body_type": "static", "collider_enabled": True,
            "approximation": "convex_hull",
        }))
        evidence["mass_body"] = _readback(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/RevoluteBody", "body_type": "dynamic", "collider_enabled": True,
            "mass_kg": 2.5,
        }))
        evidence["density_body"] = _readback(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/PrismaticBody", "body_type": "kinematic", "collider_enabled": True,
            "density_kg_m3": 850.0,
        }))
        _data(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/FixedAnchor", "body_type": "static", "collider_enabled": False,
        }))
        _data(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/FixedBody", "body_type": "dynamic", "collider_enabled": False, "mass_kg": 1.0,
        }))
        _readback(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/GroupCollider", "body_type": "dynamic", "collider_enabled": True, "mass_kg": 3.0,
        }))
        evidence["static_conversion"] = _readback(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/GroupCollider", "body_type": "static", "collider_enabled": True,
        }))
        assert evidence["static_conversion"]["mass_kg"] is None
        assert not evidence["static_conversion"]["has_rigid_body_api"]

        _data(connection.send_command("physics.create_collision_group", {
            "group_path": f"{ROOT}/GroupB", "collider_paths": [f"{ROOT}/MeshCollider"],
        }))
        evidence["collision_group"] = _readback(connection.send_command("physics.create_collision_group", {
            "group_path": f"{ROOT}/GroupA", "collider_paths": [f"{ROOT}/GroupCollider"],
            "filtered_group_paths": [f"{ROOT}/GroupB"], "invert_filtered_groups": True,
            "merge_group_name": "mcp_task_3_3",
        }))

        evidence["fixed_joint"] = _readback(connection.send_command("physics.create_joint", {
            "joint_path": f"{ROOT}/FixedJoint", "joint_type": "fixed",
            "body0": f"{ROOT}/FixedAnchor", "body1": f"{ROOT}/FixedBody",
        }))
        evidence["revolute_joint"] = _readback(connection.send_command("physics.create_joint", {
            "joint_path": f"{ROOT}/RevoluteJoint", "joint_type": "revolute",
            "body1": f"{ROOT}/RevoluteBody", "axis": "Z", "lower_limit": -45, "upper_limit": 45,
            "local_position1": [0, 0, 0], "local_rotation1": [1, 0, 0, 0],
        }))
        evidence["prismatic_joint"] = _readback(connection.send_command("physics.create_joint", {
            "joint_path": f"{ROOT}/PrismaticJoint", "joint_type": "prismatic",
            "body1": f"{ROOT}/PrismaticBody", "axis": "X", "lower_limit": -0.25, "upper_limit": 0.25,
        }))

        invalid = connection.send_command("physics.create_joint", {
            "joint_path": f"{ROOT}/InvalidJoint", "joint_type": "prismatic",
            "body1": f"{ROOT}/PrismaticBody", "axis": "X", "lower_limit": 1,
        })
        assert invalid["status"] == "error" and invalid["code"] == "INVALID_PHYSICS_JOINT", invalid
        assert connection.send_command("scene.get_prim_info", {"prim_path": f"{ROOT}/InvalidJoint"})["status"] == "error"

        rollback_attempt = connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/GroupCollider", "body_type": "dynamic", "collider_enabled": True,
            "approximation": "convex_hull",
        })
        assert rollback_attempt["status"] == "error", rollback_attempt
        rollback_readback = _data(connection.send_command("physics.get_body", {
            "prim_path": f"{ROOT}/GroupCollider",
        }))
        assert rollback_readback["body_type"] == "static" and not rollback_readback["has_rigid_body_api"], rollback_readback
        evidence["rollback"] = {
            "attempt_code": rollback_attempt["code"],
            "restored_body_type": rollback_readback["body_type"],
            "restored_has_rigid_body_api": rollback_readback["has_rigid_body_api"],
            "collider_preserved": rollback_readback["collider_enabled"],
        }

        stepped = _data(connection.send_command("simulation.step", {
            "num_steps": 120, "observe_prims": [f"{ROOT}/FixedAnchor", f"{ROOT}/FixedBody"],
        }))
        observations = stepped.get("observations", {})
        evidence["step"] = {"num_steps": stepped.get("num_steps", 120), "observations": observations}
        fixed_body = _data(connection.send_command("scene.get_prim_info", {"prim_path": f"{ROOT}/FixedBody"}))
        position = fixed_body.get("position") or fixed_body.get("translation") or fixed_body.get("transform", {}).get("position")
        evidence["fixed_body_position_after_120_steps"] = position
        if position is not None:
            assert abs(float(position[2]) - 3.0) < 0.1, position

        assert evidence["mesh_body"]["approximation"] == "convex_hull"
        assert evidence["mass_body"]["mass_kg"] == 2.5
        assert evidence["density_body"]["density_kg_m3"] == 850.0
        assert evidence["collision_group"]["filtered_group_paths"] == [f"{ROOT}/GroupB"]
        assert evidence["revolute_joint"]["units"]["limit"] == "degrees"
        assert evidence["prismatic_joint"]["units"]["limit"] == "m"
        assert evidence["revolute_joint"]["local_rotation1"] == [1.0, 0.0, 0.0, 0.0]
        _data(connection.send_command("simulation.stop"))
        evidence["collider_disabled"] = _readback(connection.send_command("physics.configure_body", {
            "prim_path": f"{ROOT}/MeshCollider", "body_type": "static", "collider_enabled": False,
        }))
        assert not evidence["collider_disabled"]["collider_enabled"]
        assert evidence["collider_disabled"]["approximation"] is None
        print(json.dumps({"status": "success", "scratch_root": ROOT, "evidence": evidence}, indent=2))
        return 0
    finally:
        connection.send_command("simulation.stop")
        deleted = connection.send_command("objects.delete", {"prim_path": ROOT})
        assert deleted["status"] == "success", deleted
        survivor = connection.send_command("scene.get_prim_info", {"prim_path": ROOT})
        assert survivor["status"] == "error", survivor
        if remove_generated_ground_plane:
            generated_ground_plane = connection.send_command("scene.get_prim_info", {"prim_path": GROUND_PLANE})
            if generated_ground_plane["status"] == "success":
                deleted_ground_plane = connection.send_command("objects.delete", {"prim_path": GROUND_PLANE})
                assert deleted_ground_plane["status"] == "success", deleted_ground_plane
            ground_plane_survivor = connection.send_command("scene.get_prim_info", {"prim_path": GROUND_PLANE})
            assert ground_plane_survivor["status"] == "error", ground_plane_survivor


if __name__ == "__main__":
    raise SystemExit(main())
