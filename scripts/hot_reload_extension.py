"""Reload the Isaac Sim MCP extension from disk inside a running Kit process.

Invoke through the existing ``reload_script`` named tool. This is deliberately
an in-process development helper; it does not restart Isaac Sim or alter USD.
"""

from __future__ import annotations

import gc
import importlib

import isaac_sim_mcp_extension.adapters as adapters_init
import isaac_sim_mcp_extension.adapters.base as base_mod
import isaac_sim_mcp_extension.adapters.v5 as v5_mod
import isaac_sim_mcp_extension.adapters.v6 as v6_mod
import isaac_sim_mcp_extension.adapters.v6_runtime as v6_runtime_init
import isaac_sim_mcp_extension.adapters.v6_runtime.assets as v6_assets_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.capabilities as v6_capabilities_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.context as v6_context_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.lighting as v6_lighting_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.materials as v6_materials_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.motion as v6_motion_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.physics as v6_physics_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.robots as v6_robots_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.scene as v6_scene_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.sensors as v6_sensors_mod
import isaac_sim_mcp_extension.adapters.v6_runtime.simulation as v6_simulation_mod
import isaac_sim_mcp_extension.adapters.version as version_mod
import isaac_sim_mcp_extension.controller_profiles as controller_profiles_mod
import isaac_sim_mcp_extension.handlers as handlers_init
import isaac_sim_mcp_extension.handlers.artifacts as artifacts_mod
import isaac_sim_mcp_extension.handlers.assets as assets_mod
import isaac_sim_mcp_extension.handlers.capabilities as capabilities_mod
import isaac_sim_mcp_extension.handlers.controllers as controllers_mod
import isaac_sim_mcp_extension.handlers.graphs as graphs_mod
import isaac_sim_mcp_extension.handlers.humans as humans_mod
import isaac_sim_mcp_extension.handlers.lighting as lighting_mod
import isaac_sim_mcp_extension.handlers.materials as materials_mod
import isaac_sim_mcp_extension.handlers.motion as motion_mod
import isaac_sim_mcp_extension.handlers.objects as objects_mod
import isaac_sim_mcp_extension.handlers.physics as physics_mod
import isaac_sim_mcp_extension.handlers.robots as robots_mod
import isaac_sim_mcp_extension.handlers.scene as scene_mod
import isaac_sim_mcp_extension.handlers.sensors as sensors_mod
import isaac_sim_mcp_extension.handlers.simulation as simulation_mod
from isaac_sim_mcp_extension.extension import MCPExtension

for module in (
    version_mod,
    base_mod,
    v6_context_mod,
    v6_capabilities_mod,
    v6_scene_mod,
    v6_physics_mod,
    v6_robots_mod,
    v6_motion_mod,
    v6_sensors_mod,
    v6_materials_mod,
    v6_lighting_mod,
    v6_assets_mod,
    v6_simulation_mod,
    v6_runtime_init,
    v5_mod,
    v6_mod,
    adapters_init,
    controller_profiles_mod,
):
    importlib.reload(module)
for module in (
    artifacts_mod,
    assets_mod,
    capabilities_mod,
    controllers_mod,
    graphs_mod,
    humans_mod,
    lighting_mod,
    materials_mod,
    motion_mod,
    objects_mod,
    physics_mod,
    robots_mod,
    scene_mod,
    sensors_mod,
    simulation_mod,
    handlers_init,
):
    importlib.reload(module)

from isaac_sim_mcp_extension.adapters import get_adapter  # noqa: E402
from isaac_sim_mcp_extension.handlers import register_all_handlers  # noqa: E402

for obj in gc.get_objects():
    if isinstance(obj, MCPExtension):
        old_adapter = obj.__dict__.get("_adapter")
        if old_adapter is not None:
            old_adapter.shutdown_motion()
        adapter = get_adapter()
        obj.__dict__["_adapter"] = adapter
        obj._registry.clear()
        register_all_handlers(obj._registry, adapter)
        print(f"Hot-reloaded {len(obj._registry)} handlers")
        break
else:
    raise RuntimeError("Could not find the live MCPExtension instance")
