import sys
import types

from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.context import RuntimeContext


def test_context_normalizes_runtime_version(monkeypatch) -> None:
    version_module = types.ModuleType("isaacsim.core.version")
    version_module.get_version = lambda: (
        "6.0.1",
        "rc.7",
        "6",
        "0",
        "1",
        "rc",
        "7",
        "release.42383.32955d8d",
    )
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", version_module)

    assert RuntimeContext.from_runtime().isaac_version == "6.0.1-rc.7"


def test_context_uses_unknown_version_when_runtime_probe_fails(monkeypatch) -> None:
    version_module = types.ModuleType("isaacsim.core.version")

    def fail() -> None:
        raise RuntimeError("not ready")

    version_module.get_version = fail
    monkeypatch.setitem(sys.modules, "isaacsim.core.version", version_module)

    assert RuntimeContext.from_runtime().isaac_version == "unknown"


def test_context_reads_backend_live_on_every_access(monkeypatch) -> None:
    engine = {"value": "physx"}
    manager = type(
        "SimulationManager",
        (),
        {"get_active_physics_engine": classmethod(lambda cls: engine["value"])},
    )
    module = types.ModuleType("isaacsim.core.simulation_manager")
    module.SimulationManager = manager
    monkeypatch.setitem(sys.modules, "isaacsim.core.simulation_manager", module)
    context = RuntimeContext(isaac_version="6.0.1")

    assert context.active_backend == "physx"
    engine["value"] = "newton"
    assert context.active_backend == "newton"


def test_context_resolves_current_stage_on_every_access(monkeypatch) -> None:
    stages = iter(["stage-a", "stage-b"])
    usd_module = types.ModuleType("omni.usd")
    usd_module.get_context = lambda: types.SimpleNamespace(get_stage=lambda: next(stages))
    omni_module = types.ModuleType("omni")
    omni_module.usd = usd_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.usd", usd_module)
    context = RuntimeContext(isaac_version="6.0.1")

    assert context.get_stage() == "stage-a"
    assert context.get_stage() == "stage-b"


def test_v6_facade_forwards_shared_runtime_facts() -> None:
    context = types.SimpleNamespace(active_backend="physx", get_stage=lambda: "stage")
    adapter = object.__new__(IsaacAdapterV6)
    adapter._runtime_context = context
    adapter._scene_runtime = types.SimpleNamespace(get_stage=context.get_stage)

    assert adapter._engine == "physx"
    assert adapter.get_stage() == "stage"
