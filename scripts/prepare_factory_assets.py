"""Prepare the generated factory for real NVIDIA assets spawned through MCP."""

import json

import omni.usd
from pxr import Gf, Sdf, UsdGeom

ROOT = "/World/Factory"


def _meta(prim, name, value):
    value_type = Sdf.ValueTypeNames.Bool if isinstance(value, bool) else Sdf.ValueTypeNames.String
    prim.CreateAttribute(name, value_type, custom=True).Set(value)


def _zone(stage, path, position, dimensions, color, purpose):
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    xform = UsdGeom.Xformable(cube)
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    xform.AddScaleOp().Set(Gf.Vec3f(*dimensions))
    _meta(cube.GetPrim(), "factory:purpose", purpose)


def prepare_factory_assets():
    stage = omni.usd.get_context().get_stage()
    if stage is None or not stage.GetPrimAtPath(ROOT).IsValid():
        raise RuntimeError("Build /World/Factory before preparing assets")

    removed = []
    stations = stage.GetPrimAtPath(ROOT + "/Workstations").GetChildren()
    for station in stations:
        for child in list(station.GetChildren()):
            if child.GetName() == "InteractiveRobotArm" or child.GetName().startswith("Fixture_"):
                path = child.GetPath()
                stage.RemovePrim(path)
                removed.append(str(path))

    agv_root = stage.GetPrimAtPath(ROOT + "/AGVs")
    for child in list(agv_root.GetChildren()):
        path = child.GetPath()
        stage.RemovePrim(path)
        removed.append(str(path))

    for group in ("Robots", "Conveyors", "Storage", "Vegetation", "Inspection"):
        stage.DefinePrim(ROOT + "/" + group, "Xform")

    _zone(
        stage,
        ROOT + "/Inspection/QuadrupedParking",
        (5.7, 12.4, 0.015),
        (2.0, 1.6, 0.025),
        (0.18, 0.48, 0.25),
        "quadruped inspection parking outside AGV lanes",
    )
    _zone(
        stage,
        ROOT + "/Storage/PalletStagingZone",
        (-1.0, -14.4, 0.015),
        (4.6, 1.4, 0.025),
        (0.48, 0.34, 0.10),
        "pallet and crate staging outside AGV lanes",
    )

    result = {
        "success": True,
        "removed_placeholder_count": len(removed),
        "station_count": len(stations),
        "groups": ["Robots", "Conveyors", "Storage", "Vegetation", "Inspection"],
    }
    print("FACTORY_ASSET_PREP_RESULT " + json.dumps(result, sort_keys=True))
    return result


prepare_factory_assets()
