import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime import (
    AssetPolicyBridge,
    AssetRuntime,
    LightingPolicyBridge,
    LightingRuntime,
    MaterialPolicyBridge,
    MaterialRuntime,
    SimulationPolicyBridge,
    SimulationRuntime,
)

ROOT = Path(__file__).resolve().parents[1]
V6_PATH = ROOT / "isaac.sim.mcp_extension" / "isaac_sim_mcp_extension" / "adapters" / "v6.py"


def _facade_with_runtime(attribute: str, runtime) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    setattr(adapter, attribute, runtime)
    return adapter


def test_final_facade_uses_explicit_forwarders_without_dynamic_lookup() -> None:
    source = V6_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    adapter = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "IsaacAdapterV6")
    assert "__getattr__" not in {node.name for node in adapter.body if isinstance(node, ast.FunctionDef)}
    assert "getattr(" not in source

    forwarded = {
        "create_pbr_material",
        "create_physics_material",
        "apply_material",
        "create_light",
        "modify_light",
        "clone_prim",
        "import_urdf",
        "play",
        "pause",
        "stop",
        "step",
        "get_simulation_state",
        "execute_script",
        "reload_script",
    }
    methods = {node.name: node for node in adapter.body if isinstance(node, ast.FunctionDef)}
    for name in forwarded:
        body = methods[name].body
        assert len(body) == 1 and isinstance(body[0], ast.Return), f"{name} is not an explicit thin forwarder"
        assert isinstance(body[0].value, ast.Call)


def test_facade_public_signatures_remain_explicit() -> None:
    assert str(inspect.signature(IsaacAdapterV6.step)) == (
        "(self, num_steps: 'int' = 1, observe_prims: 'Optional[List[str]]' = None, "
        "observe_joints: 'Optional[List[str]]' = None) -> 'Dict[str, Any]'"
    )
    assert str(inspect.signature(IsaacAdapterV6.reload_script)) == (
        "(self, file_path: 'str', module_name: 'Optional[str]' = None, timeout_s: 'float' = 30.0, "
        "max_output_bytes: 'int' = 65536) -> 'Dict[str, Any]'"
    )


def test_named_runtimes_have_cohesive_dependencies_and_state_ownership() -> None:
    scene = SimpleNamespace(get_stage=lambda: object())
    adapter = object.__new__(IsaacAdapterV6)
    context = SimpleNamespace(active_backend="physx", isaac_version="6.0.1")

    material = MaterialRuntime(scene, MaterialPolicyBridge(adapter))
    lighting = LightingRuntime(scene, LightingPolicyBridge(adapter))
    assets = AssetRuntime(AssetPolicyBridge(adapter))
    simulation = SimulationRuntime(context, SimulationPolicyBridge(adapter))

    assert material._scene is scene
    assert lighting._scene is scene
    assert not hasattr(assets, "_scene")
    assert simulation._context is context
    assert not any(hasattr(runtime, "_job_manager") for runtime in (material, lighting, assets, simulation))
    assert SimulationRuntime._exec_namespaces is simulation._exec_namespaces


def test_facade_forwarding_preserves_monkeypatch_targets() -> None:
    calls = []
    runtime = SimpleNamespace(
        play=lambda: calls.append("play"),
        create_pbr_material=lambda *args: ("material", args),
        import_urdf=lambda *args, **kwargs: (args, kwargs),
    )

    adapter = _facade_with_runtime("_simulation_runtime", runtime)
    adapter.play()
    adapter._material_runtime = runtime
    assert adapter.create_pbr_material("/World/M", [1, 0, 0], 0.3, 0.2)[0] == "material"
    adapter._asset_runtime = runtime
    assert adapter.import_urdf("robot.urdf", "/World/R", fix_base=True)[1] == {"fix_base": True}
    assert calls == ["play"]
