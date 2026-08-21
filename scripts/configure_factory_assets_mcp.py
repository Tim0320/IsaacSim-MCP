"""Rebuild the factory and place the verified NVIDIA asset set through MCP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from isaac_mcp.connection import IsaacConnection

ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = ROOT / "test_outputs" / "factory_configured_assets.usda"

ARMS = [
    (-7.35, 10.15, 1.05),
    (-2.25, 10.15, 1.05),
    (3.45, 10.15, 1.05),
    (-6.55, 2.30, 1.05),
    (2.35, 2.25, 1.05),
    (-7.25, -5.90, 1.05),
    (-2.80, -5.90, 1.05),
    (3.40, -5.90, 1.05),
    (-6.50, -11.65, 1.05),
    (2.35, -11.70, 1.05),
]

ASSETS = [
    ("carter", "/World/Factory/AGVs/AGV_01", [-5.5, 7.1, 0.0], [0, 0, 0], None),
    ("carter", "/World/Factory/AGVs/AGV_02", [-1.0, -3.0, 0.0], [0, 0, 0], None),
    ("carter", "/World/Factory/AGVs/AGV_03", [7.0, -9.0, 0.0], [0, 0, 90], None),
    (
        "conveyor_a01",
        "/World/Factory/Conveyors/PackingConveyor_01",
        [4.15, 2.25, 1.08],
        [0, 0, 90],
        [0.55, 0.55, 0.55],
    ),
    (
        "conveyor_a01",
        "/World/Factory/Conveyors/PackingConveyor_02",
        [4.15, -11.70, 1.08],
        [0, 0, 90],
        [0.55, 0.55, 0.55],
    ),
    ("spot", "/World/Factory/Inspection/Spot_01", [5.7, 12.4, 0.5], [0, 0, 180], None),
    ("pallet", "/World/Factory/Storage/Pallet_01", [-2.1, -14.4, 0.0], [0, 0, 0], [0.75] * 3),
    ("pallet", "/World/Factory/Storage/Pallet_02", [0.2, -14.4, 0.0], [0, 0, 0], [0.75] * 3),
    ("blue_crate", "/World/Factory/Storage/BlueCrate_01", [1.1, -14.4, 0.35], [0, 0, 0], [0.65] * 3),
    ("klt_bin", "/World/Factory/Storage/KLTBin_01", [-2.8, 2.3, 1.1], [0, 0, 0], [0.65] * 3),
    ("klt_bin", "/World/Factory/Storage/KLTBin_02", [-2.8, -11.65, 1.1], [0, 0, 0], [0.65] * 3),
    ("boxwood_shrub", "/World/Factory/Vegetation/Boxwood_01", [-13.5, 10.0, 0.0], [0, 0, 0], [0.65] * 3),
    ("boxwood_shrub", "/World/Factory/Vegetation/Boxwood_02", [-13.5, -10.0, 0.0], [0, 0, 0], [0.65] * 3),
]


def _require(conn: IsaacConnection, command: str, params: dict) -> dict:
    result = conn.send_command(command, params)
    if result.get("status") != "success":
        raise RuntimeError("{} failed: {}".format(command, json.dumps(result)))
    print("OK", command, params.get("asset_key", params.get("file_path", "")))
    return result


def configure(port: int) -> None:
    conn = IsaacConnection(port=port)
    try:
        _require(conn, "simulation.reload_script", {"file_path": str(ROOT / "scripts" / "create_factory_scene.py")})
        _require(conn, "simulation.reload_script", {"file_path": str(ROOT / "scripts" / "prepare_factory_assets.py")})
        for index, position in enumerate(ARMS, 1):
            _require(
                conn,
                "assets.spawn_nvidia",
                {
                    "asset_key": "frankaemika",
                    "prim_path": "/World/Factory/Robots/WorkstationArm_{:02d}".format(index),
                    "position": list(position),
                },
            )
        for key, prim_path, position, rotation, scale in ASSETS:
            params = {"asset_key": key, "prim_path": prim_path, "position": position, "rotation": rotation}
            if scale is not None:
                params["scale"] = scale
            _require(conn, "assets.spawn_nvidia", params)
        _require(
            conn,
            "simulation.reload_script",
            {"file_path": str(ROOT / "scripts" / "factory_asset_interaction.py")},
        )
        _require(conn, "simulation.reload_script", {"file_path": str(ROOT / "scripts" / "verify_factory_assets.py")})
        export_code = """
import os, omni.usd
stage = omni.usd.get_context().get_stage()
path = r'{}'
os.makedirs(os.path.dirname(path), exist_ok=True)
result = {{'ok': bool(stage.GetRootLayer().Export(path)), 'path': path}}
print('FACTORY_CONFIG_EXPORT', result)
""".format(str(EXPORT_PATH))
        _require(conn, "simulation.execute_script", {"code": export_code})
    finally:
        conn.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    configure(parser.parse_args().port)


if __name__ == "__main__":
    main()
