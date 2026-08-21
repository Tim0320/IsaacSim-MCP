"""Verify the real NVIDIA assets placed in the factory through MCP."""

import json

import omni.usd

ROOT = "/World/Factory"
EXPECTED = {
    "robot_arms": [ROOT + "/Robots/WorkstationArm_{:02d}".format(index) for index in range(1, 11)],
    "agvs": [ROOT + "/AGVs/AGV_{:02d}".format(index) for index in range(1, 4)],
    "conveyors": [ROOT + "/Conveyors/PackingConveyor_{:02d}".format(index) for index in range(1, 3)],
    "quadrupeds": [ROOT + "/Inspection/Spot_01"],
    "storage": [
        ROOT + "/Storage/Pallet_01",
        ROOT + "/Storage/Pallet_02",
        ROOT + "/Storage/BlueCrate_01",
        ROOT + "/Storage/KLTBin_01",
        ROOT + "/Storage/KLTBin_02",
    ],
    "vegetation": [ROOT + "/Vegetation/Boxwood_01", ROOT + "/Vegetation/Boxwood_02"],
}


def verify_factory_assets():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No live USD stage")
    missing = []
    invalid_references = []
    counts = {}
    for category, paths in EXPECTED.items():
        counts[category] = 0
        for path in paths:
            prim = stage.GetPrimAtPath(path)
            if not prim.IsValid():
                missing.append(path)
                continue
            counts[category] += 1
            references = prim.GetMetadata("references")
            if references is None or not references.GetAppliedItems():
                invalid_references.append(path)
    result = {
        "pass": not missing and not invalid_references,
        "counts": counts,
        "missing": missing,
        "invalid_references": invalid_references,
        "total_assets": sum(counts.values()),
    }
    print("FACTORY_ASSET_VERIFY_RESULT " + json.dumps(result, sort_keys=True))
    return result


verify_factory_assets()
