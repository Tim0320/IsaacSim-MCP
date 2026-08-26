"""Simulation control and bounded script execution for Isaac Sim 6."""

from __future__ import annotations

import weakref
from typing import Any, Dict, List, Optional

import numpy as np

from ..base import IsaacAdapterBase
from .context import RuntimeContext


def _recompile_scriptnodes_for_file(abs_path: str) -> list:
    """Recompile Action-Graph ScriptNodes whose scriptPath matches abs_path."""
    import os

    try:
        import omni.graph.core as og

        from ...handlers.graphs import force_recompile_scriptnode
    except Exception:
        return []

    recompiled = []
    try:
        graphs = og.get_all_graphs() if hasattr(og, "get_all_graphs") else []
    except Exception:
        graphs = []
    for graph in graphs:
        try:
            for node in graph.get_nodes():
                attr = node.get_attribute("inputs:scriptPath")
                if attr is None or not attr.is_valid():
                    continue
                val = attr.get()
                if val and os.path.abspath(str(val)) == abs_path:
                    force_recompile_scriptnode(graph, node)
                    recompiled.append(node.get_prim_path())
        except Exception:
            continue
    return recompiled


class SimulationPolicyBridge:
    """Preserve facade helper overrides and cross-domain observation calls."""

    def __init__(self, adapter: IsaacAdapterBase) -> None:
        self._adapter_ref = weakref.ref(adapter)

    def _adapter(self) -> IsaacAdapterBase:
        adapter = self._adapter_ref()
        if adapter is None:
            raise RuntimeError("Isaac adapter facade is no longer available")
        return adapter

    def ensure_physics_world(self) -> None:
        self._adapter()._ensure_physics_world()

    def arm_reset_point(self) -> None:
        self._adapter()._arm_reset_point()

    def get_stage(self):
        return self._adapter().get_stage()

    def get_prim_transform(self, prim_path: str) -> Dict[str, Any]:
        return self._adapter().get_prim_transform(prim_path)

    def get_physics_state(self, prim_path: str) -> Dict[str, Any]:
        return self._adapter().get_physics_state(prim_path)

    def get_joint_positions(self, prim_path: str) -> List[float]:
        return self._adapter().get_joint_positions(prim_path)

    def get_joint_names(self, prim_path: str) -> List[str]:
        return self._adapter()._get_joint_names(prim_path)


class SimulationRuntime:
    """Own V6 timeline/physics stepping and script runtime state."""

    _exec_namespaces: Dict[str, dict] = {}

    def __init__(self, context: RuntimeContext, bridge: SimulationPolicyBridge) -> None:
        self._context = context
        self._bridge = bridge

    def play(self) -> None:
        import omni.timeline

        self._bridge.ensure_physics_world()
        timeline = omni.timeline.get_timeline_interface()
        timeline.play()
        timeline.commit()

    def pause(self) -> None:
        import omni.timeline

        omni.timeline.get_timeline_interface().pause()

    def stop(self) -> None:
        import omni.timeline

        # timeline.stop() is the Isaac UI Stop behavior and restores bodies to
        # their spawn pose. SimulationManager.reset_simulation() is absent in
        # Isaac Sim 6.0.1 and must not be reintroduced here.
        omni.timeline.get_timeline_interface().stop()

    def step(
        self,
        num_steps: int = 1,
        observe_prims: Optional[List[str]] = None,
        observe_joints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # Physics-only stepping preserves exact frame boundaries and avoids
        # re-entering Kit's asyncio loop from the MCP dispatch coroutine.
        from isaacsim.core.simulation_manager import SimulationManager

        self._bridge.ensure_physics_world()
        self._bridge.arm_reset_point()
        SimulationManager.step(steps=num_steps)

        result: Dict[str, Any] = {"stepped": num_steps}

        if observe_prims:
            from pxr import UsdPhysics

            prim_states = []
            stage = self._bridge.get_stage()
            for path in observe_prims:
                prim = stage.GetPrimAtPath(path)
                if not prim.IsValid():
                    prim_states.append({"prim_path": path, "error": "Prim not found"})
                    continue
                state: Dict[str, Any] = {"prim_path": path}
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    try:
                        view = SimulationManager.get_physics_simulation_view()
                        rb_view = view.create_rigid_body_view([path]) if view is not None else None
                        if rb_view is not None:
                            transforms = rb_view.get_transforms()
                            arr = transforms.numpy() if hasattr(transforms, "numpy") else np.asarray(transforms)
                            if arr.size >= 3:
                                flat = arr.reshape(-1)
                                state["position"] = [float(flat[0]), float(flat[1]), float(flat[2])]
                        else:
                            transform = self._bridge.get_prim_transform(path)
                            state["position"] = transform.get("position", [0, 0, 0])
                    except Exception:
                        transform = self._bridge.get_prim_transform(path)
                        state["position"] = transform.get("position", [0, 0, 0])
                else:
                    transform = self._bridge.get_prim_transform(path)
                    state["position"] = transform.get("position", [0, 0, 0])
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    try:
                        physics_state = self._bridge.get_physics_state(path)
                        state["linear_velocity"] = physics_state.get("linear_velocity", [0, 0, 0])
                        state["angular_velocity"] = physics_state.get("angular_velocity", [0, 0, 0])
                    except Exception:
                        pass
                prim_states.append(state)
            result["prim_states"] = prim_states

        if observe_joints:
            joint_states = []
            for path in observe_joints:
                try:
                    positions = self._bridge.get_joint_positions(path)
                    names = self._bridge.get_joint_names(path)
                    joints_dict = dict(zip(names, positions)) if names else {"positions": positions}
                    joint_states.append({"prim_path": path, "joints": joints_dict})
                except Exception as exc:
                    joint_states.append({"prim_path": path, "error": str(exc)})
            result["joint_states"] = joint_states

        return result

    def get_simulation_state(self) -> Dict[str, Any]:
        import omni.timeline
        from pxr import UsdPhysics

        timeline = omni.timeline.get_timeline_interface()
        if timeline.is_playing():
            timeline_state = "playing"
        elif timeline.is_stopped():
            timeline_state = "stopped"
        else:
            timeline_state = "paused"

        try:
            from isaacsim.core.simulation_manager import SimulationManager

            current_time = float(SimulationManager.get_simulation_time())
        except Exception:
            current_time = timeline.get_current_time()

        stage = self._bridge.get_stage()
        physics_dt = 1.0 / 60.0
        prims = stage.Traverse() if stage is not None else []
        for prim in prims:
            try:
                if prim.IsA(UsdPhysics.Scene):
                    time_step_attr = prim.GetAttribute("physxScene:timeStepsPerSecond")
                    if time_step_attr and time_step_attr.Get():
                        steps_per_sec = time_step_attr.Get()
                        if steps_per_sec > 0:
                            physics_dt = 1.0 / steps_per_sec
                    break
            except Exception:
                pass

        return {
            "timeline_state": timeline_state,
            "current_time": current_time,
            "physics_dt": physics_dt,
            "engine": self._context.active_backend,
            "isaacsim_version": self._context.isaac_version,
        }

    def execute_script(
        self,
        code: str,
        cwd: Optional[str] = None,
        timeout_s: float = 30.0,
        max_output_bytes: int = 65536,
    ) -> Dict[str, Any]:
        import sys
        import traceback

        import carb
        import omni
        from pxr import Gf, Sdf, Usd, UsdGeom

        from ...execution_guard import (
            BoundedTextBuffer,
            ScriptExecutionTimeout,
            ScriptOutputLimitExceeded,
            cooperative_deadline,
        )

        if cwd and cwd not in sys.path:
            sys.path.insert(0, cwd)
        local_ns = {"omni": omni, "carb": carb, "Usd": Usd, "UsdGeom": UsdGeom, "Sdf": Sdf, "Gf": Gf}

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = captured_out = BoundedTextBuffer(max_output_bytes)
        sys.stderr = captured_err = BoundedTextBuffer(max_output_bytes)
        try:
            with cooperative_deadline(timeout_s):
                self._bridge.ensure_physics_world()
                exec(code, local_ns)
            out = captured_out.getvalue()
            self._append_output_to_log(out)
            return {
                "status": "success",
                "message": "Script executed successfully",
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        except (ScriptExecutionTimeout, ScriptOutputLimitExceeded) as exc:
            return {
                "status": "timeout" if isinstance(exc, ScriptExecutionTimeout) else "error",
                "code": "SCRIPT_TIMEOUT" if isinstance(exc, ScriptExecutionTimeout) else "SCRIPT_OUTPUT_LIMIT_EXCEEDED",
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": captured_out.getvalue(),
                "stderr": captured_err.getvalue(),
                "applied": None,
            }
        except Exception as exc:
            out = captured_out.getvalue()
            self._append_output_to_log(out)
            return {
                "status": "error",
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    @staticmethod
    def _append_output_to_log(output: str) -> None:
        if not output.strip():
            return
        try:
            from ...handlers.simulation import append_log

            for line in output.splitlines():
                append_log(f"[PRINT] {line}")
        except Exception:
            pass

    def reload_script(
        self,
        file_path: str,
        module_name: Optional[str] = None,
        timeout_s: float = 30.0,
        max_output_bytes: int = 65536,
    ) -> Dict[str, Any]:
        import importlib
        import os
        import sys
        import traceback

        from ...execution_guard import (
            BoundedTextBuffer,
            ScriptExecutionTimeout,
            ScriptOutputLimitExceeded,
            cooperative_deadline,
        )

        parent_dir = os.path.dirname(os.path.abspath(file_path))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        abs_path = os.path.abspath(file_path)

        with cooperative_deadline(timeout_s):
            recompiled = _recompile_scriptnodes_for_file(abs_path)
        if recompiled:
            return {
                "status": "success",
                "message": f"Recompiled ScriptNode(s) referencing {os.path.basename(file_path)}",
                "recompiled_nodes": recompiled,
            }

        old_ns = self._exec_namespaces.get(abs_path)
        if old_ns:
            for value in old_ns.values():
                if hasattr(value, "unsubscribe"):
                    try:
                        value.unsubscribe()
                    except Exception:
                        pass

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = captured_out = BoundedTextBuffer(max_output_bytes)
        sys.stderr = captured_err = BoundedTextBuffer(max_output_bytes)
        try:
            with cooperative_deadline(timeout_s):
                if module_name:
                    if module_name in sys.modules:
                        importlib.reload(sys.modules[module_name])
                        message = f"Module '{module_name}' reloaded successfully"
                    else:
                        importlib.import_module(module_name)
                        message = f"Module '{module_name}' imported successfully"
                else:
                    if not os.path.isfile(file_path):
                        return {"status": "error", "message": f"File not found: {file_path}"}
                    with open(file_path, "r") as script_file:
                        code = script_file.read()
                    import carb
                    import omni
                    from pxr import Gf, Sdf, Usd, UsdGeom

                    local_ns = {
                        "omni": omni,
                        "carb": carb,
                        "Usd": Usd,
                        "UsdGeom": UsdGeom,
                        "Sdf": Sdf,
                        "Gf": Gf,
                        "__file__": file_path,
                    }
                    self._bridge.ensure_physics_world()
                    exec(code, local_ns)
                    self._exec_namespaces[abs_path] = local_ns
                    message = f"Script '{os.path.basename(file_path)}' executed successfully"

            out = captured_out.getvalue()
            self._append_output_to_log(out)
            return {
                "status": "success",
                "message": message,
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        except (ScriptExecutionTimeout, ScriptOutputLimitExceeded) as exc:
            return {
                "status": "timeout" if isinstance(exc, ScriptExecutionTimeout) else "error",
                "code": "SCRIPT_TIMEOUT" if isinstance(exc, ScriptExecutionTimeout) else "SCRIPT_OUTPUT_LIMIT_EXCEEDED",
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": captured_out.getvalue(),
                "stderr": captured_err.getvalue(),
                "applied": None,
            }
        except Exception as exc:
            out = captured_out.getvalue()
            self._append_output_to_log(out)
            return {
                "status": "error",
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "stdout": out,
                "stderr": captured_err.getvalue(),
            }
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
