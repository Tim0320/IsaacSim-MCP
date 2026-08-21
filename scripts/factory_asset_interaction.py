"""Persistent MCP interaction helpers for the real factory assets."""

import json

import omni.timeline
import omni.usd
from isaac_sim_mcp_extension.adapters.transforms import set_transform
from pxr import Gf, PhysxSchema, Sdf, UsdGeom

ROOT = "/World/Factory"


def _stage():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No live USD stage")
    return stage


def _require(path):
    prim = _stage().GetPrimAtPath(path)
    if not prim.IsValid():
        raise ValueError("Factory asset not found: {}".format(path))
    return prim


def _set_string(prim, name, value):
    attr = prim.GetAttribute(name)
    if not attr.IsValid():
        attr = prim.CreateAttribute(name, Sdf.ValueTypeNames.String, custom=True)
    attr.Set(str(value))


def _emit(action, payload):
    result = {"success": True, "action": action, **payload}
    print("FACTORY_ASSET_INTERACTION_RESULT " + json.dumps(result, sort_keys=True))
    return result


def annotate_factory_assets():
    """Link every workstation and mobile asset to its MCP control path."""
    for index in range(1, 11):
        row = 1 if index <= 3 else 2 if index <= 5 else 3 if index <= 8 else 4
        station = _require(ROOT + "/Workstations/Workstation_{:02d}_Row{}".format(index, row))
        arm_path = ROOT + "/Robots/WorkstationArm_{:02d}".format(index)
        _set_string(station, "factory:robotAssetPath", arm_path)
        _set_string(station, "factory:robotControlTool", "set_joint_positions")
    for index, lane in enumerate(("UpperCrossAisle", "MiddleCrossAisle", "EastVerticalAisle"), 1):
        agv = _require(ROOT + "/AGVs/AGV_{:02d}".format(index))
        _set_string(agv, "factory:lane", lane)
        _set_string(agv, "factory:control", "factory_asset_interaction.move_agv while paused")
    dog = _require(ROOT + "/Inspection/Spot_01")
    _set_string(dog, "factory:purpose", "safety inspection quadruped")
    _set_string(dog, "factory:control", "compatible Spot locomotion policy or set_joint_positions")
    return _emit("annotate_factory_assets", {"workstations": 10, "agvs": 3, "quadrupeds": 1})


def set_conveyor_speed(conveyor_id, meters_per_second):
    """Apply local belt surface velocity without moving the conveyor frame."""
    conveyor_id = int(conveyor_id)
    speed = float(meters_per_second)
    if abs(speed) > 2.0:
        raise ValueError("Conveyor speed must be between -2.0 and 2.0 m/s")
    belt_path = ROOT + "/Conveyors/PackingConveyor_{:02d}/Belt".format(conveyor_id)
    belt = _require(belt_path)
    api = PhysxSchema.PhysxSurfaceVelocityAPI.Apply(belt)
    api.CreateSurfaceVelocityEnabledAttr().Set(abs(speed) > 1e-6)
    api.CreateSurfaceVelocityLocalSpaceAttr().Set(True)
    api.CreateSurfaceVelocityAttr().Set(Gf.Vec3f(speed, 0.0, 0.0))
    _set_string(belt, "factory:configuredSpeedMps", speed)
    return _emit(
        "set_conveyor_speed",
        {"conveyor": conveyor_id, "belt_path": belt_path, "speed_mps": speed, "enabled": abs(speed) > 1e-6},
    )


def stop_all_conveyors():
    return _emit("stop_all_conveyors", {"conveyors": [set_conveyor_speed(index, 0.0) for index in (1, 2)]})


def move_agv(agv_id, position, heading_degrees=0.0):
    """Reposition an AGV only while the timeline is stopped or paused."""
    timeline = omni.timeline.get_timeline_interface()
    if timeline.is_playing():
        raise RuntimeError("Pause the timeline before repositioning an AGV")
    path = ROOT + "/AGVs/AGV_{:02d}".format(int(agv_id))
    prim = _require(path)
    x, y, z = (float(value) for value in position)
    set_transform(UsdGeom.Xformable(prim), position=(x, y, z), rotation=(0.0, 0.0, float(heading_degrees)))
    return _emit("move_agv", {"agv": path, "position": [x, y, z], "heading_degrees": float(heading_degrees)})


def list_factory_assets():
    groups = {}
    stage = _stage()
    for name in ("Robots", "AGVs", "Conveyors", "Storage", "Vegetation", "Inspection"):
        parent = stage.GetPrimAtPath(ROOT + "/" + name)
        groups[name.lower()] = [str(child.GetPath()) for child in parent.GetChildren()] if parent.IsValid() else []
    return _emit("list_factory_assets", groups)


annotate_factory_assets()
set_conveyor_speed(1, 0.25)
set_conveyor_speed(2, 0.25)
print("FACTORY_ASSET_INTERACTION_READY")
