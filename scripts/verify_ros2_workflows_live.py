r"""Live Task 4.2 verifier with an out-of-process ROS 2 Clock subscriber.

Run the parent with the project venv. It launches this same file in subscriber
mode through C:\isaacsim\python.bat and the bundled Jazzy rclpy package.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

GRAPH_PATH = "/World/MCP_Task_4_2_Clock"
TOPIC = "/mcp_task_4_2/clock"
DOMAIN_ID = 42


def _subscriber(output: Path, ready: Path, timeout: float) -> int:
    import rclpy
    from rosgraph_msgs.msg import Clock

    os.environ["ROS_DOMAIN_ID"] = str(DOMAIN_ID)
    messages = []
    received_at = []
    rclpy.init()
    node = rclpy.create_node("isaacsim_mcp_task_4_2_clock_verifier")

    def callback(message: Clock) -> None:
        messages.append({"sec": int(message.clock.sec), "nanosec": int(message.clock.nanosec)})
        received_at.append(time.perf_counter())

    subscription = node.create_subscription(Clock, TOPIC, callback, 10)
    ready.write_text("ready", encoding="utf-8")
    deadline = time.perf_counter() + timeout
    try:
        while time.perf_counter() < deadline and len(messages) < 20:
            rclpy.spin_once(node, timeout_sec=0.05)
        rate_hz = None
        if len(received_at) >= 2 and received_at[-1] > received_at[0]:
            rate_hz = (len(received_at) - 1) / (received_at[-1] - received_at[0])
        result = {
            "topic": TOPIC,
            "message_type": "rosgraph_msgs/msg/Clock",
            "message_count": len(messages),
            "first_message": messages[0] if messages else None,
            "last_message": messages[-1] if messages else None,
            "observed_frequency_hz": rate_hz,
        }
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0 if len(messages) >= 5 else 2
    finally:
        node.destroy_subscription(subscription)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def _data(response):
    if response.get("status") != "success":
        raise RuntimeError(json.dumps(response, indent=2))
    return response.get("data", {})


def _ros_environment() -> dict[str, str]:
    core = Path(r"C:\isaacsim\exts\isaacsim.ros2.core")
    distro = "jazzy"
    env = os.environ.copy()
    env["ROS_DISTRO"] = distro
    env["ROS_DOMAIN_ID"] = str(DOMAIN_ID)
    env["RMW_IMPLEMENTATION"] = "rmw_fastrtps_cpp"
    env["PYTHONPATH"] = str(core / distro / "rclpy")
    env["PATH"] = os.pathsep.join([env.get("PATH", ""), str(core / distro / "lib"), str(core / "bin")])
    return env


def _parent() -> int:
    from isaac_mcp.connection import IsaacConnection

    connection = IsaacConnection(port=8766)
    temp_root = Path(tempfile.mkdtemp(prefix="isaacsim-mcp-task-4-2-"))
    output = temp_root / "subscriber-result.json"
    ready = temp_root / "subscriber-ready.txt"
    subscriber = None
    evidence = {}
    original_graphs = []
    try:
        _data(connection.send_command("simulation.stop"))
        status = _data(connection.send_command("ros2.get_status"))
        if not status.get("prerequisites_met"):
            raise RuntimeError(f"ROS 2 prerequisites are unavailable: {status.get('missing_extensions')}")
        original_graphs = [item["graph_path"] for item in _data(connection.send_command("ros2.list_workflows"))["workflows"]]
        if GRAPH_PATH in original_graphs:
            _data(connection.send_command("ros2.delete_workflow", {"graph_path": GRAPH_PATH, "preview": False}))
            original_graphs.remove(GRAPH_PATH)

        preview = _data(
            connection.send_command(
                "ros2.create_clock_publisher",
                {
                    "graph_path": GRAPH_PATH,
                    "topic_name": TOPIC,
                    "domain_id": DOMAIN_ID,
                    "qos_profile": "default",
                    "preview": True,
                },
            )
        )
        assert preview["preview"] is True and preview["node_count"] == 5
        created = connection.send_command(
            "ros2.create_clock_publisher",
            {
                "graph_path": GRAPH_PATH,
                "topic_name": TOPIC,
                "domain_id": DOMAIN_ID,
                "qos_profile": "default",
                "preview": False,
            },
        )
        created_data = _data(created)
        assert created.get("readback", {}).get("ownership", {}).get("workflow_type") == "clock"

        subscriber = subprocess.Popen(
            [
                r"C:\isaacsim\python.bat",
                str(Path(__file__).resolve()),
                "--subscriber",
                "--output",
                str(output),
                "--ready",
                str(ready),
                "--timeout",
                "10",
            ],
            env=_ros_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        ready_deadline = time.perf_counter() + 10
        while not ready.exists() and time.perf_counter() < ready_deadline:
            if subscriber.poll() is not None:
                break
            time.sleep(0.05)
        if not ready.exists():
            subscriber_output = subscriber.communicate(timeout=2)[0]
            raise RuntimeError(f"External subscriber did not become ready: {subscriber_output}")

        _data(connection.send_command("simulation.play"))
        subscriber_output, _ = subscriber.communicate(timeout=15)
        _data(connection.send_command("simulation.stop"))
        if subscriber.returncode != 0:
            raise RuntimeError(f"External subscriber failed ({subscriber.returncode}): {subscriber_output}")
        subscriber_result = json.loads(output.read_text(encoding="utf-8"))
        assert subscriber_result["message_count"] >= 5
        assert set(subscriber_result["first_message"]) == {"sec", "nanosec"}

        listed = _data(connection.send_command("ros2.list_workflows"))
        assert any(item["graph_path"] == GRAPH_PATH for item in listed["workflows"])
        deleted = connection.send_command("ros2.delete_workflow", {"graph_path": GRAPH_PATH, "preview": False})
        _data(deleted)
        assert deleted.get("readback") == {
            "graph_present": False,
            "prim_present": False,
            "ownership_marker_present": False,
        }
        restored = _data(connection.send_command("ros2.list_workflows"))
        restored_paths = [item["graph_path"] for item in restored["workflows"]]
        assert restored_paths == original_graphs
        evidence = {
            "status": "success",
            "command_count": 106,
            "extensions": status["extensions"],
            "preview": preview,
            "created": created_data,
            "subscriber": subscriber_result,
            "delete_readback": deleted["readback"],
            "workflow_list_restored": True,
            "timeline_state": "stopped",
        }
        print(json.dumps(evidence, indent=2))
        return 0
    finally:
        if subscriber is not None and subscriber.poll() is None:
            subscriber.terminate()
            try:
                subscriber.wait(timeout=3)
            except subprocess.TimeoutExpired:
                subscriber.kill()
        try:
            connection.send_command("simulation.stop")
            listed = connection.send_command("ros2.list_workflows")
            paths = [item["graph_path"] for item in listed.get("data", {}).get("workflows", [])]
            if GRAPH_PATH in paths:
                connection.send_command("ros2.delete_workflow", {"graph_path": GRAPH_PATH, "preview": False})
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscriber", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.subscriber:
        if args.output is None or args.ready is None:
            parser.error("--subscriber requires --output and --ready")
        return _subscriber(args.output, args.ready, args.timeout)
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
