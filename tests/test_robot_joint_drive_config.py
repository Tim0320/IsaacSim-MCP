"""Drive configuration contract tests for task 2.2."""

from __future__ import annotations

import json
import math
import sys
import types

import numpy as np
import pytest
from isaac_sim_mcp_extension.adapters.base import JointDriveConfigApplyError
from isaac_sim_mcp_extension.adapters.v6_runtime import RobotRuntime
from isaac_sim_mcp_extension.handlers.robots import set_joint_drive_config

from isaac_mcp.tools.robots import register_tools


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
        return {"status": "success", "data": {}}


class _Adapter:
    def __init__(self, *, timeline_state="stopped", engine="physx"):
        self.timeline_state = timeline_state
        self.engine = engine
        self.calls = []

    def get_simulation_state(self):
        return {"timeline_state": self.timeline_state, "engine": self.engine}

    def get_robot_joint_info(self, _prim_path):
        return {"joint_names": ["shoulder", "finger"], "num_dof": 2}

    def set_joint_drive_config(self, prim_path, config, joint_indices=None):
        self.calls.append((prim_path, dict(config), list(joint_indices or [])))

    def get_joint_drive_config(self, prim_path):
        return {
            "prim_path": prim_path,
            "joint_count": 2,
            "joints": [
                {
                    "index": 0,
                    "name": "shoulder",
                    "type": "revolute",
                    "stiffness": 100.0,
                    "damping": 10.0,
                    "max_force": 80.0,
                    "max_velocity": 2.0,
                    "drive_type": "force",
                },
                {
                    "index": 1,
                    "name": "finger",
                    "type": "prismatic",
                    "stiffness": 200.0,
                    "damping": 20.0,
                    "max_force": 40.0,
                    "max_velocity": 0.2,
                    "drive_type": "acceleration",
                },
            ],
        }


def test_named_tool_forwards_zero_values_and_selector():
    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    result = json.loads(
        mcp.tools["set_joint_drive_config"](
            prim_path="/World/Robot",
            stiffness=0.0,
            damping=12.0,
            max_force=80.0,
            max_velocity=2.0,
            drive_type="force",
            joint_names=["shoulder"],
            joint_indices=None,
        )
    )

    assert result["status"] == "success"
    assert connection.calls == [
        (
            "robots.set_joint_drive_config",
            {
                "prim_path": "/World/Robot",
                "stiffness": 0.0,
                "damping": 12.0,
                "max_force": 80.0,
                "max_velocity": 2.0,
                "drive_type": "force",
                "joint_names": ["shoulder"],
            },
        )
    ]


def test_drive_config_validates_then_applies_and_returns_selected_readback():
    adapter = _Adapter()

    result = set_joint_drive_config(
        adapter,
        prim_path="/World/Robot",
        joint_names=["finger"],
        stiffness=250.0,
        damping=25.0,
        max_force=45.0,
        max_velocity=0.25,
        drive_type="acceleration",
    )

    assert result["status"] == "success"
    assert result["applied"] is True
    assert result["joint_indices"] == [1]
    assert result["joint_names"] == ["finger"]
    assert adapter.calls == [
        (
            "/World/Robot",
            {
                "stiffness": 250.0,
                "damping": 25.0,
                "max_force": 45.0,
                "max_velocity": 0.25,
                "drive_type": "acceleration",
            },
            [1],
        )
    ]
    assert [joint["name"] for joint in result["readback"]["joints"]] == ["finger"]


def test_invalid_drive_config_is_atomic_and_never_calls_adapter():
    cases = [
        ({}, "EMPTY_JOINT_DRIVE_CONFIG"),
        ({"stiffness": -1.0}, "INVALID_JOINT_DRIVE_VALUE"),
        ({"damping": True}, "INVALID_JOINT_DRIVE_VALUE"),
        ({"max_force": float("nan")}, "INVALID_JOINT_DRIVE_VALUE"),
        ({"max_velocity": -0.1}, "INVALID_JOINT_DRIVE_VALUE"),
        ({"max_velocity": 3.5e38}, "INVALID_JOINT_DRIVE_VALUE"),
        ({"drive_type": "torque"}, "INVALID_JOINT_DRIVE_TYPE"),
        (
            {"stiffness": 1.0, "joint_names": ["shoulder"], "joint_indices": [0]},
            "JOINT_SELECTOR_CONFLICT",
        ),
        ({"stiffness": 1.0, "joint_names": ["missing"]}, "JOINT_NOT_FOUND"),
    ]
    for params, expected_code in cases:
        adapter = _Adapter()
        result = set_joint_drive_config(adapter, prim_path="/World/Robot", **params)
        assert result["status"] == "error"
        assert result["code"] == expected_code
        assert result["applied"] is False
        assert adapter.calls == []


def test_drive_config_requires_stopped_timeline_before_apply():
    adapter = _Adapter(timeline_state="playing")

    result = set_joint_drive_config(adapter, prim_path="/World/Robot", stiffness=10.0)

    assert result["status"] == "error"
    assert result["code"] == "JOINT_DRIVE_TIMELINE_ACTIVE"
    assert result["applied"] is False
    assert adapter.calls == []


def test_newton_rejects_physx_only_max_velocity_before_apply():
    adapter = _Adapter(engine="newton")

    result = set_joint_drive_config(adapter, prim_path="/World/Robot", max_velocity=1.0)

    assert result["status"] == "unsupported"
    assert result["code"] == "JOINT_DRIVE_FIELD_UNSUPPORTED"
    assert result["applied"] is False
    assert adapter.calls == []


def test_apply_failure_reports_rollback_state():
    class _Failure(_Adapter):
        def set_joint_drive_config(self, *_args, **_kwargs):
            raise RuntimeError("write failed; rollback succeeded")

    result = set_joint_drive_config(_Failure(), prim_path="/World/Robot", damping=10.0)

    assert result["status"] == "error"
    assert result["code"] == "JOINT_DRIVE_CONFIG_FAILED"
    assert result["applied"] is False
    assert "rollback succeeded" in result["message"]


def test_rollback_failure_is_partial_with_unknown_applied_state():
    class _RollbackFailure(_Adapter):
        def set_joint_drive_config(self, *_args, **_kwargs):
            raise JointDriveConfigApplyError("rollback failed", rollback_succeeded=False)

    result = set_joint_drive_config(_RollbackFailure(), prim_path="/World/Robot", damping=10.0)

    assert result["status"] == "partial"
    assert result["code"] == "JOINT_DRIVE_ROLLBACK_FAILED"
    assert result["applied"] is None
    assert result["rollback_succeeded"] is False


def test_successful_apply_with_failed_readback_is_partial_and_applied():
    class _ReadbackFailure(_Adapter):
        def get_joint_drive_config(self, _prim_path):
            raise RuntimeError("readback unavailable")

    adapter = _ReadbackFailure()
    result = set_joint_drive_config(adapter, prim_path="/World/Robot", damping=10.0, joint_indices=[0])

    assert result["status"] == "partial"
    assert result["code"] == "JOINT_DRIVE_READBACK_FAILED"
    assert result["applied"] is True
    assert adapter.calls == [("/World/Robot", {"damping": 10.0}, [0])]


class _DriveArticulation:
    valid = True
    dof_names = ["shoulder", "finger"]
    dof_types = ["DofType.Rotation", "DofType.Translation"]
    dof_paths = [["/World/Robot/joint0", "/World/Robot/joint1"]]

    def __init__(self, *, fail_gains=False):
        self.fail_gains = fail_gains
        self.calls = []

    def get_dof_gains(self, **_kwargs):
        return np.asarray([[100.0, 200.0]], dtype=np.float32), np.asarray([[10.0, 20.0]], dtype=np.float32)

    def get_dof_max_efforts(self, **_kwargs):
        return np.asarray([[80.0, 40.0]], dtype=np.float32)

    def get_dof_max_velocities(self, **_kwargs):
        return np.asarray([[2.0, 0.2]], dtype=np.float32)

    def get_dof_drive_types(self, **_kwargs):
        return [["force", "acceleration"]]

    def set_dof_drive_types(self, values, **_kwargs):
        self.calls.append(("drive_type", values))

    def set_dof_gains(self, stiffnesses=None, dampings=None, **_kwargs):
        self.calls.append(("gains", stiffnesses, dampings))
        if self.fail_gains:
            self.fail_gains = False
            raise RuntimeError("gain write failed")

    def set_dof_max_efforts(self, values, **_kwargs):
        self.calls.append(("max_force", values))

    def set_dof_max_velocities(self, values, **_kwargs):
        self.calls.append(("max_velocity", values))


class _DriveAdapter(RobotRuntime):
    def __init__(self, art, *, engine="physx", stage=None):
        self.art = art
        self.engine = engine
        self.stage = stage

    @property
    def _engine(self):
        return self.engine

    def _ensure_physics_world(self):
        return None

    def _drive_config_articulation(self, _prim_path):
        return self.art

    def get_simulation_state(self):
        return {"timeline_state": "stopped", "engine": self.engine}

    def require_backend_capability(self, _feature):
        return {"state": "supported"}

    def get_stage(self):
        return self.stage


class _Attr:
    def __init__(self, value, *, fail_once=False):
        self.value = value
        self.authored = True
        self.fail_once = fail_once
        self.history = []

    def HasAuthoredValueOpinion(self):
        return self.authored

    def Get(self):
        return self.value

    def Set(self, value):
        self.history.append(("set", value))
        if self.fail_once:
            self.fail_once = False
            return False
        self.value = value
        self.authored = True
        return True

    def Clear(self):
        self.history.append(("clear", None))
        self.value = None
        self.authored = False
        return True

    def GetPath(self):
        return "/fake.attribute"


class _Drive:
    def __init__(
        self,
        *,
        drive_type="force",
        stiffness=1.0,
        damping=2.0,
        max_force=3.0,
        fail_stiffness=False,
    ):
        self.type = _Attr(drive_type)
        self.stiffness = _Attr(stiffness, fail_once=fail_stiffness)
        self.damping = _Attr(damping)
        self.max_force = _Attr(max_force)

    def __bool__(self):
        return True

    def GetTypeAttr(self):
        return self.type

    def GetStiffnessAttr(self):
        return self.stiffness

    def GetDampingAttr(self):
        return self.damping

    def GetMaxForceAttr(self):
        return self.max_force


class _PhysxJoint:
    def __init__(self, max_velocity=4.0):
        self.max_velocity = _Attr(max_velocity)

    def __bool__(self):
        return True

    def GetMaxJointVelocityAttr(self):
        return self.max_velocity


class _RevoluteJointSchema:
    pass


class _PrismaticJointSchema:
    pass


class _Prim:
    def __init__(self, *, kind="revolute", fail_stiffness=False):
        self.kind = kind
        self.drive = _Drive(fail_stiffness=fail_stiffness)
        self.physx = _PhysxJoint()
        self.requested_drive_instances = []

    def IsValid(self):
        return True

    def IsA(self, schema):
        return (self.kind == "revolute" and schema is _RevoluteJointSchema) or (
            self.kind == "prismatic" and schema is _PrismaticJointSchema
        )

    def HasAPI(self, _schema):
        return True

    def RemoveAPI(self, *_args):
        return True


class _Stage:
    def __init__(self, prims):
        self.prims = prims

    def GetPrimAtPath(self, path):
        return self.prims[path]


class _DriveAPI:
    @staticmethod
    def Get(prim, axis):
        assert axis in {"angular", "linear"}
        prim.requested_drive_instances.append(axis)
        return prim.drive

    @staticmethod
    def Apply(prim, _axis):
        return prim.drive


class _PhysxJointAPI:
    def __new__(cls, prim):
        return prim.physx

    @staticmethod
    def Apply(prim):
        return prim.physx


def _install_drive_schema_stubs(monkeypatch):
    pxr = sys.modules["pxr"]
    monkeypatch.setattr(
        pxr,
        "UsdPhysics",
        types.SimpleNamespace(
            DriveAPI=_DriveAPI,
            RevoluteJoint=_RevoluteJointSchema,
            PrismaticJoint=_PrismaticJointSchema,
        ),
        raising=False,
    )
    monkeypatch.setattr(pxr, "PhysxSchema", types.SimpleNamespace(PhysxJointAPI=_PhysxJointAPI), raising=False)


def test_v6_drive_config_readback_has_typed_values_and_units():
    result = _DriveAdapter(_DriveArticulation()).get_joint_drive_config("/World/Robot")

    assert result["joint_count"] == 2
    assert result["joints"][0] == {
        "index": 0,
        "name": "shoulder",
        "type": "revolute",
        "stiffness": 100.0,
        "damping": 10.0,
        "max_force": 80.0,
        "max_velocity": 2.0,
        "drive_type": "force",
        "units": {
            "stiffness": "newton_meters_per_radian",
            "damping": "newton_meter_seconds_per_radian",
            "max_force": "newton_meters",
            "max_velocity": "radians_per_second",
        },
    }
    assert result["joints"][1]["units"]["max_velocity"] == "meters_per_second"


def test_v6_drive_readback_uses_explicit_usd_instances_when_tensor_dof_type_is_invalid(monkeypatch):
    _install_drive_schema_stubs(monkeypatch)

    class _InvalidTensorMetadata(_DriveArticulation):
        dof_types = ["DofType.Rotation", "DofType.Invalid"]

        def get_dof_gains(self, **_kwargs):
            raise RuntimeError("PhysicsDriveAPI, a non-empty instance name must be provided")

    art = _InvalidTensorMetadata()
    revolute = _Prim(kind="revolute")
    revolute.drive = _Drive(
        drive_type="force",
        stiffness=100.0 * math.pi / 180.0,
        damping=10.0 * math.pi / 180.0,
        max_force=80.0,
    )
    revolute.physx = _PhysxJoint(2.0 * 180.0 / math.pi)
    prismatic = _Prim(kind="prismatic")
    prismatic.drive = _Drive(drive_type="acceleration", stiffness=200.0, damping=20.0, max_force=40.0)
    prismatic.physx = _PhysxJoint(0.2)
    adapter = _DriveAdapter(
        art,
        stage=_Stage(
            {
                art.dof_paths[0][0]: revolute,
                art.dof_paths[0][1]: prismatic,
            }
        ),
    )

    result = adapter.get_joint_drive_config("/World/Robot")

    assert [joint["name"] for joint in result["joints"]] == ["shoulder", "finger"]
    assert math.isclose(result["joints"][0]["stiffness"], 100.0)
    assert math.isclose(result["joints"][0]["max_velocity"], 2.0)
    assert result["joints"][1]["stiffness"] == 200.0
    assert result["joints"][1]["max_velocity"] == 0.2
    assert revolute.requested_drive_instances == ["angular"]
    assert prismatic.requested_drive_instances == ["linear"]


def test_v6_drive_config_applies_every_requested_field_to_subset(monkeypatch):
    _install_drive_schema_stubs(monkeypatch)
    art = _DriveArticulation()
    prim = _Prim()
    adapter = _DriveAdapter(art, stage=_Stage({art.dof_paths[0][0]: prim}))

    adapter.set_joint_drive_config(
        "/World/Robot",
        {
            "stiffness": 300.0,
            "damping": 30.0,
            "max_force": 90.0,
            "max_velocity": 3.0,
            "drive_type": "acceleration",
        },
        [0],
    )

    assert prim.drive.type.value == "acceleration"
    assert math.isclose(prim.drive.stiffness.value, 300.0 * math.pi / 180.0)
    assert math.isclose(prim.drive.damping.value, 30.0 * math.pi / 180.0)
    assert prim.drive.max_force.value == 90.0
    assert math.isclose(prim.physx.max_velocity.value, 3.0 * 180.0 / math.pi)


def test_v6_drive_config_rolls_back_earlier_fields_when_apply_fails(monkeypatch):
    _install_drive_schema_stubs(monkeypatch)
    art = _DriveArticulation()
    prim = _Prim(fail_stiffness=True)
    adapter = _DriveAdapter(art, stage=_Stage({art.dof_paths[0][0]: prim}))

    with pytest.raises(RuntimeError, match="rollback succeeded"):
        adapter.set_joint_drive_config(
            "/World/Robot",
            {"drive_type": "acceleration", "stiffness": 300.0},
            [0],
        )

    assert prim.drive.type.value == "force"
    assert prim.drive.stiffness.value == 1.0
    assert prim.drive.type.history == [("set", "acceleration"), ("set", "force")]
