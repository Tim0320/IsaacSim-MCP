"""Reusable runtime controls for NVIDIA IRA humans created by spawn_human.

Load with reload_script, then call these functions from execute_script while the
timeline is playing. Spawn humans with behavior="manual" for direct control;
wander, patrol, and stop routines may schedule another task afterward.
"""

import json
import sys
import types

import carb
from omni.metropolis.pipeline.agent import AgentsManager


def _runtime_agents():
    manager = AgentsManager.get_instance()
    if not manager.is_runtime_agents_collect_done():
        raise RuntimeError("Runtime humans are not ready; start the simulation first")
    return [agent for agent in manager.get_runtime_agent_instances() if hasattr(agent, "get_bh_agent")]


def _find_human(identifier):
    needle = str(identifier)
    agents = _runtime_agents()
    matches = [agent for agent in agents if needle in str(agent.prim.GetPath())]
    if len(matches) != 1:
        available = [str(agent.prim.GetPath()) for agent in agents]
        raise ValueError(f"Expected one human matching {needle!r}; matches={len(matches)}, available={available}")
    agent = matches[0]
    if agent.get_bh_agent() is None:
        raise RuntimeError(f"Behavior Agent is not ready for {agent.prim.GetPath()}")
    return agent


def _emit(action, payload):
    result = {"success": True, "action": action, **payload}
    print("NVIDIA_HUMAN_INTERACTION " + json.dumps(result, sort_keys=True))
    return result


def list_humans():
    """List collected IRA humans and their current runtime state."""
    humans = []
    for agent in _runtime_agents():
        behavior = agent.get_bh_agent()
        position = agent.get_world_position()
        humans.append(
            {
                "prim_path": str(agent.prim.GetPath()),
                "behavior_ready": behavior is not None,
                "position": list(position) if position is not None else None,
                "speed": agent.get_speed(),
                "task": agent.get_current_task_name() if behavior is not None else None,
            }
        )
    return _emit("list_humans", {"humans": humans})


def move_to(identifier, target, speed=1.0):
    """Send one human to an XYZ point on the baked NavMesh."""
    if len(target) != 3:
        raise ValueError("target must contain x, y, z")
    if float(speed) <= 0:
        raise ValueError("speed must be positive")
    agent = _find_human(identifier)
    behavior = agent.get_bh_agent()
    behavior.set_speed(float(speed))
    task_id = behavior.move_to(target=carb.Float3(*[float(value) for value in target]))
    return _emit(
        "move_to",
        {"human": str(agent.prim.GetPath()), "target": list(target), "speed": float(speed), "task_id": task_id},
    )


def look_at(identifier, target, duration=2.0):
    """Make one human look at a prim path or XYZ point."""
    agent = _find_human(identifier)
    behavior = agent.get_bh_agent()
    look_target = target if isinstance(target, str) else carb.Float3(*[float(value) for value in target])
    task_id = behavior.look_at(target=look_target, duration=float(duration))
    return _emit(
        "look_at",
        {"human": str(agent.prim.GetPath()), "target": target, "duration": float(duration), "task_id": task_id},
    )


def idle(identifier, duration=2.0):
    """Request an idle animation for one human."""
    agent = _find_human(identifier)
    task_id = agent.get_bh_agent().idle(duration=float(duration))
    return _emit("idle", {"human": str(agent.prim.GetPath()), "duration": float(duration), "task_id": task_id})


# reload_script(file_path=...) executes a persistent namespace rather than a
# normal import. Publish that fresh namespace as an importable module so later
# execute_script calls always receive the newest functions without stale .pyc.
if globals().get("__name__") != "nvidia_human_interaction":
    _published_module = types.ModuleType("nvidia_human_interaction")
    _published_module.__file__ = __file__
    _published_module.__dict__.update(globals())
    sys.modules["nvidia_human_interaction"] = _published_module

print("NVIDIA_HUMAN_INTERACTION_READY")
