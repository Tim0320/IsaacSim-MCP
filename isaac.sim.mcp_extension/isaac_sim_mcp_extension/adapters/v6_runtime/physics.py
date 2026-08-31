"""Physics operations for the Isaac Sim 6 adapter facade."""

from __future__ import annotations

import math
import weakref
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..base import IsaacAdapterBase, PhysicsParamsApplyError
from .context import RuntimeContext
from .scene import SceneRuntime


class PhysicsPolicyBridge:
    """Preserve shared adapter policy without copying inherited behavior."""

    def __init__(self, adapter: IsaacAdapterBase) -> None:
        self._adapter_ref = weakref.ref(adapter)

    def _adapter(self) -> IsaacAdapterBase:
        adapter = self._adapter_ref()
        if adapter is None:
            raise RuntimeError("Isaac adapter facade is no longer available")
        return adapter

    def require_backend_capability(self, feature: str) -> Dict[str, Any]:
        return self._adapter().require_backend_capability(feature)

    def configure_shared_physics(self, gravity: Optional[Sequence[float]]) -> Dict[str, Any]:
        return IsaacAdapterBase.configure_physics(self._adapter(), gravity=gravity)

    def get_simulation_state(self) -> Dict[str, Any]:
        return self._adapter().get_simulation_state()

    def find_physics_scene(self, preferred_path: Optional[str] = None) -> Optional[str]:
        return self._adapter()._find_physics_scene(preferred_path)

    def apply_gravity(self, scene_path: str, gravity: Sequence[float]) -> bool:
        return self._adapter()._apply_gravity(scene_path, gravity)


class PhysicsRuntime:
    """Own V6 physics runtime bridges, authoring, read-back, and rollback."""

    def __init__(
        self,
        context: RuntimeContext,
        scene: SceneRuntime,
        bridge: PhysicsPolicyBridge,
    ) -> None:
        self._context = context
        self._scene = scene
        self._bridge = bridge

    @property
    def _engine(self) -> str:
        return self._context.active_backend

    def get_stage(self):
        return self._scene.get_stage()

    def require_backend_capability(self, feature: str) -> Dict[str, Any]:
        return self._bridge.require_backend_capability(feature)

    def get_simulation_state(self) -> Dict[str, Any]:
        return self._bridge.get_simulation_state()

    def _find_physics_scene(self, preferred_path: Optional[str] = None) -> Optional[str]:
        return self._bridge.find_physics_scene(preferred_path)

    def _apply_gravity(self, scene_path: str, gravity: Sequence[float]) -> bool:
        return self._bridge.apply_gravity(scene_path, gravity)

    def _ensure_physics_world(self) -> None:
        """Initialise SimulationManager (idempotent under both PhysX and Newton).

        Cleans stale PhysicsScene references first — the SimulationManager
        retains Python wrappers around scenes that may have been deleted via
        clear_scene, and calling setup_simulation/initialize_physics against
        them raises "Accessed invalid expired 'PhysicsScene' prim".
        """
        from isaacsim.core.simulation_manager import SimulationManager

        # Do nothing until the stage exists. setup_simulation() dereferences the
        # USD stage in native code, and Kit starts accepting MCP commands before
        # it has created one — measured on 6.0.1: the socket opens at [4.0s] and
        # the stage appears 2.86s later. A command landing in that window kills
        # the entire process:
        #
        #     [Fatal] [omni.usd] attempted member lookup on NULL TfWeakPtr<UsdStage>
        #
        # That is a native abort, not a Python exception, so it cannot be caught
        # — it has to be prevented. Reproduced 3/3 with any early execute_script,
        # including one whose body was just `print('hi')`, because this runs
        # before the submitted code does.
        # get_stage() can also raise while omni.usd is still coming up, so treat
        # "no stage" and "cannot ask yet" identically.
        try:
            if self.get_stage() is None:
                return
        except Exception:
            return
        try:
            view = SimulationManager.get_physics_simulation_view()
            if view is not None:
                is_valid = getattr(view, "is_valid", False)
                if not bool(is_valid() if callable(is_valid) else is_valid):
                    SimulationManager.invalidate_physics()
        except Exception:
            # Older or stubbed SimulationManager variants may not expose a
            # queryable view. setup_simulation/initialize_physics remains the
            # compatibility path below.
            pass
        try:
            SimulationManager._cleanup_stale_physics_scenes()
        except Exception:
            pass
        # Do not pass a dt here. setup_simulation(dt=1/60) silently rewrites a
        # time_step configured through set_physics_params every time any tool
        # calls this initializer (including execute_script and step). With no
        # dt, Isaac Sim still creates a 60 Hz default scene when none exists,
        # while preserving an authored rate on an existing scene.
        SimulationManager.setup_simulation()
        SimulationManager.initialize_physics()

    def _arm_reset_point(self) -> None:
        """Give stop_simulation something to restore to, without running the sim.

        PhysX records its restore point on a Play, and it records the state as
        of the moment play() is called. V6 advances physics with
        SimulationManager.step(), which never plays, so a run driven purely by
        step_simulation had no restore point and stop_simulation silently did
        nothing — a cube stepped down from z=2 stayed on the ground.

        Play cannot simply be called and observed: timeline transitions are
        tick-driven, and a handler may not pump kit's event loop (see step), so
        is_playing() is still False on the next line. Queueing play() and
        pause() together sidesteps that — by the time the next tick lands the
        timeline is paused, and no frame ever runs free. Measured on 6.0.1: a
        cube left at z=50.0 was still at exactly 50.0 afterwards, physics step
        count unchanged, and a subsequent stop_simulation restored it to 50.0
        from 48.73.

        Deliberately NOT the agent's job: asking the caller to play then pause
        costs a network round trip between the two, during which the sim runs
        free — measured at ~1.4s of fall — which is exactly the imprecision
        step_simulation exists to remove.

        Queueing alone is not enough: the transition is tick-driven, so it lands
        a tick *after* this returns, and a stop_simulation issued promptly finds
        no restore point and silently keeps the stepped pose. Measured on 6.0.1:
        a cube stepped from z=2.0 stayed at z=-3.32 through stop when the two
        calls were back to back, and reset correctly with any delay between
        them -- so the bug hid behind human-speed interaction and only bites the
        agent-speed debug loop this tool exists to serve. One app.update() lands
        the transition before returning, which is exactly the piece of the V5
        step this adapter otherwise avoids.

        That single pump is deliberately *not* the pumped stepping V5 does: see
        step(), which keeps SimulationManager.step for the physics so no frame
        ever runs free. Verified on 6.0.1/physx -- pump-to-arm reproduces V6's
        exact stepped result (z=-3.322, identical to no arming) while V5-style
        pumped stepping lands at z=-2.987, and the reset then works with no
        delay, 3/3. Re-check under Newton before assuming it holds there.

        Only arms while the timeline is stopped, so it re-arms once per run and
        never disturbs a genuine Play already in progress.
        """
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            if timeline.is_stopped():
                timeline.play()
                timeline.pause()
                try:
                    import omni.kit.app

                    omni.kit.app.get_app().update()
                except Exception:
                    # Pumping from inside the dispatch coroutine is the hazard
                    # step() documents. It did not reproduce here on
                    # 6.0.1/physx, but if it ever does, losing the pump costs
                    # only the reset -- degrading to the old tick-late
                    # behaviour -- and must not break stepping itself.
                    pass
        except Exception:
            # Best effort: failing to arm costs the ability to reset, but must
            # never stop the caller from stepping.
            pass

    def create_world(self, **kwargs) -> Any:
        """V6 exposes SimulationManager (a class-level singleton) where V5 returned World()."""
        from isaacsim.core.simulation_manager import SimulationManager

        return SimulationManager

    def create_simulation_context(self, **kwargs) -> Any:
        from isaacsim.core.simulation_manager import SimulationManager

        return SimulationManager

    def create_physics_scene(self, gravity: Optional[Sequence[float]] = None, scene_name: str = "PhysicsScene") -> str:
        import omni.kit.commands

        scene_path = f"/World/{scene_name}"
        # Reuse a scene that already exists rather than adding a second one:
        # two PhysicsScenes break physics state reads. See _find_physics_scene.
        existing = self._find_physics_scene(preferred_path=scene_path)
        if existing is not None:
            scene_path = existing
        else:
            omni.kit.commands.execute("CreatePrim", prim_path=scene_path, prim_type="PhysicsScene")
        if gravity is not None:
            # Without this the argument was accepted and discarded — see
            # _apply_gravity.
            self._apply_gravity(scene_path, gravity)
        return scene_path

    def configure_physics(
        self,
        gravity: Optional[Sequence[float]] = None,
        time_step: Optional[float] = None,
        gpu_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Atomically author and read back Isaac Sim 6 PhysX scene parameters."""
        if self._engine != "physx":
            if time_step is not None:
                self.require_backend_capability("physics.time_step")
            if gpu_enabled is not None:
                self.require_backend_capability("physics.gpu_enabled")
            return self._bridge.configure_shared_physics(gravity)

        state = self.get_simulation_state()
        if state.get("timeline_state") != "stopped":
            raise RuntimeError("Physics parameters require a stopped timeline")

        import carb
        from isaacsim.core.simulation_manager import PhysxScene, SimulationManager
        from pxr import PhysxSchema, UsdPhysics

        stage = self.get_stage()
        scene_paths = [prim.GetPath().pathString for prim in stage.Traverse() if prim.GetTypeName() == "PhysicsScene"]
        if len(scene_paths) > 1:
            raise RuntimeError(f"Multiple PhysicsScene prims are unsupported: {scene_paths}")

        created = not scene_paths
        scene_path = self.create_physics_scene()
        prim = stage.GetPrimAtPath(scene_path)
        had_physx_api = prim.HasAPI(PhysxSchema.PhysxSceneAPI)
        attr_names = (
            "physics:gravityDirection",
            "physics:gravityMagnitude",
            "physxScene:timeStepsPerSecond",
            "physxScene:enableGPUDynamics",
            "physxScene:broadphaseType",
            "physxScene:enableCCD",
        )

        def snapshot_attr(name: str) -> tuple[bool, Any]:
            attr = prim.GetAttribute(name)
            authored = bool(attr and attr.HasAuthoredValueOpinion())
            return authored, attr.Get() if attr else None

        snapshots = {name: snapshot_attr(name) for name in attr_names}
        stage_time_codes_before = float(stage.GetTimeCodesPerSecond())
        manager_dt_before = float(SimulationManager.get_physics_dt(scene_path))
        # The public getter logs a warning when no default exists, which is a
        # normal fresh-stage state. Snapshot the manager field directly so a
        # valid transaction does not pollute diagnostics.
        default_scene_before = getattr(SimulationManager, "_default_physics_scene_path", None)
        settings = carb.settings.get_settings()
        min_frame_rate_key = "/persistent/simulation/minFrameRate"
        min_frame_rate_before = settings.get(min_frame_rate_key)

        try:
            SimulationManager.set_default_physics_scene(scene_path)
            usd_scene = UsdPhysics.Scene(prim)
            physx_api = PhysxSchema.PhysxSceneAPI.Apply(prim)
            runtime_scene = next(
                (item for item in SimulationManager.get_physics_scenes() if str(item.path) == scene_path),
                None,
            )
            required_runtime_methods = (
                "set_steps_per_second",
                "set_enabled_gpu_dynamics",
                "set_broadphase_type",
                "get_dt",
                "get_enabled_gpu_dynamics",
                "get_broadphase_type",
            )
            # Hot reload replaces the PhysxScene class object while
            # SimulationManager can retain a valid instance of the previous
            # class. Match that registered scene by path and protocol instead
            # of isinstance; otherwise USD read-back changes but step() keeps
            # using the stale registered 60 Hz wrapper.
            if runtime_scene is None or not all(hasattr(runtime_scene, name) for name in required_runtime_methods):
                runtime_scene = PhysxScene(scene_path)

            applied: List[str] = []
            requested: Dict[str, Any] = {}
            if gravity is not None:
                if not self._apply_gravity(scene_path, gravity):
                    raise RuntimeError("Failed to author gravity on the PhysicsScene")
                applied.append("gravity")
                requested["gravity"] = [float(value) for value in gravity]
            if gpu_enabled is not None:
                runtime_scene.set_enabled_gpu_dynamics(bool(gpu_enabled))
                runtime_scene.set_broadphase_type("GPU" if gpu_enabled else "MBP")
            if time_step is not None:
                steps_per_second = int(round(1.0 / float(time_step)))
                stage.SetTimeCodesPerSecond(float(steps_per_second))
                # Match the established PhysicsContext contract. Without this
                # clamp, the next Kit update re-authors the default 60 Hz.
                settings.set(min_frame_rate_key, steps_per_second)
                runtime_scene.set_steps_per_second(steps_per_second)
                # GPU dynamics can refresh SimulationManager's registered
                # scene wrapper and reset its effective dt. Set dt last, then
                # explicitly synchronize the manager used by step().
                SimulationManager.set_physics_dt(float(time_step), physics_scene=scene_path)
                applied.append("time_step")
                requested["time_step"] = float(time_step)
            if gpu_enabled is not None:
                applied.append("gpu_enabled")
                requested["gpu_enabled"] = bool(gpu_enabled)

            # SimulationManager may materialize a separate registered wrapper
            # for the same single USD scene. Synchronize every registered
            # wrapper after authoring, then use it for runtime read-back and
            # for the clock consumed by SimulationManager.step().
            registered_scenes = list(SimulationManager.get_physics_scenes())
            for registered_scene in registered_scenes:
                if gpu_enabled is not None:
                    registered_scene.set_enabled_gpu_dynamics(bool(gpu_enabled))
                    registered_scene.set_broadphase_type("GPU" if gpu_enabled else "MBP")
                if time_step is not None:
                    registered_scene.set_steps_per_second(int(round(1.0 / float(time_step))))
            if registered_scenes:
                runtime_scene = registered_scenes[0]

            gravity_direction = usd_scene.GetGravityDirectionAttr().Get()
            gravity_magnitude = usd_scene.GetGravityMagnitudeAttr().Get()
            usd_gravity = None
            if gravity_direction is not None and gravity_magnitude is not None:
                usd_gravity = [float(gravity_direction[index]) * float(gravity_magnitude) for index in range(3)]
            usd_steps = physx_api.GetTimeStepsPerSecondAttr().Get()
            usd_readback = {
                "gravity": usd_gravity,
                "time_steps_per_second": int(usd_steps) if usd_steps is not None else None,
                "time_step": 1.0 / float(usd_steps) if usd_steps else 0.0,
                "gpu_enabled": bool(physx_api.GetEnableGPUDynamicsAttr().Get()),
                "broadphase_type": str(physx_api.GetBroadphaseTypeAttr().Get()),
                "ccd_enabled": bool(physx_api.GetEnableCCDAttr().Get()),
            }
            runtime_readback = {
                "time_step": float(runtime_scene.get_dt()),
                "manager_time_step": float(SimulationManager.get_physics_dt()),
                "default_scene_path": SimulationManager.get_default_physics_scene(),
                "stage_time_codes_per_second": float(stage.GetTimeCodesPerSecond()),
                "min_frame_rate": int(settings.get(min_frame_rate_key)),
                "gpu_enabled": bool(runtime_scene.get_enabled_gpu_dynamics()),
                "broadphase_type": str(runtime_scene.get_broadphase_type()),
            }

            if time_step is not None and not math.isclose(
                runtime_readback["time_step"], float(time_step), rel_tol=5e-6, abs_tol=1e-9
            ):
                raise RuntimeError(
                    f"time_step read-back mismatch: requested {time_step}, got {runtime_readback['time_step']}"
                )
            if time_step is not None and not math.isclose(
                runtime_readback["manager_time_step"], float(time_step), rel_tol=5e-6, abs_tol=1e-9
            ):
                raise RuntimeError(
                    "SimulationManager time_step read-back mismatch: "
                    f"requested {time_step}, got {runtime_readback['manager_time_step']}"
                )
            if time_step is not None and runtime_readback["min_frame_rate"] != int(round(1.0 / float(time_step))):
                raise RuntimeError("Physics minFrameRate read-back did not match time_steps_per_second")
            if time_step is not None and runtime_readback["stage_time_codes_per_second"] != float(
                int(round(1.0 / float(time_step)))
            ):
                raise RuntimeError("Stage timeCodesPerSecond read-back did not match the physics rate")
            if runtime_readback["default_scene_path"] != scene_path:
                raise RuntimeError("SimulationManager default PhysicsScene read-back did not match the target")
            if gpu_enabled is not None:
                expected_broadphase = "GPU" if gpu_enabled else "MBP"
                if (
                    usd_readback["gpu_enabled"] != bool(gpu_enabled)
                    or runtime_readback["gpu_enabled"] != bool(gpu_enabled)
                    or usd_readback["broadphase_type"] != expected_broadphase
                    or runtime_readback["broadphase_type"] != expected_broadphase
                ):
                    raise RuntimeError("GPU dynamics or broadphase read-back did not match the request")

            return {
                "scene_path": scene_path,
                "backend": "physx",
                "applied": applied,
                "requested": requested,
                "readback": {"usd": usd_readback, "runtime": runtime_readback},
                "side_effects": {
                    "ccd_disabled_by_gpu_dynamics": bool(gpu_enabled) if gpu_enabled is not None else False,
                    "physics_gpu_ordinal_changed": False,
                },
                "atomic": True,
            }
        except Exception as exc:
            rollback_succeeded = True
            try:
                if created:
                    stage.RemovePrim(scene_path)
                else:
                    for name, (authored, value) in snapshots.items():
                        attr = prim.GetAttribute(name)
                        if not attr:
                            continue
                        if authored:
                            attr.Set(value)
                        else:
                            attr.Clear()
                    if not had_physx_api and prim.HasAPI(PhysxSchema.PhysxSceneAPI):
                        prim.RemoveAPI(PhysxSchema.PhysxSceneAPI)
                    SimulationManager.set_physics_dt(manager_dt_before, physics_scene=scene_path)
                if min_frame_rate_before is None:
                    settings.destroy_item(min_frame_rate_key)
                else:
                    settings.set(min_frame_rate_key, min_frame_rate_before)
                if default_scene_before is None:
                    SimulationManager._default_physics_scene_path = None
                else:
                    SimulationManager.set_default_physics_scene(default_scene_before)
                stage.SetTimeCodesPerSecond(stage_time_codes_before)
            except Exception:
                rollback_succeeded = False
            raise PhysicsParamsApplyError(str(exc), rollback_succeeded=rollback_succeeded) from exc

    def configure_physics_body(
        self,
        prim_path: str,
        body_type: str,
        collider_enabled: bool,
        approximation: Optional[str] = None,
        mass_kg: Optional[float] = None,
        density_kg_m3: Optional[float] = None,
    ) -> Dict[str, Any]:
        from pxr import UsdPhysics

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")

        api_types = [UsdPhysics.RigidBodyAPI, UsdPhysics.CollisionAPI, UsdPhysics.MeshCollisionAPI, UsdPhysics.MassAPI]
        attributes = [
            "physics:rigidBodyEnabled",
            "physics:kinematicEnabled",
            "physics:collisionEnabled",
            "physics:approximation",
            "physics:mass",
            "physics:density",
        ]
        had_api = {api: prim.HasAPI(api) for api in api_types}
        snapshots = {}
        for name in attributes:
            attr = prim.GetAttribute(name)
            snapshots[name] = (
                bool(attr and attr.HasAuthoredValueOpinion()),
                attr.Get() if attr and attr.HasAuthoredValueOpinion() else None,
            )

        approximation_tokens = {
            "none": "none",
            "convex_hull": "convexHull",
            "convex_decomposition": "convexDecomposition",
            "mesh_simplification": "meshSimplification",
            "bounding_cube": "boundingCube",
            "bounding_sphere": "boundingSphere",
        }
        try:
            collision = UsdPhysics.CollisionAPI.Apply(prim) if collider_enabled else UsdPhysics.CollisionAPI(prim)
            if collider_enabled:
                collision.CreateCollisionEnabledAttr().Set(True)
            else:
                if prim.HasAPI(UsdPhysics.MeshCollisionAPI):
                    prim.RemoveAPI(UsdPhysics.MeshCollisionAPI)
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    prim.RemoveAPI(UsdPhysics.CollisionAPI)

            if body_type in {"dynamic", "kinematic"}:
                rigid = UsdPhysics.RigidBodyAPI.Apply(prim)
                rigid.CreateRigidBodyEnabledAttr().Set(True)
                rigid.CreateKinematicEnabledAttr().Set(body_type == "kinematic")
            else:
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
                if prim.HasAPI(UsdPhysics.MassAPI):
                    prim.RemoveAPI(UsdPhysics.MassAPI)

            if approximation is not None:
                if not collider_enabled:
                    raise ValueError("approximation requires collider_enabled=true")
                if prim.GetTypeName() != "Mesh":
                    raise ValueError("collider approximation can only be authored on Mesh prims")
                mesh_collision = UsdPhysics.MeshCollisionAPI.Apply(prim)
                mesh_collision.CreateApproximationAttr().Set(approximation_tokens[approximation])

            if mass_kg is not None or density_kg_m3 is not None:
                mass = UsdPhysics.MassAPI.Apply(prim)
                if mass_kg is not None:
                    mass.CreateMassAttr().Set(float(mass_kg))
                    mass.GetDensityAttr().Clear()
                else:
                    mass.CreateDensityAttr().Set(float(density_kg_m3))
                    mass.GetMassAttr().Clear()

            readback = self.get_physics_body(prim_path)
            if readback["body_type"] != body_type or readback["collider_enabled"] != collider_enabled:
                raise RuntimeError("physics body read-back did not match requested state")
            return readback
        except Exception:
            for api in api_types:
                if had_api[api] and not prim.HasAPI(api):
                    api.Apply(prim)
            for name, (authored, value) in snapshots.items():
                attr = prim.GetAttribute(name)
                if attr:
                    if authored:
                        attr.Set(value)
                    else:
                        attr.Clear()
            for api in reversed(api_types):
                if not had_api[api] and prim.HasAPI(api):
                    prim.RemoveAPI(api)
            raise

    def get_physics_body(self, prim_path: str) -> Dict[str, Any]:
        from pxr import UsdPhysics

        prim = self.get_stage().GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")
        has_rigid = prim.HasAPI(UsdPhysics.RigidBodyAPI)
        has_collision = prim.HasAPI(UsdPhysics.CollisionAPI)
        rigid = UsdPhysics.RigidBodyAPI(prim) if has_rigid else None
        collision = UsdPhysics.CollisionAPI(prim) if has_collision else None
        kinematic = bool(rigid.GetKinematicEnabledAttr().Get()) if rigid else False
        mass_api = UsdPhysics.MassAPI(prim) if prim.HasAPI(UsdPhysics.MassAPI) else None
        mesh_api = UsdPhysics.MeshCollisionAPI(prim) if prim.HasAPI(UsdPhysics.MeshCollisionAPI) else None

        def authored(attr: Any) -> Any:
            return attr.Get() if attr and attr.HasAuthoredValueOpinion() else None

        token_to_name = {
            "none": "none",
            "convexHull": "convex_hull",
            "convexDecomposition": "convex_decomposition",
            "meshSimplification": "mesh_simplification",
            "boundingCube": "bounding_cube",
            "boundingSphere": "bounding_sphere",
        }
        approximation = authored(mesh_api.GetApproximationAttr()) if mesh_api else None
        return {
            "prim_path": prim_path,
            "body_type": "kinematic" if kinematic else ("dynamic" if has_rigid else "static"),
            "has_rigid_body_api": has_rigid,
            "rigid_body_enabled": bool(rigid.GetRigidBodyEnabledAttr().Get()) if rigid else False,
            "kinematic_enabled": kinematic,
            "collider_enabled": bool(collision.GetCollisionEnabledAttr().Get()) if collision else False,
            "approximation": token_to_name.get(str(approximation), str(approximation))
            if approximation is not None
            else None,
            "mass_kg": authored(mass_api.GetMassAttr()) if mass_api else None,
            "density_kg_m3": authored(mass_api.GetDensityAttr()) if mass_api else None,
            "units": {"mass": "kg", "density": "kg/m^3"},
        }

    def create_collision_group(
        self,
        group_path: str,
        collider_paths: Sequence[str],
        filtered_group_paths: Sequence[str],
        invert_filtered_groups: bool = False,
        merge_group_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        from pxr import Sdf, UsdPhysics

        stage = self.get_stage()
        if stage.GetPrimAtPath(group_path).IsValid():
            raise ValueError(f"Prim already exists: {group_path}")
        for path in collider_paths:
            prim = stage.GetPrimAtPath(path)
            if not prim.IsValid() or not prim.HasAPI(UsdPhysics.CollisionAPI):
                raise ValueError(f"Collider prim is missing CollisionAPI: {path}")
        for path in filtered_group_paths:
            prim = stage.GetPrimAtPath(path)
            if not prim.IsValid() or not prim.IsA(UsdPhysics.CollisionGroup):
                raise ValueError(f"Filtered collision group not found: {path}")
        try:
            group = UsdPhysics.CollisionGroup.Define(stage, group_path)
            group.GetCollidersCollectionAPI().CreateIncludesRel().SetTargets(
                [Sdf.Path(path) for path in collider_paths]
            )
            group.CreateFilteredGroupsRel().SetTargets([Sdf.Path(path) for path in filtered_group_paths])
            group.CreateInvertFilteredGroupsAttr().Set(bool(invert_filtered_groups))
            if merge_group_name is not None:
                group.CreateMergeGroupNameAttr().Set(str(merge_group_name))
            return self.get_collision_group(group_path)
        except Exception:
            stage.RemovePrim(group_path)
            raise

    def get_collision_group(self, group_path: str) -> Dict[str, Any]:
        from pxr import UsdPhysics

        prim = self.get_stage().GetPrimAtPath(group_path)
        if not prim.IsValid() or not prim.IsA(UsdPhysics.CollisionGroup):
            raise ValueError(f"Collision group not found: {group_path}")
        group = UsdPhysics.CollisionGroup(prim)
        return {
            "group_path": group_path,
            "collider_paths": [str(path) for path in group.GetCollidersCollectionAPI().GetIncludesRel().GetTargets()],
            "filtered_group_paths": [str(path) for path in group.GetFilteredGroupsRel().GetTargets()],
            "invert_filtered_groups": bool(group.GetInvertFilteredGroupsAttr().Get()),
            "merge_group_name": group.GetMergeGroupNameAttr().Get() or None,
        }

    def create_physics_joint(
        self,
        joint_path: str,
        joint_type: str,
        body1: str,
        body0: Optional[str] = None,
        axis: Optional[str] = None,
        lower_limit: Optional[float] = None,
        upper_limit: Optional[float] = None,
        local_position0: Optional[Sequence[float]] = None,
        local_rotation0: Optional[Sequence[float]] = None,
        local_position1: Optional[Sequence[float]] = None,
        local_rotation1: Optional[Sequence[float]] = None,
        collision_enabled: bool = False,
    ) -> Dict[str, Any]:
        from pxr import Gf, Sdf, UsdPhysics

        stage = self.get_stage()
        if stage.GetPrimAtPath(joint_path).IsValid():
            raise ValueError(f"Prim already exists: {joint_path}")
        for label, path in (("body0", body0), ("body1", body1)):
            if path and not stage.GetPrimAtPath(path).IsValid():
                raise ValueError(f"{label} prim not found: {path}")
        schema = {
            "fixed": UsdPhysics.FixedJoint,
            "revolute": UsdPhysics.RevoluteJoint,
            "prismatic": UsdPhysics.PrismaticJoint,
        }[joint_type]
        try:
            joint = schema.Define(stage, joint_path)
            if body0:
                joint.CreateBody0Rel().SetTargets([Sdf.Path(body0)])
            joint.CreateBody1Rel().SetTargets([Sdf.Path(body1)])
            joint.CreateCollisionEnabledAttr().Set(bool(collision_enabled))
            for index, position, rotation in (
                (0, local_position0, local_rotation0),
                (1, local_position1, local_rotation1),
            ):
                if position is not None:
                    getattr(joint, f"CreateLocalPos{index}Attr")().Set(Gf.Vec3f(*position))
                if rotation is not None:
                    norm = math.sqrt(sum(float(value) ** 2 for value in rotation))
                    quat = [float(value) / norm for value in rotation]
                    getattr(joint, f"CreateLocalRot{index}Attr")().Set(Gf.Quatf(quat[0], Gf.Vec3f(*quat[1:])))
            if joint_type != "fixed":
                joint.CreateAxisAttr().Set(axis)
                if lower_limit is not None:
                    joint.CreateLowerLimitAttr().Set(float(lower_limit))
                    joint.CreateUpperLimitAttr().Set(float(upper_limit))
            return self.get_physics_joint(joint_path)
        except Exception:
            stage.RemovePrim(joint_path)
            raise

    def get_physics_joint(self, joint_path: str) -> Dict[str, Any]:
        from pxr import UsdPhysics

        prim = self.get_stage().GetPrimAtPath(joint_path)
        types = (
            ("fixed", UsdPhysics.FixedJoint),
            ("revolute", UsdPhysics.RevoluteJoint),
            ("prismatic", UsdPhysics.PrismaticJoint),
        )
        joint_type = next((name for name, schema in types if prim.IsValid() and prim.IsA(schema)), None)
        if joint_type is None:
            raise ValueError(f"Physics joint not found: {joint_path}")
        joint = dict(types)[joint_type](prim)

        def value(attr: Any) -> Any:
            item = attr.Get() if attr else None
            if item is None:
                return None
            if hasattr(item, "GetReal"):
                imaginary = item.GetImaginary()
                return [float(item.GetReal()), *[float(v) for v in imaginary]]
            if hasattr(item, "__len__") and not isinstance(item, str):
                return [float(v) for v in item]
            return item

        result = {
            "joint_path": joint_path,
            "joint_type": joint_type,
            "body0": [str(path) for path in joint.GetBody0Rel().GetTargets()],
            "body1": [str(path) for path in joint.GetBody1Rel().GetTargets()],
            "collision_enabled": bool(joint.GetCollisionEnabledAttr().Get()),
            "local_position0": value(joint.GetLocalPos0Attr()),
            "local_rotation0": value(joint.GetLocalRot0Attr()),
            "local_position1": value(joint.GetLocalPos1Attr()),
            "local_rotation1": value(joint.GetLocalRot1Attr()),
            "axis": None,
            "lower_limit": None,
            "upper_limit": None,
            "units": {"position": "m", "rotation": "quaternion_wxyz", "limit": None},
        }
        if joint_type != "fixed":
            result["axis"] = str(joint.GetAxisAttr().Get())
            result["lower_limit"] = value(joint.GetLowerLimitAttr())
            result["upper_limit"] = value(joint.GetUpperLimitAttr())
            result["units"]["limit"] = "degrees" if joint_type == "revolute" else "m"
        return result

    def get_physics_state(self, prim_path: str) -> Dict[str, Any]:
        from pxr import UsdPhysics

        stage = self.get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {prim_path}")

        result: Dict[str, Any] = {"prim_path": prim_path}
        has_rb = prim.HasAPI(UsdPhysics.RigidBodyAPI)
        result["has_rigid_body"] = has_rb
        if has_rb:
            rb = UsdPhysics.RigidBodyAPI(prim)
            kinematic_attr = rb.GetKinematicEnabledAttr()
            result["is_kinematic"] = kinematic_attr.Get() if kinematic_attr else False
        has_mass = prim.HasAPI(UsdPhysics.MassAPI)
        if has_mass:
            mass_api = UsdPhysics.MassAPI(prim)
            mass_attr = mass_api.GetMassAttr()
            result["mass"] = mass_attr.Get() if mass_attr else None
        result["collision_enabled"] = prim.HasAPI(UsdPhysics.CollisionAPI)

        if has_rb:
            lin_vel = [0.0, 0.0, 0.0]
            ang_vel = [0.0, 0.0, 0.0]
            try:
                from isaacsim.core.simulation_manager import SimulationManager

                view = SimulationManager.get_physics_simulation_view()
                if view is not None:
                    rb_view = view.create_rigid_body_view([prim_path])
                    vels = rb_view.get_velocities()
                    arr = vels.numpy() if hasattr(vels, "numpy") else np.asarray(vels)
                    if arr.size >= 6:
                        flat = arr.reshape(-1)[:6]
                        lin_vel = [float(flat[0]), float(flat[1]), float(flat[2])]
                        ang_vel = [float(flat[3]), float(flat[4]), float(flat[5])]
            except Exception:
                pass
            result["linear_velocity"] = lin_vel
            result["angular_velocity"] = ang_vel

        result["contacts"] = []
        return result
