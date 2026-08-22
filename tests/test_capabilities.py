"""Capability contract tests for the MCP server and Isaac extension."""

from __future__ import annotations

import json
from pathlib import Path

import tomllib
from isaac_sim_mcp_extension import __version__ as extension_version
from isaac_sim_mcp_extension.handlers.capabilities import get_capabilities

from isaac_mcp import __version__ as server_version
from isaac_mcp.tools.capabilities import register_tools


class _AdapterV6:
    def __init__(self) -> None:
        self._camera_sensors = {"/World/Camera": object()}
        self._lidar_sensors = {}

    def get_simulation_state(self):
        return {"engine": "physx", "isaacsim_version": "6.0.1-rc.7"}

    def get_stage(self):
        return None


class _ExtensionManager:
    enabled = {"isaac.sim.mcp_extension", "isaacsim.core.simulation_manager"}

    def is_extension_enabled(self, name):
        return name in self.enabled

    def get_enabled_extension_id(self, name):
        return f"{name}-0.6.0" if name in self.enabled else ""

    def get_extension_dict(self, _extension_id):
        return {"package": {"version": "0.6.0"}}


def test_handler_returns_stable_runtime_capability_contract():
    registry = {"system.get_capabilities": object(), "scene.get_info": object()}

    result = get_capabilities(_AdapterV6(), registry, extension_manager=_ExtensionManager())

    assert result["status"] == "success"
    assert result["schema_version"] == "1.0"
    assert result["runtime"] == {
        "isaac_sim_version": "6.0.1-rc.7",
        "adapter": "_AdapterV6",
        "adapter_generation": 6,
        "physics_backend": "physx",
        "stage_available": False,
    }
    assert result["extension"]["command_count"] == 2
    assert result["extension"]["command_names"] == ["scene.get_info", "system.get_capabilities"]
    assert result["extensions"]["isaac.sim.mcp_extension"]["state"] == "enabled"
    assert result["extensions"]["isaacsim.ros2.bridge"]["state"] == "disabled"
    assert result["feature_flags"]["camera.rgb_pixels"]["state"] == "unsupported"
    assert result["feature_flags"]["lidar.config"]["state"] == "accepted_not_applied"
    assert result["unsupported_arguments"]["set_physics_params"]["time_step"]["state"] == "unsupported"
    assert result["sensor_warmup"]["camera"]["state"] == "per_sensor_unknown"
    assert result["sensor_warmup"]["lidar"]["state"] == "not_created"


def test_extension_manager_failure_is_reported_as_unknown_without_failing_query():
    class _UnavailableManager:
        def is_extension_enabled(self, _name):
            raise RuntimeError("not ready")

    result = get_capabilities(_AdapterV6(), {}, extension_manager=_UnavailableManager())

    assert result["status"] == "success"
    assert all(item == {"state": "unknown", "enabled": None, "version": None} for item in result["extensions"].values())


def test_v5_reports_physx_and_supported_lidar_config():
    class _AdapterV5:
        _camera_sensors = {}
        _lidar_sensors = {}

        def get_simulation_state(self):
            return {}

        def get_stage(self):
            return object()

    result = get_capabilities(_AdapterV5(), {}, extension_manager=_ExtensionManager())

    assert result["runtime"]["adapter_generation"] == 5
    assert result["runtime"]["physics_backend"] == "physx"
    assert result["feature_flags"]["lidar.config"]["state"] == "supported"
    assert "create_lidar" not in result["unsupported_arguments"]


def test_tool_adds_mcp_server_metadata_and_uses_system_command():
    class _MCP:
        def __init__(self):
            self.tools = {}

        def tool(self, name):
            def decorator(function):
                self.tools[name] = function
                return function

            return decorator

    class _Connection:
        port = 8766

        def __init__(self):
            self.commands = []

        def send_command(self, command):
            self.commands.append(command)
            return {"status": "success", "schema_version": "1.0"}

    mcp = _MCP()
    connection = _Connection()
    register_tools(mcp, lambda: connection)

    result = json.loads(mcp.tools["get_capabilities"]())

    assert connection.commands == ["system.get_capabilities"]
    assert result["data"]["mcp_server"] == {
        "name": "isaacsim-mcp-server",
        "version": server_version,
        "transport": "stdio_to_tcp",
        "live_control_port": 8766,
    }


def test_server_extension_and_manifest_versions_match():
    root = Path(__file__).parents[1]
    manifest = tomllib.loads(
        (root / "isaac.sim.mcp_extension" / "config" / "extension.toml").read_text(encoding="utf-8")
    )

    assert server_version == extension_version == manifest["package"]["version"]
