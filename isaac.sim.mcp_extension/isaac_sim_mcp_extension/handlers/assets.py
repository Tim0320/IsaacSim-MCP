# MIT License
#
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Asset import and loading command handlers."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

from ..adapters.base import IsaacAdapterBase

_NVIDIA_ASSETS_ROOT = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets"
_USD_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Small, verified entry-point catalog. Robot entries are discovered live from
# /Isaac/Robots so the catalog follows the installed Isaac Sim asset version.
NVIDIA_ASSET_CATALOG: Dict[str, Dict[str, str]] = {
    "cargo_crane": {
        "category": "lifting",
        "description": "NVIDIA Digital Twin cargo crane",
        "asset_path": "/DigitalTwin/Assets/Warehouse/Equipment/Cranes/Cargo_A/CargoCrane_A01_01.usd",
        "thumbnail_path": (
            "/DigitalTwin/Assets/Warehouse/Equipment/Cranes/Cargo_A/.thumbs/256x256/CargoCrane_A01_01.usd.png"
        ),
        "load_profile": "heavy; first remote composition may exceed five minutes",
        "source": "nvidia",
    },
    "portable_gantry_crane": {
        "category": "lifting",
        "description": "NVIDIA Digital Twin portable gantry crane with hoist",
        "asset_path": (
            "/DigitalTwin/Assets/Warehouse/Equipment/Cranes/PortableGantry_A/PortableGantryCrane_A01_01.usd"
        ),
        "thumbnail_path": (
            "/DigitalTwin/Assets/Warehouse/Equipment/Cranes/PortableGantry_A/.thumbs/256x256/"
            "PortableGantryCrane_A01_01.usd.png"
        ),
        "load_profile": "heavy; first remote composition may exceed five minutes",
        "source": "nvidia",
    },
    "jib_crane": {
        "category": "lifting",
        "description": "NVIDIA Digital Twin jib crane with hook",
        "asset_path": "/DigitalTwin/Assets/Warehouse/Equipment/Cranes/Jib_A/JibCrane_A01_01.usd",
        "thumbnail_path": (
            "/DigitalTwin/Assets/Warehouse/Equipment/Cranes/Jib_A/.thumbs/256x256/JibCrane_A01_01.usd.png"
        ),
        "load_profile": "heavy; first remote composition may exceed five minutes",
        "source": "nvidia",
    },
    "scissor_lift_table": {
        "category": "lifting",
        "description": "SimReady mobile scissor lift table",
        "asset_path": (
            "/Isaac/SimReady/Industrial/Equipment/Scissor_Mobile_Lift_Table_A01/"
            "sm_equipment_liftTable_scissorMobile_a01_01.usd"
        ),
        "thumbnail_path": (
            "/Isaac/SimReady/Industrial/Equipment/Scissor_Mobile_Lift_Table_A01/.thumbs/256x256/"
            "sm_equipment_liftTable_scissorMobile_a01_01.usd.png"
        ),
        "source": "isaac",
    },
    "oscilloscope_a01": {
        "category": "instrumentation",
        "description": "SimReady digital oscilloscope",
        "asset_path": ("/Isaac/SimReady/Industrial/Tools/Oscilloscope_A01/sm_testingTool_oscilloscope_a01_01.usd"),
        "thumbnail_path": (
            "/Isaac/SimReady/Industrial/Tools/Oscilloscope_A01/.thumbs/256x256/"
            "sm_testingTool_oscilloscope_a01_01.usd.png"
        ),
        "source": "isaac",
    },
    "digital_multimeter_b01": {
        "category": "instrumentation",
        "description": "SimReady high-detail digital multimeter and probes",
        "asset_path": (
            "/Isaac/SimReady/Industrial/Tools/Digital_Multimeter_B01/sm_testingTool_multimeter_digital_b01_01.usd"
        ),
        "thumbnail_path": (
            "/Isaac/SimReady/Industrial/Tools/Digital_Multimeter_B01/.thumbs/256x256/"
            "sm_testingTool_multimeter_digital_b01_01.usd.png"
        ),
        "source": "isaac",
    },
    "wheel_alignment_scanner": {
        "category": "instrumentation",
        "description": "SimReady wheel-alignment optical scanner unit",
        "asset_path": (
            "/Isaac/SimReady/Industrial/Tools/Testing/Wheel_Alignment_Lift_Scanner_Unit_B01/"
            "sm_testingTool_wheel_alignment_lift_scannerUnit_b01_01.usd"
        ),
        "thumbnail_path": (
            "/Isaac/SimReady/Industrial/Tools/Testing/Wheel_Alignment_Lift_Scanner_Unit_B01/"
            ".thumbs/256x256/sm_testingTool_wheel_alignment_lift_scannerUnit_b01_01.usd.png"
        ),
        "source": "isaac",
    },
    "rigid_inspection_task_light": {
        "category": "instrumentation",
        "description": "SimReady rigid inspection task light",
        "asset_path": (
            "/Isaac/SimReady/Industrial/Equipment/Rigid_Inspection_Task_Light_A01/"
            "sm_lighting_taskLight_rigidInspection_a01_01.usd"
        ),
        "thumbnail_path": (
            "/Isaac/SimReady/Industrial/Equipment/Rigid_Inspection_Task_Light_A01/.thumbs/256x256/"
            "sm_lighting_taskLight_rigidInspection_a01_01.usd.png"
        ),
        "source": "isaac",
    },
    "wall_display_panel": {
        "category": "instrumentation",
        "description": "SimReady industrial wall display panel",
        "asset_path": (
            "/Isaac/SimReady/Industrial/Equipment/Wall_Display_Panel_A01/sm_digitalSystem_displayPanel_wall_a01_01.usd"
        ),
        "thumbnail_path": (
            "/Isaac/SimReady/Industrial/Equipment/Wall_Display_Panel_A01/.thumbs/256x256/"
            "sm_digitalSystem_displayPanel_wall_a01_01.usd.png"
        ),
        "source": "isaac",
    },
    "conveyor_a01": {
        "category": "conveyor",
        "description": "Straight NVIDIA conveyor belt A01",
        "asset_path": "/Isaac/Props/Conveyors/ConveyorBelt_A01.usd",
        "source": "isaac",
    },
    "conveyor_a13": {
        "category": "conveyor",
        "description": "NVIDIA conveyor belt A13",
        "asset_path": "/Isaac/Props/Conveyors/ConveyorBelt_A13.usd",
        "source": "isaac",
    },
    "conveyor_a31": {
        "category": "conveyor",
        "description": "NVIDIA conveyor belt A31",
        "asset_path": "/Isaac/Props/Conveyors/ConveyorBelt_A31.usd",
        "source": "isaac",
    },
    "pallet": {
        "category": "warehouse",
        "description": "Warehouse pallet",
        "asset_path": "/Isaac/Props/Pallet/pallet.usd",
        "source": "isaac",
    },
    "pallet_holder": {
        "category": "warehouse",
        "description": "Pallet holder",
        "asset_path": "/Isaac/Props/Pallet/pallet_holder.usd",
        "source": "isaac",
    },
    "klt_bin": {
        "category": "warehouse",
        "description": "Small KLT logistics bin",
        "asset_path": "/Isaac/Props/KLT_Bin/small_KLT.usd",
        "source": "isaac",
    },
    "packing_table": {
        "category": "warehouse",
        "description": "Packing workstation table",
        "asset_path": "/Isaac/Props/PackingTable/packing_table.usd",
        "source": "isaac",
    },
    "dolly": {
        "category": "warehouse",
        "description": "Warehouse dolly",
        "asset_path": "/Isaac/Props/Dolly/dolly.usd",
        "source": "isaac",
    },
    "warehouse_rack_3m": {
        "category": "warehouse",
        "description": "3 meter SimReady warehouse rack",
        "asset_path": "/Isaac/SimReady/Industrial/Warehouse/Racks/3m_S01_Rack/sm_rack_h3m_s01_01.usd",
        "source": "isaac",
    },
    "bulk_storage_rack": {
        "category": "warehouse",
        "description": "SimReady bulk storage rack",
        "asset_path": (
            "/Isaac/SimReady/Industrial/Warehouse/Racks/Bulk_Storage_Rack_A03/sm_rack_bulk_storage_a03_01.usd"
        ),
        "source": "isaac",
    },
    "blue_crate": {
        "category": "warehouse",
        "description": "SimReady blue warehouse crate",
        "asset_path": ("/Isaac/SimReady/Industrial/Warehouse/Containers/Crate_Blue_A01/sm_crate_blue_a01_01.usd"),
        "source": "isaac",
    },
    "factory_gear_small": {
        "category": "factory",
        "description": "Small factory gear",
        "asset_path": "/Isaac/Props/Factory/gear_assets/factory_gear_small/factory_gear_small.usd",
        "source": "isaac",
    },
    "factory_bolt_m12": {
        "category": "factory",
        "description": "Loose M12 factory bolt",
        "asset_path": "/Isaac/Props/Factory/factory_bolt_m12_loose/factory_bolt_m12_loose.usd",
        "source": "isaac",
    },
    "boxwood_shrub": {
        "category": "vegetation",
        "description": "NVIDIA Boxwood shrub",
        "asset_path": "/Vegetation/Shrub/Boxwood.usd",
        "source": "nvidia",
    },
    "cedar_shrub": {
        "category": "vegetation",
        "description": "NVIDIA Cedar shrub",
        "asset_path": "/Vegetation/Shrub/Cedar_Shrub.usd",
        "source": "nvidia",
    },
    "fountain_grass": {
        "category": "vegetation",
        "description": "NVIDIA short fountain grass",
        "asset_path": "/Vegetation/Shrub/Fountain_Grass_Short.usd",
        "source": "nvidia",
    },
    "japanese_cherry_tree": {
        "category": "vegetation",
        "description": "NVIDIA Japanese cherry tree",
        "asset_path": "/Vegetation/Trees/Japanese_Cherry.usd",
        "source": "nvidia",
    },
    "red_maple_tree": {
        "category": "vegetation",
        "description": "NVIDIA Red Maple tree",
        "asset_path": "/Vegetation/Trees/Red_Maple.usd",
        "source": "nvidia",
    },
    "agave": {
        "category": "vegetation",
        "description": "NVIDIA Agave plant",
        "asset_path": "/Vegetation/Plant_Tropical/Agave.usd",
        "source": "nvidia",
    },
    "bamboo": {
        "category": "vegetation",
        "description": "NVIDIA Buddha Belly Bamboo",
        "asset_path": "/Vegetation/Plant_Tropical/Buddha_Belly_Bamboo.usd",
        "source": "nvidia",
    },
}

_QUADRUPED_TERMS = ("anymal", "spot", "go1", "go2", "aliengo", "laikago", "unitree a1", "unitree b2")
_AGV_TERMS = (
    "agv",
    "amr",
    "carter",
    "jetbot",
    "forklift",
    "syncro",
    "trakr",
    "mir",
    "husky",
    "kaya",
    "ridgeback",
)
_ARM_TERMS = (
    "franka",
    "fanuc",
    "kuka",
    "comau",
    "ufactory",
    "xarm",
    "cobotta",
    "universal robots",
    "ur5",
    "ur10",
    "kinova",
    "jaco",
    "sawyer",
    "doosan",
    "yaskawa",
    "kawasaki",
)


def register(registry: Dict[str, Any], adapter: IsaacAdapterBase) -> None:
    registry["assets.import_urdf"] = lambda **p: import_urdf(adapter, **p)
    registry["assets.load_usd"] = lambda **p: load_usd(adapter, **p)
    registry["assets.search_usd"] = lambda **p: search_usd(adapter, **p)
    registry["assets.generate_3d"] = lambda **p: generate_3d(adapter, **p)
    registry["assets.list_nvidia"] = lambda **p: list_nvidia_assets(adapter, **p)
    registry["assets.spawn_nvidia"] = lambda **p: spawn_nvidia_asset(adapter, **p)


def _classify_robot(key: str, info: Dict[str, str]) -> str:
    searchable = f"{key} {info.get('description', '')} {info.get('manufacturer', '')}".lower()
    if any(term in searchable for term in _QUADRUPED_TERMS):
        return "quadruped"
    if any(term in searchable for term in _AGV_TERMS):
        return "agv"
    if any(term in searchable for term in _ARM_TERMS):
        return "robot_arm"
    return "robot_other"


def _catalog_entries(adapter: IsaacAdapterBase) -> list[Dict[str, Any]]:
    from .robots import _get_robot_library

    entries = []
    for key, info in NVIDIA_ASSET_CATALOG.items():
        category = info["category"]
        thumbnail_root = (
            adapter.get_assets_root_path().rstrip("/") if info["source"] == "isaac" else _NVIDIA_ASSETS_ROOT
        )
        thumbnail_url = thumbnail_root + info["thumbnail_path"] if info.get("thumbnail_path") else None
        if category == "conveyor":
            control_tool = "create_action_graph / reload_script / execute_script"
            interaction_note = "Add a belt-motion Action Graph or reusable controller script after spawning."
        elif category == "lifting":
            control_tool = "transform_object / create_action_graph / execute_script"
            interaction_note = "Lifting model with no prebuilt MCP hoist controller; script movable parts as needed."
        elif category == "instrumentation":
            control_tool = "transform_object / clone_object / delete_object / execute_script"
            interaction_note = "Instrument prop; connect sensor or display logic through a reusable script."
        else:
            control_tool = "transform_object / clone_object / delete_object"
            interaction_note = "Static referenced asset; transform, clone, or delete it through MCP."
        entries.append(
            {
                "key": key,
                **info,
                "spawn_tool": "spawn_nvidia_asset",
                "control_tool": control_tool,
                "interaction_note": interaction_note,
                "thumbnail_url": thumbnail_url,
            }
        )
    for key, info in _get_robot_library(adapter).items():
        entries.append(
            {
                "key": key,
                **info,
                "category": _classify_robot(key, info),
                "source": "isaac",
                "spawn_tool": "spawn_nvidia_asset or create_robot",
                "control_tool": "get_robot_info / set_joint_positions / create_action_graph",
                "interaction_note": (
                    "Quadrupeds require a compatible locomotion policy; mobile robots require a wheel/base "
                    "controller; arms can be driven by joints or an Action Graph."
                ),
            }
        )
    return entries


def list_nvidia_assets(
    adapter: IsaacAdapterBase,
    category: Optional[str] = None,
    query: Optional[str] = None,
    max_results: int = 50,
) -> Dict[str, Any]:
    """List curated props plus the live-discovered Isaac robot catalog."""
    try:
        if not isinstance(max_results, int) or not 1 <= max_results <= 250:
            return {"status": "error", "message": "max_results must be an integer from 1 to 250"}
        category_filter = (category or "all").lower().strip()
        valid_categories = {
            "all",
            "robot_arm",
            "quadruped",
            "agv",
            "robot_other",
            "conveyor",
            "warehouse",
            "factory",
            "lifting",
            "instrumentation",
            "vegetation",
        }
        if category_filter not in valid_categories:
            return {"status": "error", "message": f"category must be one of: {sorted(valid_categories)}"}
        query_filter = (query or "").lower().strip()
        entries = []
        for entry in _catalog_entries(adapter):
            if category_filter != "all" and entry["category"] != category_filter:
                continue
            searchable = " ".join(str(value) for value in entry.values()).lower()
            if query_filter and query_filter not in searchable:
                continue
            entries.append(entry)
        entries.sort(key=lambda item: (item["category"], item["key"]))
        return {
            "status": "success",
            "category": category_filter,
            "query": query_filter,
            "match_count": len(entries),
            "returned_count": min(len(entries), max_results),
            "assets": entries[:max_results],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def spawn_nvidia_asset(
    adapter: IsaacAdapterBase,
    asset_key: Optional[str] = None,
    prim_path: Optional[str] = None,
    position: Optional[Sequence[float]] = None,
    rotation: Optional[Sequence[float]] = None,
    scale: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Spawn one verified catalog asset while preserving the current stage."""
    try:
        if not asset_key:
            return {"status": "error", "message": "asset_key is required"}
        key = asset_key.lower().strip()
        state = adapter.get_simulation_state()
        if state.get("timeline_state") == "playing":
            return {"status": "error", "message": "Stop or pause the timeline before spawning an asset"}

        from .robots import _get_robot_library
        from .robots import create as create_robot

        robot_library = _get_robot_library(adapter)
        if key in robot_library:
            result = create_robot(adapter, robot_type=key, position=position, prim_path=prim_path)
            if result.get("status") == "success" and (rotation is not None or scale is not None):
                adapter.set_prim_transform(result["prim_path"], rotation=rotation, scale=scale)
            result["category"] = _classify_robot(key, robot_library[key])
            result["asset_key"] = key
            result["control_tool"] = "get_robot_info / set_joint_positions / create_action_graph"
            return result

        entry = NVIDIA_ASSET_CATALOG.get(key)
        if entry is None:
            return {
                "status": "error",
                "message": f"Unknown asset_key '{asset_key}'. Call list_nvidia_assets first.",
            }
        if prim_path is not None and (
            not prim_path.startswith("/") or not _USD_IDENTIFIER.fullmatch(prim_path.rsplit("/", 1)[-1])
        ):
            return {"status": "error", "message": "prim_path must be absolute and end in a valid USD identifier"}

        stage = adapter.get_stage()
        if stage is None:
            return {"status": "error", "message": "No USD stage is open"}
        if prim_path is None:
            import omni.usd

            prim_path = omni.usd.get_stage_next_free_path(stage, f"/World/Assets/{key}", False)
        elif stage.GetPrimAtPath(prim_path).IsValid():
            return {"status": "error", "message": f"Prim already exists: {prim_path}"}

        if entry["source"] == "isaac":
            asset_url = adapter.get_assets_root_path().rstrip("/") + entry["asset_path"]
        else:
            asset_url = _NVIDIA_ASSETS_ROOT + entry["asset_path"]
        adapter.add_reference_to_stage(asset_url, prim_path)
        adapter.set_prim_transform(prim_path, position=position, rotation=rotation, scale=scale)
        if entry["category"] == "conveyor":
            control_tool = "create_action_graph / reload_script / execute_script"
            interaction_note = "Add a belt-motion Action Graph or reusable controller script after spawning."
        elif entry["category"] == "lifting":
            control_tool = "transform_object / create_action_graph / execute_script"
            interaction_note = "Lifting model with no prebuilt MCP hoist controller; script movable parts as needed."
        elif entry["category"] == "instrumentation":
            control_tool = "transform_object / clone_object / delete_object / execute_script"
            interaction_note = "Instrument prop; connect sensor or display logic through a reusable script."
        else:
            control_tool = "transform_object / clone_object / delete_object"
            interaction_note = "Static referenced asset; transform, clone, or delete it through MCP."
        return {
            "status": "success",
            "message": f"Spawned {entry['description']}",
            "asset_key": key,
            "category": entry["category"],
            "prim_path": prim_path,
            "asset_url": asset_url,
            "control_tool": control_tool,
            "interaction_note": interaction_note,
            "thumbnail_url": (
                (adapter.get_assets_root_path().rstrip("/") if entry["source"] == "isaac" else _NVIDIA_ASSETS_ROOT)
                + entry["thumbnail_path"]
                if entry.get("thumbnail_path")
                else None
            ),
            "load_profile": entry.get("load_profile", "normal"),
            "preserved_current_stage": True,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def import_urdf(
    adapter: IsaacAdapterBase,
    urdf_path: Optional[str] = None,
    prim_path: str = "/World/robot",
    position: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    try:
        if not urdf_path:
            return {"status": "error", "message": "urdf_path is required"}
        _result = adapter.import_urdf(urdf_path, prim_path=prim_path)
        if position:
            adapter.set_prim_transform(prim_path, position=position)
        return {"status": "success", "message": f"Imported URDF from {urdf_path}", "prim_path": prim_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def load_usd(
    adapter: IsaacAdapterBase,
    usd_url: Optional[str] = None,
    prim_path: str = "/World/my_usd",
    position: Optional[Sequence[float]] = None,
    scale: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    try:
        if not usd_url:
            return {"status": "error", "message": "usd_url is required"}
        from isaac_sim_mcp_extension.usd import USDLoader

        loader = USDLoader()
        result_path = loader.load_usd_from_url(url_path=usd_url, target_path=prim_path, location=position, scale=scale)
        return {"status": "success", "message": f"Loaded USD from {usd_url}", "prim_path": result_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def search_usd(
    adapter: IsaacAdapterBase,
    text_prompt: Optional[str] = None,
    target_path: str = "/World/my_usd",
    position: Optional[Sequence[float]] = None,
    scale: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    try:
        if not text_prompt:
            return {"status": "error", "message": "text_prompt is required"}
        from isaac_sim_mcp_extension.usd import USDLoader, USDSearch3d

        searcher = USDSearch3d()
        url = searcher.search(text_prompt)
        loader = USDLoader()
        prim_path = loader.load_usd_from_url(url_path=url, target_path=target_path)
        return {
            "status": "success",
            "message": f"Found and loaded USD for '{text_prompt}'",
            "prim_path": prim_path,
            "url": url,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_3d(
    adapter: IsaacAdapterBase,
    text_prompt: Optional[str] = None,
    image_url: Optional[str] = None,
    position: Optional[Sequence[float]] = None,
    scale: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    try:
        if not text_prompt and not image_url:
            return {"status": "error", "message": "Either text_prompt or image_url is required"}
        from isaac_sim_mcp_extension.gen3d import Beaver3d
        from isaac_sim_mcp_extension.usd import USDLoader

        beaver = Beaver3d()
        if image_url:
            task_id = beaver.generate_3d_from_image(image_url)
        else:
            task_id = beaver.generate_3d_from_text(text_prompt)

        def on_complete(task_id, status, result_path):
            loader = USDLoader()
            loader.load_usd_model(task_id=task_id)
            try:
                loader.load_texture_and_create_material(task_id=task_id)
                loader.bind_texture_to_model()
            except Exception:
                pass
            if position or scale:
                loader.transform(position=position or (0, 0, 50), scale=scale or (10, 10, 10))

        from omni.kit.async_engine import run_coroutine

        run_coroutine(beaver.monitor_task_status_async(task_id, on_complete_callback=on_complete))
        return {"status": "success", "message": "3D generation started", "task_id": task_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}
