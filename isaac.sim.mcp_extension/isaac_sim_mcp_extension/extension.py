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

"""Isaac Sim MCP Extension — slim entry point.

Routes incoming socket commands to handler modules via a registry.
"""

from __future__ import annotations

import gc
import inspect
import traceback
from typing import Any, Dict

import carb
import omni.ext
import omni.kit.app
import omni.timeline
import omni.usd

from .adapters import get_adapter
from .handlers import register_all_handlers
from .socket_server import SocketServer


class MCPExtension(omni.ext.IExt):
    STAGE_INDEPENDENT_COMMANDS = {"system.get_capabilities"}

    def __init__(self):
        super().__init__()
        self.ext_id = None
        self._settings = carb.settings.get_settings()
        self._registry: Dict[str, Any] = {}
        self._adapter = None
        self._server: SocketServer | None = None
        self._play_sub = None

    def on_startup(self, ext_id: str) -> None:
        print("trigger  on_startup for: ", ext_id)
        self.ext_id = ext_id
        port = self._settings.get("/exts/isaac.sim.mcp/server.port") or 8766
        host = self._settings.get("/exts/isaac.sim.mcp/server.host") or "localhost"

        # Load IRA while Kit is still starting, before the first stage opens.
        # Enabling Navigation Core late can leave a valid NavMeshVolume
        # undiscovered until Isaac Sim restarts. Keep this best-effort so the
        # MCP extension still starts on installations without Actor SDG.
        if self._settings.get("/exts/isaac.sim.mcp/server.enable_humans") is not False:
            try:
                manager = omni.kit.app.get_app().get_extension_manager()
                if not manager.is_extension_enabled("isaacsim.replicator.agent.core"):
                    manager.set_extension_enabled_immediate("isaacsim.replicator.agent.core", True)
            except Exception as _e:
                print("NVIDIA IRA preload skipped:", _e)

        self._adapter = get_adapter()
        register_all_handlers(self._registry, self._adapter)
        print(f"Registered {len(self._registry)} command handlers")

        # Capture logs from extension load so early diagnostics are not missed,
        # and mark a run boundary on each timeline Play so get_isaac_logs can
        # scope to the current run.
        try:
            from .handlers.simulation import _ensure_log_listener, mark_play_boundary

            _ensure_log_listener()
            self._play_sub = (
                omni.timeline.get_timeline_interface()
                .get_timeline_event_stream()
                .create_subscription_to_pop_by_type(
                    int(omni.timeline.TimelineEventType.PLAY),
                    lambda _e: mark_play_boundary(),
                )
            )
        except Exception as _e:
            print("log listener / play-boundary setup skipped:", _e)

        self._server = SocketServer(host, port, self._execute_command)
        self._server.start()

    def on_shutdown(self) -> None:
        print("trigger  on_shutdown for: ", self.ext_id)
        if self._server:
            self._server.stop()
        self._play_sub = None
        self._registry.clear()
        gc.collect()

    # ── Command routing ────────────────────────────────────────────────────────

    def _stage_pending(self) -> bool:
        """True while Kit has started this extension but has no stage yet.

        The socket starts accepting connections roughly 8 seconds before the
        stage exists (measured on 6.0.1: connections at t+6.8s, first successful
        stage read at t+14.5s). An MCP client normally connects the moment the
        port opens, so an agent's opening commands land in that window and every
        stage-dependent handler failed with a bare
        "'NoneType' object has no attribute 'GetPrimAtPath'" — which reads as a
        broken server rather than one that is still starting.
        """
        try:
            return self._adapter.get_stage() is None
        except Exception:
            # A runtime that cannot answer at all is not "pending"; let the
            # handler run and report its own, more specific failure.
            return False

    async def _execute_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        cmd_type = command.get("type", "")
        params = command.get("params", {})
        handler = self._registry.get(cmd_type)
        if handler and cmd_type not in self.STAGE_INDEPENDENT_COMMANDS and self._stage_pending():
            return {
                "status": "error",
                "message": (
                    "Isaac Sim is still starting up — no stage yet. This clears on its own a "
                    "few seconds after the window appears; retry the same command."
                ),
            }
        if handler:
            try:
                result = handler(**params)
                if inspect.isawaitable(result):
                    result = await result
                if result and result.get("status") == "success":
                    return {"status": "success", "result": result}
                else:
                    return {
                        "status": "error",
                        "message": result.get("message", "Unknown error") if result else "No result",
                    }
            except Exception as e:
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": f"Unknown command: {cmd_type}"}
