"""Interactive controls for the generated Isaac Sim factory actors."""

import json

import omni.usd
from isaac_sim_mcp_extension.adapters.transforms import set_transform
from pxr import Sdf, UsdGeom

ROOT = "/World/Factory"


def _stage():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No live USD stage is available")
    return stage


def _require(path):
    prim = _stage().GetPrimAtPath(path)
    if not prim.IsValid():
        raise ValueError("Factory actor not found: {}".format(path))
    return prim


def _emit(action, payload):
    result = {"success": True, "action": action, **payload}
    print("FACTORY_INTERACTION_RESULT " + json.dumps(result, sort_keys=True))
    return result


def move_human(human_id, target):
    """Move a human to a workstation interaction point or an explicit (x, y)."""
    human_path = ROOT + "/Humans/Human_{:02d}".format(int(human_id))
    human = _require(human_path)
    if isinstance(target, int):
        station_path = ROOT + "/Workstations/Workstation_{:02d}_Row{}".format(
            target, 1 if target <= 3 else 2 if target <= 5 else 3 if target <= 8 else 4
        )
        station = _require(station_path)
        x = station.GetAttribute("factory:interactionX").Get()
        y = station.GetAttribute("factory:interactionY").Get()
        target_name = "Workstation_{:02d}".format(target)
    else:
        x, y = target
        target_name = "point({:.2f},{:.2f})".format(float(x), float(y))
    set_transform(UsdGeom.Xformable(human), position=(float(x), float(y), 0))
    human.GetAttribute("factory:target").Set(target_name)
    return _emit("move_human", {"human": human_path, "target": target_name, "position": [float(x), float(y), 0]})


def set_human_action(human_id, action):
    """Set a human pose: idle, wave, inspect, or point."""
    poses = {
        "idle": ((0, 0, 0), (0, 0, 0)),
        "wave": ((0, 0, 0), (0, -110, 0)),
        "inspect": ((0, 45, 0), (0, -45, 0)),
        "point": ((0, 0, 0), (0, -90, 0)),
    }
    if action not in poses:
        raise ValueError("Unknown human action '{}'; use {}".format(action, sorted(poses)))
    human_path = ROOT + "/Humans/Human_{:02d}".format(int(human_id))
    human = _require(human_path)
    left = _require(human_path + "/LeftShoulder")
    right = _require(human_path + "/RightShoulder")
    set_transform(UsdGeom.Xformable(left), rotation=poses[action][0])
    set_transform(UsdGeom.Xformable(right), rotation=poses[action][1])
    human.GetAttribute("factory:currentAction").Set(action)
    return _emit("set_human_action", {"human": human_path, "pose": action})


def set_robot_action(station_id, action):
    """Set a workstation robot pose: home, pick, place, or stop."""
    poses = {
        "home": ((0, 0, 0), (0, 0, 0)),
        "pick": ((0, 0, 20), (0, 65, 0)),
        "place": ((0, 0, -30), (0, 40, 0)),
    }
    station_id = int(station_id)
    row = 1 if station_id <= 3 else 2 if station_id <= 5 else 3 if station_id <= 8 else 4
    arm_path = ROOT + "/Workstations/Workstation_{:02d}_Row{}/InteractiveRobotArm".format(station_id, row)
    arm = _require(arm_path)
    if action == "stop":
        arm.GetAttribute("factory:state").Set("stop")
        return _emit("set_robot_action", {"robot_arm": arm_path, "state": "stop", "motion_changed": False})
    if action not in poses:
        raise ValueError("Unknown robot action '{}'; use home, pick, place, or stop".format(action))
    joint1 = _require(arm_path + "/Joint1")
    joint2 = _require(arm_path + "/Joint1/Joint2")
    set_transform(UsdGeom.Xformable(joint1), rotation=poses[action][0])
    set_transform(UsdGeom.Xformable(joint2), rotation=poses[action][1])
    arm.GetAttribute("factory:state").Set(action)
    return _emit("set_robot_action", {"robot_arm": arm_path, "state": action, "motion_changed": True})


def interact(human_id, station_id):
    """Move a human to a station, pose for inspection, and safety-stop its arm."""
    move_result = move_human(int(human_id), int(station_id))
    pose_result = set_human_action(int(human_id), "inspect")
    robot_result = set_robot_action(int(station_id), "stop")
    row = 1 if station_id <= 3 else 2 if station_id <= 5 else 3 if station_id <= 8 else 4
    station = _require(ROOT + "/Workstations/Workstation_{:02d}_Row{}".format(int(station_id), row))
    attr = station.GetAttribute("factory:lastHumanInteraction")
    if not attr.IsValid():
        attr = station.CreateAttribute("factory:lastHumanInteraction", Sdf.ValueTypeNames.String, custom=True)
    attr.Set("Human_{:02d}:inspect".format(int(human_id)))
    return _emit(
        "interact",
        {
            "human": move_result["human"],
            "station": int(station_id),
            "human_pose": pose_result["pose"],
            "robot_state": robot_result["state"],
            "safety_stop": True,
        },
    )


def list_factory_actors():
    stage = _stage()
    humans = [str(prim.GetPath()) for prim in stage.GetPrimAtPath(ROOT + "/Humans").GetChildren()]
    stations = [str(prim.GetPath()) for prim in stage.GetPrimAtPath(ROOT + "/Workstations").GetChildren()]
    return _emit(
        "list_factory_actors",
        {
            "humans": humans,
            "workstations": stations,
            "available_human_actions": ["idle", "wave", "inspect", "point"],
            "available_robot_actions": ["home", "pick", "place", "stop"],
        },
    )


print(
    "FACTORY_INTERACTION_READY "
    + json.dumps({"humans": 2, "robot_arms": 10, "module": "factory_interaction"}, sort_keys=True)
)
