"""Contracts for item 14 typed physics materials."""

from __future__ import annotations

import json

from isaac_sim_mcp_extension.handlers.materials import apply_material, create, get_binding, get_material

from isaac_mcp.tools.materials import register_tools


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    def __init__(self):
        self.calls = []

    def send_command(self, command, params=None):
        self.calls.append((command, params))
        return {"status": "success"}


class _Prim:
    def IsValid(self):
        return True


class _Stage:
    def TraverseAll(self):
        return []

    def GetPrimAtPath(self, _path):
        return _Prim()


class _Adapter:
    def __init__(self, timeline_state="stopped", material_type="physics"):
        self.timeline_state = timeline_state
        self.material_type = material_type
        self.calls = []

    def get_stage(self):
        return _Stage()

    def get_simulation_state(self):
        return {"timeline_state": self.timeline_state}

    def create_physics_material(self, prim_path, **params):
        self.calls.append(("create_physics", prim_path, params))

    def create_pbr_material(self, prim_path, **params):
        self.calls.append(("create_pbr", prim_path, params))

    def get_material(self, prim_path):
        self.calls.append(("get", prim_path))
        if self.material_type == "physics":
            return {
                "material_path": prim_path,
                "material_type": "physics",
                "static_friction": 0.8,
                "dynamic_friction": 0.6,
                "restitution": 0.25,
                "units": {"friction": "dimensionless", "restitution": "dimensionless"},
            }
        return {"material_path": prim_path, "material_type": "pbr"}

    def apply_material(self, material_path, target_prim_path, material_purpose="auto"):
        self.calls.append(("apply", material_path, target_prim_path, material_purpose))
        return {
            "material_path": material_path,
            "target_prim_path": target_prim_path,
            "material_purpose": "physics" if self.material_type == "physics" else "visual",
        }

    def get_material_binding(self, target_prim_path, material_purpose):
        self.calls.append(("binding", target_prim_path, material_purpose))
        return {
            "target_prim_path": target_prim_path,
            "material_path": "/World/Materials/Test",
            "material_purpose": material_purpose,
        }


def test_named_tools_expose_physics_fields_and_queries():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)
    assert {"create_material", "apply_material", "get_material", "get_material_binding"} == set(mcp.tools)

    result = json.loads(
        mcp.tools["create_material"]("physics", "/World/Materials/Test", None, 0.5, 0.0, 0.8, 0.6, 0.25)
    )
    assert result["status"] == "success"
    assert connection.calls[-1] == (
        "materials.create",
        {
            "material_type": "physics",
            "prim_path": "/World/Materials/Test",
            "roughness": 0.5,
            "metallic": 0.0,
            "static_friction": 0.8,
            "dynamic_friction": 0.6,
            "restitution": 0.25,
        },
    )
    mcp.tools["get_material"]("/World/Materials/Test")
    mcp.tools["get_material_binding"]("/World/Box", "physics")
    assert connection.calls[-2:] == [
        ("materials.get", {"material_path": "/World/Materials/Test"}),
        ("materials.get_binding", {"target_prim_path": "/World/Box", "material_purpose": "physics"}),
    ]


def test_physics_material_validation_and_readback():
    adapter = _Adapter()
    result = create(
        adapter,
        material_type="physics",
        prim_path="/World/Materials/Test",
        static_friction=0.8,
        dynamic_friction=0.6,
        restitution=0.25,
    )
    assert result["status"] == "success"
    assert result["readback"]["static_friction"] == 0.8
    assert adapter.calls[0] == (
        "create_physics",
        "/World/Materials/Test",
        {"static_friction": 0.8, "dynamic_friction": 0.6, "restitution": 0.25},
    )
    assert create(adapter, material_type="physics", static_friction=-1)["code"] == "INVALID_MATERIAL"
    assert (
        create(adapter, material_type="physics", static_friction=0.2, dynamic_friction=0.3)["code"]
        == "INVALID_MATERIAL"
    )
    assert create(adapter, material_type="physics", restitution=1.1)["code"] == "INVALID_MATERIAL"
    adapter.timeline_state = "playing"
    assert create(adapter, material_type="physics")["code"] == "TIMELINE_NOT_STOPPED"


def test_apply_auto_selects_physics_purpose_and_returns_binding_readback():
    adapter = _Adapter()
    result = apply_material(adapter, "/World/Materials/Test", "/World/Box", "auto")
    assert result["status"] == "success"
    assert result["readback"]["material_purpose"] == "physics"
    assert adapter.calls[-1] == ("apply", "/World/Materials/Test", "/World/Box", "physics")
    assert get_material(adapter, "/World/Materials/Test")["status"] == "success"
    assert get_binding(adapter, "/World/Box", "physics")["status"] == "success"


def test_material_purpose_and_pbr_ranges_fail_closed():
    adapter = _Adapter(material_type="pbr")
    assert apply_material(adapter, "/World/M", "/World/B", "invalid")["code"] == "INVALID_MATERIAL_BINDING"
    assert create(adapter, material_type="pbr", color=[1, 0])["code"] == "INVALID_MATERIAL"
    assert create(adapter, material_type="pbr", color=[1, 0, 2])["code"] == "INVALID_MATERIAL"
    assert create(adapter, material_type="pbr", roughness=-0.1)["code"] == "INVALID_MATERIAL"
