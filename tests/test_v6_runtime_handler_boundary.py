from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "isaac.sim.mcp_extension" / "isaac_sim_mcp_extension"
RUNTIME = EXTENSION / "adapters" / "v6_runtime"
HANDLERS = EXTENSION / "handlers"


DEFERRED_DOMAINS = {
    "graphs": {
        "raw": ("omni.graph.core", "og.Controller"),
        "policy": ("TIMELINE_NOT_STOPPED", "source_sha256"),
    },
    "ros2": {
        "raw": ("omni.graph.core", "UsdGeom"),
        "policy": ("ROS2_PREREQUISITE_MISSING", "qos_profile", "domain_id"),
    },
    "replicator": {
        "raw": ("omni.replicator", "rep.orchestrator"),
        "policy": ("_JOBS", "artifact"),
    },
    "humans": {
        "raw": ("omni.anim", "omni.kit.commands"),
        "policy": ("TIMELINE_STATE_CONFLICT", "owner", "NavMesh"),
    },
}


def test_handler_owned_domains_remain_deferred_until_phase_f() -> None:
    """Do not create hollow runtimes while raw APIs and MCP policy are mixed."""
    for domain, markers in DEFERRED_DOMAINS.items():
        runtime_path = RUNTIME / f"{domain}.py"
        assert not runtime_path.exists(), f"{runtime_path.name} requires a separate Phase F boundary change"

        handler_path = HANDLERS / f"{domain}.py"
        source = handler_path.read_text(encoding="utf-8")
        assert any(marker in source for marker in markers["raw"]), f"{domain}: missing raw runtime evidence"
        assert any(marker in source for marker in markers["policy"]), f"{domain}: missing policy/ownership evidence"
        assert "v6_runtime" not in source, f"{domain}: handlers must not depend on adapter internals"
