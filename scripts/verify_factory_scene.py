"""Inspect the live Isaac Sim factory scene without modifying it."""

import json
from pathlib import Path

import omni.usd
from pxr import Sdf, Usd

ROOT = "/World/Factory"
EXPORT_PATH = str(Path(__file__).resolve().parents[1] / "test_outputs" / "factory_scene.usda")


def _children(stage, path, prefix):
    parent = stage.GetPrimAtPath(path)
    return [child for child in parent.GetChildren() if child.GetName().startswith(prefix)] if parent.IsValid() else []


def _check_inventory(stage, missing, label, strict_world_children=False):
    factory = stage.GetPrimAtPath(ROOT)
    world = stage.GetPrimAtPath("/World")
    if not factory.IsValid():
        missing.append(label + " /World/Factory")
    if not world.IsValid():
        missing.append(label + " /World")
    elif strict_world_children and [child.GetName() for child in world.GetChildren()] != ["Factory"]:
        missing.append(label + " World inventory must contain only Factory")


def _check_factory(stage, missing, label):
    workstations = _children(stage, ROOT + "/Workstations", "Workstation_")
    agvs = _children(stage, ROOT + "/AGVs", "AGV_")
    humans = _children(stage, ROOT + "/Humans", "Human_")
    row_counts = [
        len([item for item in workstations if item.GetName().endswith("_Row{}".format(row))]) for row in range(1, 5)
    ]
    if len(workstations) != 10:
        missing.append(label + " exactly 10 workstation roots (found {})".format(len(workstations)))
    if row_counts != [3, 2, 3, 2]:
        missing.append(label + " workstation rows must be 3-2-3-2 (found {})".format(row_counts))
    if len(agvs) != 3:
        missing.append(label + " exactly 3 AGV roots (found {})".format(len(agvs)))
    floor = stage.GetPrimAtPath(ROOT + "/Floor")
    floor_scale = floor.GetAttribute("xformOp:scale").Get() if floor.IsValid() else None
    if floor_scale is None or any(
        abs(actual - expected) > 1e-5 for actual, expected in zip(floor_scale, (32.0, 32.0, 0.2))
    ):
        missing.append(label + " 32m x 32m floor")
    for station in workstations:
        path = str(station.GetPath())
        if not stage.GetPrimAtPath(path + "/Zone").IsValid():
            missing.append(label + " " + path + " floor-plan zone")
        if not stage.GetPrimAtPath(path + "/WorkSurface").IsValid():
            missing.append(label + " " + path + " work surface")
        if not any(child.GetName().startswith("Fixture_") for child in station.GetChildren()):
            missing.append(label + " " + path + " equipment fixture")
        arm_path = path + "/InteractiveRobotArm"
        arm = stage.GetPrimAtPath(arm_path)
        if not arm.IsValid():
            missing.append(label + " " + path + " interactive robot arm")
        else:
            if arm.GetAttribute("factory:interactive").Get() is not True:
                missing.append(label + " " + arm_path + " interactive metadata")
            for joint_path in (arm_path + "/Joint1", arm_path + "/Joint1/Joint2"):
                if not stage.GetPrimAtPath(joint_path).IsValid():
                    missing.append(label + " robot joint " + joint_path)
    for vehicle in agvs:
        path = str(vehicle.GetPath())
        if not stage.GetPrimAtPath(path + "/Chassis").IsValid():
            missing.append(label + " " + path + " chassis")
        if len([child for child in vehicle.GetChildren() if child.GetName().startswith("Wheel_")]) != 4:
            missing.append(label + " " + path + " exactly four wheels")
        for attribute in ("factory:agvIndex", "factory:lane", "factory:route"):
            value = vehicle.GetAttribute(attribute).Get()
            if value is None or (attribute != "factory:agvIndex" and not str(value).strip()):
                missing.append(label + " " + path + " metadata " + attribute)
    if humans:
        missing.append(label + " placeholder humans must be removed before NVIDIA IRA spawning")
    aisle_paths = (
        ROOT + "/Aisles/UpperCrossAisle",
        ROOT + "/Aisles/MiddleCrossAisle",
        ROOT + "/Aisles/EastVerticalAisle",
    )
    aisle_present = True
    for path in aisle_paths:
        aisle = stage.GetPrimAtPath(path)
        direction = aisle.GetAttribute("factory:direction").Get() if aisle.IsValid() else None
        if not aisle.IsValid() or not direction or "two-way" not in str(direction).lower():
            aisle_present = False
            missing.append(label + " missing two-way aisle " + path)
    wall_paths = (
        ROOT + "/Walls/Top",
        ROOT + "/Walls/Left",
        ROOT + "/Walls/RightUpper",
        ROOT + "/Walls/BottomLeft",
    )
    for path in wall_paths:
        if not stage.GetPrimAtPath(path).IsValid():
            missing.append(label + " floor-plan wall " + path)
    for path, label_name in (
        (ROOT + "/Safety/PedestrianWalkwayWest", "west pedestrian walkway"),
        (ROOT + "/Lighting/FactoryDome", "factory lighting"),
        (ROOT + "/Cameras/FactoryOverview", "overview camera"),
    ):
        if not stage.GetPrimAtPath(path).IsValid():
            missing.append(label + " " + label_name)
    camera = stage.GetPrimAtPath(ROOT + "/Cameras/FactoryOverview")
    if camera.IsValid() and "OmniSensorAPI" not in camera.GetAppliedSchemas():
        missing.append(label + " overview camera OmniSensorAPI")
    robot_arm_count = len(
        [
            station
            for station in workstations
            if stage.GetPrimAtPath(str(station.GetPath()) + "/InteractiveRobotArm").IsValid()
        ]
    )
    return len(workstations), len(agvs), len(humans), robot_arm_count, bool(aisle_present), row_counts


def _external_dependencies(stage):
    found = []
    for prim in stage.TraverseAll():
        for field in ("references", "payload"):
            list_op = prim.GetMetadata(field)
            if list_op and hasattr(list_op, "GetAppliedItems"):
                for item in list_op.GetAppliedItems():
                    if getattr(item, "assetPath", ""):
                        found.append("{} on {}".format(field, prim.GetPath()))
        for attribute in prim.GetAttributes():
            if attribute.GetTypeName() in (Sdf.ValueTypeNames.Asset, Sdf.ValueTypeNames.AssetArray):
                value = attribute.Get()
                paths = value if isinstance(value, (list, tuple)) else (value,)
                if any(getattr(item, "path", "") for item in paths):
                    found.append("asset attribute {}".format(attribute.GetPath()))
    return found


def verify_factory_scene():
    live_missing = []
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        result = {
            "pass": False,
            "factory_path": ROOT,
            "workstation_count": 0,
            "agv_count": 0,
            "aisle_present": False,
            "missing_requirements": ["live USD stage"],
            "export_pass": False,
            "export_missing_requirements": ["live USD stage unavailable"],
        }
        print("FACTORY_VERIFY_RESULT " + json.dumps(result, sort_keys=True))
        return result
    _check_inventory(stage, live_missing, "live")
    workstation_count, agv_count, human_count, robot_arm_count, aisle_present, row_counts = _check_factory(
        stage, live_missing, "live"
    )
    export_missing = []
    try:
        export_stage = Usd.Stage.Open(EXPORT_PATH)
        if export_stage is None:
            export_missing.append("could not open exported stage")
        else:
            _check_inventory(export_stage, export_missing, "export", strict_world_children=True)
            _check_factory(export_stage, export_missing, "export")
            for dependency in _external_dependencies(export_stage):
                export_missing.append("external " + dependency)
    except Exception as exc:
        export_missing.append("export open failed: {}: {}".format(type(exc).__name__, exc))
    export_pass = not export_missing
    result = {
        "pass": not live_missing and export_pass,
        "factory_path": ROOT,
        "workstation_count": workstation_count,
        "robot_arm_count": robot_arm_count,
        "agv_count": agv_count,
        "human_count": human_count,
        "row_counts": row_counts,
        "aisle_present": aisle_present,
        "missing_requirements": live_missing,
        "export_pass": export_pass,
        "export_missing_requirements": export_missing,
    }
    print("FACTORY_VERIFY_RESULT " + json.dumps(result, sort_keys=True))
    return result


verify_factory_scene()
