"""Offline validation for the saved factory asset USD."""

from __future__ import annotations

import argparse
import json

from pxr import Sdf

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("usd_path")
    args = parser.parse_args()
    layer = Sdf.Layer.FindOrOpen(args.usd_path)
    if layer is None:
        raise RuntimeError("Could not open {}".format(args.usd_path))
    missing = []
    missing_references = []
    counts = {}
    for category, paths in EXPECTED.items():
        counts[category] = 0
        for path in paths:
            prim = layer.GetPrimAtPath(path)
            if prim is None:
                missing.append(path)
                continue
            counts[category] += 1
            if not prim.referenceList.prependedItems:
                missing_references.append(path)
    result = {
        "pass": not missing and not missing_references,
        "counts": counts,
        "missing": missing,
        "missing_references": missing_references,
        "total_assets": sum(counts.values()),
    }
    print(json.dumps(result, sort_keys=True))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
