#!/usr/bin/env python3
"""Exercise every public MCP tool against a running Isaac Sim instance."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "test_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
RESULT_PATH = OUTPUT_DIR / "all_tools_results.json"


def parse_payload(result: Any) -> dict[str, Any]:
    text = ""
    for item in result.content:
        if getattr(item, "type", None) == "text":
            text = item.text
            break
    try:
        payload = json.loads(text)
    except Exception:
        payload = {"raw": text}
    return payload if isinstance(payload, dict) else {"value": payload}


async def main() -> int:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    server = StdioServerParameters(
        command=str(python),
        args=["-m", "isaac_mcp.server"],
        env={**os.environ, "ISAAC_MCP_PORT": "8766"},
    )
    results: dict[str, dict[str, Any]] = {}

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            expected = {tool.name for tool in listed.tools}

            async def call(name: str, args: dict[str, Any] | None = None, timeout: float = 180) -> dict[str, Any]:
                started = time.perf_counter()
                try:
                    raw = await asyncio.wait_for(session.call_tool(name, args or {}), timeout=timeout)
                    payload = parse_payload(raw)
                    message = str(payload.get("message", ""))
                    status = "pass"
                    if raw.isError or payload.get("status") == "error":
                        if any(key in message for key in ("ARK_API_KEY", "BEAVER3D_MODEL", "NVIDIA_API_KEY")):
                            status = "blocked_external_config"
                        else:
                            status = "fail"
                    entry = {
                        "status": status,
                        "duration_seconds": round(time.perf_counter() - started, 3),
                        "payload": payload,
                    }
                except Exception as exc:
                    entry = {
                        "status": "fail",
                        "duration_seconds": round(time.perf_counter() - started, 3),
                        "exception": repr(exc),
                    }
                results[name] = entry
                print(f"[{entry['status'].upper():>23}] {name} ({entry['duration_seconds']}s)", flush=True)
                return entry

            def payload_of(name: str) -> dict[str, Any]:
                return results.get(name, {}).get("payload", {})

            def dependency_block(name: str, dependency: str) -> None:
                results[name] = {"status": "blocked_dependency", "dependency": dependency}
                print(f"[{'BLOCKED_DEPENDENCY':>23}] {name} ({dependency})", flush=True)

            await call("get_scene_info")
            await call("clear_scene")
            await call("create_physics_scene", {"gravity": [0, 0, -9.81], "scene_name": "TestPhysicsScene"})
            await call("list_prims", {"root_path": "/World"})
            await call("list_environments")
            await call("load_environment", {"environment": "grid", "prim_path": "/Environment/TestGrid"})

            await call(
                "create_object",
                {
                    "object_type": "Cube",
                    "prim_path": "/World/TestCube",
                    "position": [0, 0, 1],
                    "size": 0.4,
                    "color": [0.2, 0.6, 0.9],
                    "physics_enabled": True,
                },
            )
            await call("get_prim_info", {"prim_path": "/World/TestCube"})
            await call(
                "transform_object",
                {"prim_path": "/World/TestCube", "position": [0.2, 0, 1.2], "rotation": [0, 0, 15]},
            )
            await call(
                "clone_object",
                {"source_path": "/World/TestCube", "target_path": "/World/TestCubeClone", "position": [1, 0, 1]},
            )
            await call(
                "create_light",
                {
                    "light_type": "SphereLight",
                    "prim_path": "/World/TestLight",
                    "position": [0, 0, 3],
                    "intensity": 500,
                    "color": [1, 0.9, 0.8],
                },
            )
            await call("modify_light", {"prim_path": "/World/TestLight", "intensity": 750, "color": [0.8, 0.9, 1]})
            await call(
                "create_material",
                {
                    "material_type": "pbr",
                    "prim_path": "/World/Looks/TestMaterial",
                    "color": [0.8, 0.2, 0.2],
                    "roughness": 0.4,
                    "metallic": 0.1,
                },
            )
            await call(
                "apply_material",
                {"material_path": "/World/Looks/TestMaterial", "target_prim_path": "/World/TestCube"},
            )
            await call("set_physics_params", {"gravity": [0, 0, -9.81]})
            unsupported_physics = await session.call_tool(
                "set_physics_params", {"time_step": 0.0166667, "gpu_enabled": True}
            )
            unsupported_physics_payload = parse_payload(unsupported_physics)
            if unsupported_physics_payload.get("status") == "error":
                results["set_physics_params"]["status"] = "partial"
                results["set_physics_params"]["unsupported_probe"] = unsupported_physics_payload
            await call("get_physics_state", {"prim_path": "/World/TestCube"})
            await call("step_simulation", {"num_steps": 2, "observe_prims": ["/World/TestCube"]})
            await call("play_simulation")
            await asyncio.sleep(0.5)
            await call("pause_simulation")
            await call("stop_simulation")
            await call("get_simulation_state")

            await call("list_nvidia_assets", {"category": "conveyor", "max_results": 5}, timeout=240)
            await call(
                "spawn_nvidia_asset",
                {
                    "asset_key": "pallet",
                    "prim_path": "/World/TestNvidiaPallet",
                    "position": [3, 0, 0],
                },
                timeout=240,
            )

            await call(
                "spawn_human",
                {
                    "count": 1,
                    "group_name": "MCPToolTestHumans",
                    "behavior": "stop",
                    "position": [0, 2, 0],
                    "auto_create_navmesh_volume": True,
                    "navmesh_volume_center": [0, 0, 1.5],
                    "navmesh_volume_size": [40, 40, 4],
                },
                timeout=300,
            )

            await call("list_available_robots", timeout=240)
            await call("refresh_robot_library", timeout=240)
            robot = await call(
                "create_robot",
                {"robot_type": "franka", "prim_path": "/World/TestFranka", "position": [0, 0, 0]},
                timeout=240,
            )
            if robot["status"] == "pass":
                info = await call("get_robot_info", {"prim_path": "/World/TestFranka"}, timeout=120)
                info_payload = info.get("payload", {})
                dof = int(info_payload.get("num_dof") or payload_of("create_robot").get("num_dof") or 9)
                await call(
                    "set_joint_positions",
                    {"prim_path": "/World/TestFranka", "joint_positions": [0.0] * dof},
                    timeout=120,
                )
                await call(
                    "step_simulation",
                    {"num_steps": 2, "observe_joints": ["/World/TestFranka"]},
                    timeout=120,
                )
                await call("get_joint_positions", {"prim_path": "/World/TestFranka"}, timeout=120)
                await call("get_joint_config", {"prim_path": "/World/TestFranka"}, timeout=120)
            else:
                for name in ("get_robot_info", "set_joint_positions", "get_joint_positions", "get_joint_config"):
                    dependency_block(name, "create_robot")

            await call(
                "create_camera",
                {
                    "prim_path": "/World/TestCamera",
                    "position": [3, 3, 2],
                    "rotation": [65, 0, 135],
                    "resolution": [320, 240],
                },
            )
            await call(
                "create_lidar",
                {"prim_path": "/World/TestLidar", "position": [0, 0, 1.5], "config": "Example_Rotary"},
                timeout=120,
            )
            await call("play_simulation")
            await call(
                "capture_image",
                {"prim_path": "/World/TestCamera", "output_path": str(OUTPUT_DIR / "camera.png")},
                timeout=120,
            )
            await call("get_lidar_point_cloud", {"prim_path": "/World/TestLidar"}, timeout=120)
            await asyncio.sleep(5)
            await call(
                "capture_image",
                {"prim_path": "/World/TestCamera", "output_path": str(OUTPUT_DIR / "camera.png")},
                timeout=120,
            )
            await call("get_lidar_point_cloud", {"prim_path": "/World/TestLidar"}, timeout=120)
            await call("stop_simulation")

            await call(
                "import_urdf",
                {
                    "urdf_path": str(ROOT / "test_assets" / "minimal_robot.urdf"),
                    "prim_path": "/World/TestUrdf",
                    "position": [2, 0, 0.2],
                },
                timeout=240,
            )
            await call(
                "load_usd",
                {
                    "usd_url": str(ROOT / "test_assets" / "minimal_asset.usda"),
                    "prim_path": "/World/TestUsd",
                    "position": [-2, 0, 0.2],
                    "scale": [1, 1, 1],
                },
            )
            await call("search_usd", {"text_prompt": "a wooden pallet", "target_path": "/World/TestSearchUsd"})
            await call("generate_3d", {"text_prompt": "a small red cube", "position": [0, 2, 0.5]})

            await call("execute_script", {"code": "print('MCP_EXECUTE_SCRIPT_OK')\nresult = 6 * 7"})
            await call("reload_script", {"file_path": str(ROOT / "test_assets" / "reload_target.py")})
            await call(
                "create_action_graph",
                {
                    "graph_path": "/World/TestActionGraph",
                    "inline_script": "def setup(db):\n    pass\n\ndef compute(db):\n    return True",
                },
            )
            await call(
                "edit_action_graph",
                {
                    "graph_path": "/World/TestActionGraph",
                    "values": [{"attr": "ScriptNode.inputs:usePath", "value": False}],
                },
            )
            inline_edit_probe = await session.call_tool(
                "edit_action_graph",
                {
                    "graph_path": "/World/TestActionGraph",
                    "values": [
                        {
                            "attr": "ScriptNode.inputs:script",
                            "value": "def setup(db):\n    pass\n\ndef compute(db):\n    return True",
                        }
                    ],
                },
            )
            inline_edit_payload = parse_payload(inline_edit_probe)
            if inline_edit_payload.get("status") == "error":
                results["edit_action_graph"]["status"] = "partial"
                results["edit_action_graph"]["inline_script_probe"] = inline_edit_payload
            await call("get_isaac_logs", {"clear": False, "count": 50, "since_last_play": False})
            await call("delete_object", {"prim_path": "/World/TestCubeClone"})

            missing = sorted(expected - set(results))
            extra = sorted(set(results) - expected)
            summary = {
                "tool_count": len(expected),
                "tested_count": len(results),
                "missing": missing,
                "extra": extra,
                "counts": {
                    status: sum(1 for entry in results.values() if entry["status"] == status)
                    for status in sorted({entry["status"] for entry in results.values()})
                },
                "results": results,
            }
            RESULT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(summary["counts"], ensure_ascii=False), flush=True)
            print(f"Results: {RESULT_PATH}", flush=True)
            return 1 if missing or any(entry["status"] == "fail" for entry in results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
