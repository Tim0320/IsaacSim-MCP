"""Contracts for task 3.3 typed physics authoring."""

from __future__ import annotations

from isaac_sim_mcp_extension.handlers.physics import (
    configure_body,
    create_collision_group,
    create_joint,
    get_body,
    get_collision_group,
    get_joint,
)


class _Adapter:
    def __init__(self, timeline_state="stopped"):
        self.timeline_state = timeline_state
        self.calls = []

    def get_simulation_state(self):
        return {"timeline_state": self.timeline_state}

    def configure_physics_body(self, **kwargs):
        self.calls.append(("body", kwargs))
        return {"prim_path": kwargs["prim_path"], "body_type": kwargs["body_type"], "units": {"mass": "kg"}}

    def get_physics_body(self, prim_path):
        self.calls.append(("get_body", prim_path))
        return {"prim_path": prim_path, "body_type": "dynamic"}

    def create_collision_group(self, **kwargs):
        self.calls.append(("group", kwargs))
        return {"group_path": kwargs["group_path"], "collider_paths": kwargs["collider_paths"]}

    def get_collision_group(self, group_path):
        self.calls.append(("get_group", group_path))
        return {"group_path": group_path, "collider_paths": []}

    def create_physics_joint(self, **kwargs):
        self.calls.append(("joint", kwargs))
        return {"joint_path": kwargs["joint_path"], "joint_type": kwargs["joint_type"]}

    def get_physics_joint(self, joint_path):
        self.calls.append(("get_joint", joint_path))
        return {"joint_path": joint_path, "joint_type": "fixed"}


def test_configure_body_validates_and_forwards_typed_values():
    adapter = _Adapter()
    result = configure_body(
        adapter,
        prim_path="/World/Box",
        body_type="kinematic",
        collider_enabled=True,
        approximation="convex_hull",
        mass_kg=2.5,
    )
    assert result["status"] == "success"
    assert result["readback"]["body_type"] == "kinematic"
    assert adapter.calls == [
        (
            "body",
            {
                "prim_path": "/World/Box",
                "body_type": "kinematic",
                "collider_enabled": True,
                "approximation": "convex_hull",
                "mass_kg": 2.5,
                "density_kg_m3": None,
            },
        )
    ]


def test_configure_body_rejects_unsafe_or_ambiguous_inputs():
    adapter = _Adapter("playing")
    assert configure_body(adapter, "/World/Box")["code"] == "TIMELINE_NOT_STOPPED"
    adapter.timeline_state = "stopped"
    assert configure_body(adapter, "/World/Box", mass_kg=1, density_kg_m3=2)["code"] == "INVALID_PHYSICS_BODY"
    assert configure_body(adapter, "/World/Box", body_type="static", mass_kg=1)["code"] == "INVALID_PHYSICS_BODY"
    assert configure_body(adapter, "/World/Box", approximation="triangle_soup")["code"] == "INVALID_PHYSICS_BODY"


def test_collision_group_requires_paths_and_forwards_readback():
    adapter = _Adapter()
    result = create_collision_group(adapter, "/World/Groups/G", ["/World/A"], ["/World/Groups/H"], True, "merged")
    assert result["status"] == "success"
    assert result["readback"]["collider_paths"] == ["/World/A"]
    assert create_collision_group(adapter, "/World/Groups/Empty", [])["code"] == "INVALID_COLLISION_GROUP"
    assert get_collision_group(adapter, "/World/Groups/G")["status"] == "success"


def test_joint_validation_covers_types_axes_limits_and_frames():
    adapter = _Adapter()
    result = create_joint(
        adapter,
        "/World/Joints/J",
        "revolute",
        "/World/B",
        body0="/World/A",
        axis="Z",
        lower_limit=-45,
        upper_limit=45,
        local_position0=[0, 0, 1],
        local_rotation0=[1, 0, 0, 0],
    )
    assert result["status"] == "success"
    kwargs = adapter.calls[-1][1]
    assert kwargs["axis"] == "Z"
    assert kwargs["lower_limit"] == -45.0
    assert create_joint(adapter, "/World/J", "fixed", "/World/B", axis="X")["code"] == "INVALID_PHYSICS_JOINT"
    assert create_joint(adapter, "/World/J", "revolute", "/World/B", axis="Q")["code"] == "INVALID_PHYSICS_JOINT"
    assert (
        create_joint(adapter, "/World/J", "prismatic", "/World/B", axis="X", lower_limit=1)["code"]
        == "INVALID_PHYSICS_JOINT"
    )
    assert (
        create_joint(adapter, "/World/J", "prismatic", "/World/B", axis="X", lower_limit=2, upper_limit=1)["code"]
        == "INVALID_PHYSICS_JOINT"
    )
    assert get_body(adapter, "/World/B")["status"] == "success"
    assert get_joint(adapter, "/World/J")["status"] == "success"
