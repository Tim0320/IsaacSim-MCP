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

"""Simulation control MCP tools."""

import json
from typing import TYPE_CHECKING, Callable, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:

    @mcp.tool("play_simulation")
    def play_simulation() -> str:
        """Start the physics simulation."""
        try:
            conn = get_connection()
            result = conn.send_command("simulation.play")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("pause_simulation")
    def pause_simulation() -> str:
        """Pause the physics simulation."""
        try:
            conn = get_connection()
            result = conn.send_command("simulation.pause")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("stop_simulation")
    def stop_simulation() -> str:
        """Stop the physics simulation and reset to spawn state.

        Resets articulations and rigid bodies to their spawn pose (the state
        captured at first Play), like the Isaac UI Stop button. Call this to
        return the scene to a clean starting point before another run."""
        try:
            conn = get_connection()
            result = conn.send_command("simulation.stop")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("step_simulation")
    def step_simulation(
        num_steps: int = 1, observe_prims: Optional[List[str]] = None, observe_joints: Optional[List[str]] = None
    ) -> str:
        """Advance the simulation by exactly N physics frames on a FROZEN timeline.

        step is self-contained: it initialises physics on first call and operates
        on a paused/stopped timeline, so N is always exact and observations
        correlate to a known frame count.

        Do NOT call play_simulation before or during the debug loop; step is for
        a frozen timeline. If the timeline is already playing, step returns an
        error (a free run cannot be counted frame-by-frame). Use play_simulation
        ONLY for a final continuous run / ScriptNode-driven demo, never for
        debugging.

        Typical debug loop (no play):
          1. set_joint_positions to command the robot
          2. step_simulation with observe_prims and observe_joints
          3. get_joint_config if drives are not tracking correctly
          4. get_physics_state if objects are not behaving as expected
          5. Adjust and repeat

        Args:
            num_steps: Number of simulation frames to step.
            observe_prims: List of prim paths to observe (returns position + velocity).
            observe_joints: List of articulation prim paths to observe (returns joint positions).
        """
        try:
            conn = get_connection()
            params = {"num_steps": num_steps}
            if observe_prims is not None:
                params["observe_prims"] = observe_prims
            if observe_joints is not None:
                params["observe_joints"] = observe_joints
            result = conn.send_command("simulation.step", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("set_physics_params")
    def set_physics_params(
        gravity: Optional[List[float]] = None, time_step: Optional[float] = None, gpu_enabled: Optional[bool] = None
    ) -> str:
        """Atomically configure Isaac Sim 6 PhysX scene parameters.

        The timeline must be stopped. ``time_step`` must be within
        [0.0001, 1.0] seconds and map to an integer PhysX steps-per-second
        value (for example, 1/60 or 1/120). Isaac Sim's Stage time codes and
        minimum simulation frame-rate are synchronized to that rate. Enabling GPU physics selects GPU
        dynamics and GPU broadphase; disabling it selects MBP broadphase.
        This does not change the launcher-controlled physics GPU ordinal.
        Success includes both USD and runtime read-back; failed application is
        rolled back as one transaction.

        Args:
            gravity: Gravity vector [x, y, z].
            time_step: Physics time step in seconds.
            gpu_enabled: Enable or disable GPU dynamics and matching broadphase.
        """
        try:
            conn = get_connection()
            params = {}
            if gravity is not None:
                params["gravity"] = gravity
            if time_step is not None:
                params["time_step"] = time_step
            if gpu_enabled is not None:
                params["gpu_enabled"] = gpu_enabled
            result = conn.send_command("simulation.set_physics", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_isaac_logs")
    def get_isaac_logs(clear: bool = False, count: int = 100, since_last_play: bool = True) -> str:
        """Diagnostic tool: recent WARN/ERROR logs plus captured print() output.

        Captures carb.log_*/omni.log WARN+ERROR and stdout from execute_script /
        reload_script (tagged [PRINT]). Plain print() outside those captured
        contexts may not appear.

        Defaults are agent-friendly: non-destructive (clear=False) and scoped to
        the current run (since_last_play=True) so you see logs from what you just
        did, not stale entries from previous runs.

        Args:
            clear: If True, empty the buffer after reading. Default False.
            count: Maximum number of log entries to return.
            since_last_play: If True (default), return only entries since the last
                timeline Play. Set False for the full buffer.
        """
        try:
            conn = get_connection()
            result = conn.send_command(
                "simulation.get_logs",
                {"clear": clear, "count": count, "since_last_play": since_last_play},
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_simulation_state")
    def get_simulation_state() -> str:
        """Get the current simulation state: timeline status (playing/stopped/paused),
        simulation time, and physics dt. step_simulation does NOT require a running
        timeline — do not play just to step."""
        try:
            conn = get_connection()
            result = conn.send_command("simulation.get_state")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_physics_state")
    def get_physics_state(prim_path: str) -> str:
        """Diagnostic tool: get physics state for a prim.

        Returns rigid body status, mass, velocities, kinematic flag, and collision info.
        Velocity units: linear_velocity in m/s, angular_velocity in rad/s.
        Velocities are only non-zero once the simulation has advanced — step the
        simulation (or play) before reading them.
        Call this when:
        - Objects fall through the ground (check collision enabled)
        - Objects don't move when expected (check is_kinematic, mass)
        - Grasping fails (check collision on gripper fingers and target object)

        Args:
            prim_path: USD path to the prim to inspect.
        """
        try:
            conn = get_connection()
            result = conn.send_command("simulation.get_physics_state", {"prim_path": prim_path})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_joint_config")
    def get_joint_config(prim_path: str) -> str:
        """Diagnostic tool: get joint drive configuration for a robot articulation.

        Returns stiffness, damping, limits, target vs actual positions, and position error
        for each joint. Call this when:
        - Joint drives are not tracking targets (check position_error)
        - Joints are oscillating or unstable (check stiffness/damping ratio)
        - Joints hit limits unexpectedly (check lower_limit/upper_limit)

        Args:
            prim_path: USD path to the robot articulation root.
        """
        try:
            conn = get_connection()
            result = conn.send_command("simulation.get_joint_config", {"prim_path": prim_path})
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("execute_script")
    def execute_script(
        code: str,
        cwd: Optional[str] = None,
        timeout_s: Optional[float] = None,
        max_output_bytes: Optional[int] = None,
        allow_background: bool = False,
    ) -> str:
        """Escape hatch: execute arbitrary Python code in Isaac Sim.

        PREFER named tools over this for: reading/setting joints (set_joint_positions,
        get_joint_positions), inspecting state (get_prim_info, get_physics_state,
        get_joint_config), stepping simulation (step_simulation), and checking logs
        (get_isaac_logs).

        USE this only for a trusted operation that no named tool covers. Execution
        is policy-gated, cooperatively timed, output-bounded, cwd-restricted, and
        audited by code hash. Background scheduling is denied unless both the
        request and administrator policy explicitly opt in.

        CAUTION: touching an articulation controlled by a running ScriptNode /
        Action Graph can silently break its control path (no error is raised).
        While a graph is running, read-only diagnostics (get_prim_info,
        get_physics_state, get_joint_positions, get_isaac_logs) are safe, but
        stop_simulation before using execute_script or named write tools on the
        same articulation.

        For persistent controllers (>20 lines), write a .py file and load it with
        reload_script instead of pasting code here.

        Args:
            code: Python code to execute in the Isaac Sim context.
            cwd: Optional working directory to add to sys.path before execution.
            timeout_s: Cooperative Python deadline; capped by extension policy.
            max_output_bytes: Combined per-stream capture limit; capped by policy.
            allow_background: Request background scheduling. Default false and
                rejected unless the extension policy also enables it.
        """
        try:
            conn = get_connection()
            params = {"code": code}
            if cwd is not None:
                params["cwd"] = cwd
            if timeout_s is not None:
                params["timeout_s"] = timeout_s
            if max_output_bytes is not None:
                params["max_output_bytes"] = max_output_bytes
            params["allow_background"] = allow_background
            result = conn.send_command("simulation.execute_script", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("reload_script")
    def reload_script(
        file_path: str,
        module_name: Optional[str] = None,
        timeout_s: Optional[float] = None,
        max_output_bytes: Optional[int] = None,
    ) -> str:
        """Reload a Python controller from a file on disk.

        Two modes, chosen automatically:
        - If any Action-Graph ScriptNode references this file (inputs:scriptPath),
          those ScriptNodes are force-recompiled so your on-disk edits take effect
          on the running graph. This is how you iterate on a ScriptNode controller.
        - Otherwise the file is (re-)executed as a standalone controller, the way
          you would use execute_script for code longer than ~20 lines.

        Workflow:
          1. Write the controller as a .py file (attach via create_action_graph
             script_file=... for ScriptNode use)
          2. reload_script to load / recompile it
          3. step_simulation to debug (frozen timeline) or play for a ScriptNode demo
          4. Edit the file and reload_script again to iterate

        The file's directory is auto-added to sys.path.

        Args:
            file_path: Path to the Python file on disk.
            module_name: Optional module name to reload (e.g. 'my_controller').
            timeout_s: Cooperative Python deadline; capped by extension policy.
            max_output_bytes: Per-stream capture limit; capped by policy.
        """
        try:
            conn = get_connection()
            params = {"file_path": file_path}
            if module_name is not None:
                params["module_name"] = module_name
            if timeout_s is not None:
                params["timeout_s"] = timeout_s
            if max_output_bytes is not None:
                params["max_output_bytes"] = max_output_bytes
            result = conn.send_command("simulation.reload_script", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool("get_script_policy")
    def get_script_policy() -> str:
        """Return the current execute/reload policy without exposing script source or credentials."""
        conn = get_connection()
        return json.dumps(conn.send_command("simulation.get_script_policy"), indent=2)

    @mcp.tool("get_script_audit_log")
    def get_script_audit_log(count: int = 50) -> str:
        """Return bounded script audit metadata. Source code is represented only by SHA-256."""
        conn = get_connection()
        return json.dumps(conn.send_command("simulation.get_script_audit", {"count": count}), indent=2)
