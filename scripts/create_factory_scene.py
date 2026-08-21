"""Create the 32m x 32m factory layout from the supplied floor-plan image."""

import json
import os
from pathlib import Path

import omni.physxcommands
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdUtils

ROOT = "/World/Factory"
EXPORT_PATH = str(Path(__file__).resolve().parents[1] / "test_outputs" / "factory_scene.usda")


def _meta(prim, name, value):
    typ = (
        Sdf.ValueTypeNames.Bool
        if isinstance(value, bool)
        else Sdf.ValueTypeNames.Int
        if isinstance(value, int)
        else Sdf.ValueTypeNames.Double
        if isinstance(value, float)
        else Sdf.ValueTypeNames.String
    )
    prim.CreateAttribute(name, typ, custom=True).Set(value)


def _xform(stage, path, position=(0, 0, 0)):
    prim = UsdGeom.Xform.Define(stage, path).GetPrim()
    UsdGeom.Xformable(prim).AddTranslateOp().Set(Gf.Vec3d(*position))
    return prim


def _box(stage, path, position, dimensions, color, collision=True):
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    transform = UsdGeom.Xformable(cube)
    transform.AddTranslateOp().Set(Gf.Vec3d(*position))
    transform.AddScaleOp().Set(Gf.Vec3f(*dimensions))
    if collision:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    return cube.GetPrim()


def _cylinder(stage, path, position, radius, height, color, rotation=(90, 0, 0)):
    cylinder = UsdGeom.Cylinder.Define(stage, path)
    cylinder.CreateRadiusAttr(radius)
    cylinder.CreateHeightAttr(height)
    cylinder.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    transform = UsdGeom.Xformable(cylinder)
    transform.AddTranslateOp().Set(Gf.Vec3d(*position))
    transform.AddRotateXYZOp().Set(Gf.Vec3f(*rotation))
    UsdPhysics.CollisionAPI.Apply(cylinder.GetPrim())
    return cylinder.GetPrim()


def _sphere(stage, path, position, radius, color, collision=True):
    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr(radius)
    sphere.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    UsdGeom.Xformable(sphere).AddTranslateOp().Set(Gf.Vec3d(*position))
    if collision:
        UsdPhysics.CollisionAPI.Apply(sphere.GetPrim())
    return sphere.GetPrim()


def _robot_arm(stage, path, x_offset=0.0):
    root = _xform(stage, path, (x_offset, 0, 1.08))
    _meta(root, "factory:interactive", True)
    _meta(root, "factory:state", "home")
    _cylinder(stage, path + "/Base", (0, 0, 0.12), 0.26, 0.24, (0.92, 0.52, 0.12), (0, 0, 0))
    joint1 = _xform(stage, path + "/Joint1", (0, 0, 0.24))
    _meta(joint1, "factory:joint", "base")
    _box(stage, path + "/Joint1/LowerLink", (0, 0, 0.48), (0.18, 0.18, 0.96), (0.95, 0.58, 0.14))
    joint2 = _xform(stage, path + "/Joint1/Joint2", (0, 0, 0.96))
    _meta(joint2, "factory:joint", "elbow")
    _box(stage, path + "/Joint1/Joint2/UpperLink", (0.42, 0, 0), (0.84, 0.15, 0.15), (0.92, 0.45, 0.10))
    _box(stage, path + "/Joint1/Joint2/Tool", (0.88, 0, 0), (0.14, 0.34, 0.12), (0.18, 0.20, 0.22))
    return path


def _workstation(stage, number, x, y, width, depth, equipment, row):
    path = ROOT + "/Workstations/Workstation_{:02d}_Row{}".format(number, row)
    root = _xform(stage, path, (x, y, 0))
    _meta(root, "factory:stationIndex", number)
    _meta(root, "factory:row", row)
    _meta(root, "factory:equipment", equipment)
    _meta(root, "factory:zoneWidthMeters", float(width))
    _meta(root, "factory:zoneDepthMeters", float(depth))
    interaction_y = y - depth / 2 - 0.7 if row in (1, 2) else y + depth / 2 + 0.7
    _meta(root, "factory:interactionX", float(x))
    _meta(root, "factory:interactionY", float(interaction_y))
    _box(stage, path + "/Zone", (0, 0, 0.018), (width, depth, 0.025), (0.46, 0.48, 0.50), False)
    work_width = max(1.2, min(width - 0.6, 4.8))
    work_depth = max(1.2, min(depth - 0.6, 2.4))
    _box(stage, path + "/WorkSurface", (0, 0, 0.95), (work_width, work_depth, 0.12), (0.30, 0.33, 0.36))
    leg_x = max(0.35, work_width / 2 - 0.25)
    leg_y = max(0.35, work_depth / 2 - 0.25)
    for leg_number, (lx, ly) in enumerate(((-leg_x, -leg_y), (-leg_x, leg_y), (leg_x, -leg_y), (leg_x, leg_y)), 1):
        _box(stage, path + "/Leg_{:02d}".format(leg_number), (lx, ly, 0.45), (0.16, 0.16, 0.9), (0.16, 0.18, 0.20))
    fixture = path + "/Fixture_" + equipment
    if equipment == "RobotArm":
        _cylinder(stage, fixture + "/Base", (0, 0, 1.16), 0.36, 0.3, (0.92, 0.52, 0.12), (0, 0, 0))
        _box(stage, fixture + "/Arm", (0.55, 0, 1.75), (1.15, 0.25, 0.22), (0.95, 0.58, 0.14))
    elif equipment == "CNC":
        _box(stage, fixture + "/Enclosure", (0, 0, 1.65), (1.8, 1.35, 1.35), (0.20, 0.48, 0.72))
    elif equipment == "Inspection":
        _box(stage, fixture + "/Frame", (0, 0, 1.78), (1.5, 1.1, 1.35), (0.70, 0.70, 0.72))
        _cylinder(stage, fixture + "/Camera", (0, 0, 2.55), 0.16, 0.35, (0.12, 0.14, 0.16), (0, 0, 0))
    elif equipment == "Packing":
        _box(stage, fixture + "/Conveyor", (0, 0, 1.2), (2.7, 0.72, 0.25), (0.14, 0.45, 0.30))
        _box(stage, fixture + "/Carton", (0.55, 0, 1.55), (0.75, 0.65, 0.5), (0.68, 0.45, 0.22))
    else:
        _box(stage, fixture + "/ToolBoard", (0, 0.75, 1.75), (2.4, 0.12, 1.55), (0.86, 0.72, 0.18))
        _cylinder(stage, fixture + "/Tool", (-0.65, 0, 1.35), 0.15, 0.8, (0.80, 0.16, 0.12), (0, 90, 0))
    _robot_arm(stage, path + "/InteractiveRobotArm", -min(work_width * 0.22, 0.75))
    return path


def _agv(stage, number, x, y, lane, route):
    path = ROOT + "/AGVs/AGV_{:02d}".format(number)
    root = _xform(stage, path, (x, y, 0))
    _meta(root, "factory:agvIndex", number)
    _meta(root, "factory:lane", lane)
    _meta(root, "factory:route", route)
    _meta(root, "factory:static", True)
    _box(stage, path + "/Chassis", (0, 0, 0.45), (2.2, 1.1, 0.38), (0.16, 0.36, 0.70))
    _box(stage, path + "/CargoDeck", (0, 0, 0.8), (1.7, 0.88, 0.18), (0.38, 0.48, 0.56))
    _box(stage, path + "/StatusLight", (0.7, 0, 1.02), (0.18, 0.28, 0.15), (0.12, 0.90, 0.28), False)
    for index, (wx, wy) in enumerate(((-0.72, -0.58), (-0.72, 0.58), (0.72, -0.58), (0.72, 0.58)), 1):
        _cylinder(stage, path + "/Wheel_{:02d}".format(index), (wx, wy, 0.27), 0.3, 0.2, (0.06, 0.07, 0.08))
    return path


def _export_factory_only(stage):
    """Export a self-contained layer with exactly /World/Factory below World."""
    flattened = UsdUtils.FlattenLayerStack(stage)
    export_stage = Usd.Stage.CreateInMemory()
    export_layer = export_stage.GetRootLayer()
    export_stage.DefinePrim("/World", "Xform")
    if not Sdf.CopySpec(flattened, Sdf.Path(ROOT), export_layer, Sdf.Path(ROOT)):
        raise RuntimeError("Sdf.CopySpec could not copy /World/Factory")
    return bool(export_layer.Export(EXPORT_PATH))


def build_factory_scene():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No live USD stage is available yet")
    if stage.GetPrimAtPath(ROOT).IsValid():
        stage.RemovePrim(Sdf.Path(ROOT))  # Scope-limited idempotent replacement.
    stage.DefinePrim("/World", "Xform")
    root = _xform(stage, ROOT)
    _meta(root, "factory:description", "32m x 32m factory recreated from supplied floor plan")
    _meta(root, "factory:floorLengthMeters", 32.0)
    _meta(root, "factory:floorWidthMeters", 32.0)
    _meta(root, "factory:layout", "floor-plan-3-2-3-2")
    for group in ("Walls", "Workstations", "AGVs", "Humans", "Aisles", "Safety", "Lighting", "Cameras"):
        _xform(stage, ROOT + "/" + group)
    _box(stage, ROOT + "/Floor", (0, 0, -0.1), (32, 32, 0.2), (0.18, 0.20, 0.22))
    # Navigation Core reliably bakes the PhysX ground-plane mesh. Keep the
    # visible floor cube for appearance and overlay an invisible walk surface.
    omni.physxcommands.AddGroundPlaneCommand.execute(
        stage,
        ROOT + "/NavigationGround",
        UsdGeom.GetStageUpAxis(stage),
        32.0,
        Gf.Vec3f(0.0),
        Gf.Vec3f(0.18, 0.20, 0.22),
    )
    for prim in stage.TraverseAll():
        if str(prim.GetPath()).startswith(ROOT + "/NavigationGround") and prim.IsA(UsdGeom.Gprim):
            UsdGeom.Gprim(prim).CreateDisplayOpacityAttr([0.0])

    # Floor-plan boundary: the right and bottom sides intentionally retain openings.
    wall_color = (0.08, 0.09, 0.10)
    _box(stage, ROOT + "/Walls/Top", (-1.5, 14.0, 1.5), (20.0, 0.22, 3.0), wall_color)
    _box(stage, ROOT + "/Walls/Left", (-11.5, -0.75, 1.5), (0.22, 29.5, 3.0), wall_color)
    _box(stage, ROOT + "/Walls/RightUpper", (8.5, 9.0, 1.5), (0.22, 10.0, 3.0), wall_color)
    _box(stage, ROOT + "/Walls/BottomLeft", (-2.5, -15.5, 1.5), (18.0, 0.22, 3.0), wall_color)
    _meta(stage.GetPrimAtPath(ROOT + "/Walls/RightUpper"), "factory:openingBelow", True)
    _meta(stage.GetPrimAtPath(ROOT + "/Walls/BottomLeft"), "factory:openingOnRight", True)

    aisle_specs = (
        ("UpperCrossAisle", (-1.5, 7.1, 0.012), (18.0, 1.6, 0.025), "two-way along X"),
        ("MiddleCrossAisle", (-1.5, -3.0, 0.012), (18.0, 2.0, 0.025), "two-way along X"),
        ("EastVerticalAisle", (7.0, -4.0, 0.012), (2.2, 22.0, 0.025), "two-way along Y"),
    )
    for name, position, dimensions, direction in aisle_specs:
        aisle = _box(stage, ROOT + "/Aisles/" + name, position, dimensions, (0.12, 0.15, 0.18), False)
        _meta(aisle, "factory:widthMeters", float(min(dimensions[0], dimensions[1])))
        _meta(aisle, "factory:direction", direction)
    walkway = _box(
        stage,
        ROOT + "/Safety/PedestrianWalkwayWest",
        (-10.1, -0.5, 0.032),
        (1.2, 28.0, 0.03),
        (0.16, 0.42, 0.68),
        False,
    )
    _meta(walkway, "factory:purpose", "pedestrian walkway")
    for number, y in enumerate((7.1, -3.0, -14.0), 1):
        _box(
            stage,
            ROOT + "/Safety/Crossing_{:02d}".format(number),
            (-10.1, y, 0.052),
            (1.2, 0.65, 0.025),
            (0.92, 0.92, 0.92),
            False,
        )
    for number, x in enumerate((-8, -4, 0, 4), 1):
        _box(
            stage,
            ROOT + "/Safety/UpperDash_{:02d}".format(number),
            (x, 7.1, 0.04),
            (1.8, 0.1, 0.025),
            (0.95, 0.95, 0.90),
            False,
        )
        _box(
            stage,
            ROOT + "/Safety/MiddleDash_{:02d}".format(number),
            (x, -3.0, 0.04),
            (1.8, 0.1, 0.025),
            (0.95, 0.95, 0.90),
            False,
        )

    # Coordinates are mapped from the image: x_local=x_plan-16, y_local=16-y_plan.
    station_specs = (
        (-7.35, 10.15, 3.0, 4.0, "RobotArm", 1),
        (-2.25, 10.15, 2.0, 4.0, "CNC", 1),
        (3.45, 10.15, 3.6, 4.0, "Inspection", 1),
        (-4.90, 2.30, 8.0, 8.0, "Assembly", 2),
        (3.40, 2.25, 3.6, 8.0, "Packing", 2),
        (-7.25, -5.90, 3.0, 4.0, "RobotArm", 3),
        (-2.80, -5.90, 3.5, 4.0, "CNC", 3),
        (3.40, -5.90, 3.6, 4.0, "Inspection", 3),
        (-4.85, -11.65, 8.0, 4.0, "Assembly", 4),
        (3.40, -11.70, 3.6, 4.0, "Packing", 4),
    )
    stations = [
        _workstation(stage, number, x, y, width, depth, equipment, row)
        for number, (x, y, width, depth, equipment, row) in enumerate(station_specs, 1)
    ]
    agvs = [
        _agv(stage, 1, -5.5, 7.1, "UpperCrossAisle", "row-1-to-row-2"),
        _agv(stage, 2, -1.0, -3.0, "MiddleCrossAisle", "row-2-to-row-3"),
        _agv(stage, 3, 7.0, -9.0, "EastVerticalAisle", "south-gate-to-upper-gate"),
    ]
    # Real people are added afterward through spawn_human. Keep this group
    # empty so box-built placeholders do not overlap NVIDIA characters.
    humans = []
    dome = UsdLux.DomeLight.Define(stage, ROOT + "/Lighting/FactoryDome")
    dome.CreateIntensityAttr(450.0)
    dome.CreateColorAttr(Gf.Vec3f(0.82, 0.88, 1.0))
    for number, x in enumerate((-8, 0, 8), 1):
        light = UsdLux.RectLight.Define(stage, ROOT + "/Lighting/Overhead_{:02d}".format(number))
        light.CreateIntensityAttr(4500.0)
        light.CreateWidthAttr(8.0)
        light.CreateHeightAttr(5.0)
        UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(x, 0, 12))
    # RtxCamera authors OmniSensorAPI, required by sensors.capture_image.
    from isaacsim.sensors.experimental.rtx import RtxCamera

    RtxCamera(path=ROOT + "/Cameras/FactoryOverview")
    camera = UsdGeom.Camera(stage.GetPrimAtPath(ROOT + "/Cameras/FactoryOverview"))
    camera.CreateFocalLengthAttr(24.0)
    camera.CreateHorizontalApertureAttr(36.0)
    _meta(camera.GetPrim(), "factory:purpose", "overview")
    from isaac_sim_mcp_extension.adapters.transforms import set_transform

    set_transform(UsdGeom.Xformable(camera), position=(-1.5, -38, 38), rotation=(45, 0, 0), scale=(1, 1, 1))
    export_ok, export_error = False, None
    try:
        os.makedirs(os.path.dirname(EXPORT_PATH), exist_ok=True)
        export_ok = _export_factory_only(stage)
        if not export_ok:
            export_error = "Usd.Stage.Export returned False"
    except Exception as exc:
        export_error = "{}: {}".format(type(exc).__name__, exc)
    result = {
        "success": True,
        "factory_path": ROOT,
        "workstation_count": len(stations),
        "robot_arm_count": len(stations),
        "agv_count": len(agvs),
        "human_count": len(humans),
        "row_counts": [3, 2, 3, 2],
        "aisle_path": ROOT + "/Aisles",
        "camera_path": ROOT + "/Cameras/FactoryOverview",
        "export_path": EXPORT_PATH,
        "export_ok": export_ok,
        "export_error": export_error,
    }
    print("FACTORY_SCENE_RESULT " + json.dumps(result, sort_keys=True))
    return result


build_factory_scene()
