"""Bounded Windows supervisor for the separately owned Isaac Sim process."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from isaac_mcp.runtime_status import STATE_SCHEMA_VERSION, default_state_file, probe_runtime_health, utc_now


@dataclass(frozen=True)
class SupervisorConfig:
    repository_root: Path
    isaac_sim_root: Path
    state_file: Path
    port: int = 8766
    physics_gpu: str | None = None
    max_restarts: int = 3
    restart_window_seconds: float = 300.0
    backoff_seconds: float = 2.0
    health_interval_seconds: float = 5.0
    health_timeout_seconds: float = 1.0
    isaac_args: tuple[str, ...] = field(default_factory=tuple)


def write_runtime_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically publish a small state document for independent MCP processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_launcher_command(config: SupervisorConfig) -> list[str]:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        raise FileNotFoundError(
            "PowerShell was not found; install PowerShell or run scripts/run_isaac_sim.ps1 directly"
        )
    script = config.repository_root / "scripts" / "run_isaac_sim.ps1"
    command = [
        pwsh,
        "-NoProfile",
        "-File",
        str(script),
        "-IsaacSimRoot",
        str(config.isaac_sim_root),
        "-Port",
        str(config.port),
    ]
    if config.physics_gpu is not None:
        command.extend(["-PhysicsGpu", config.physics_gpu])
    command.extend(config.isaac_args)
    return command


def _state(config: SupervisorConfig, state: str, **fields: Any) -> dict[str, Any]:
    value = {
        "schema_version": STATE_SCHEMA_VERSION,
        "state": state,
        "supervised": True,
        "supervisor_pid": os.getpid(),
        "port": config.port,
        "max_restarts": config.max_restarts,
        "updated_at": utc_now(),
    }
    value.update(fields)
    return value


def run_supervisor(
    config: SupervisorConfig,
    *,
    launch_process: Callable[[Sequence[str]], Any] = subprocess.Popen,
    health_probe: Callable[..., dict[str, Any]] = probe_runtime_health,
    sleep: Callable[[float], None] = time.sleep,
    write_state: Callable[[Path, dict[str, Any]], None] = write_runtime_state,
) -> int:
    """Run until a normal exit or the bounded crash-restart budget is exhausted."""
    restart_times: deque[float] = deque()
    restart_count = 0
    last_crash: dict[str, Any] | None = None
    preflight = health_probe(host="127.0.0.1", port=config.port, timeout=config.health_timeout_seconds)
    if preflight.get("responding") or preflight.get("port_open"):
        responding = bool(preflight.get("responding"))
        write_state(
            config.state_file,
            _state(
                config,
                "external_runtime_detected" if responding else "external_runtime_unresponsive",
                supervised=False,
                health=preflight,
                availability_code="ISAAC_RUNTIME_READY" if responding else "ISAAC_RUNTIME_UNAVAILABLE",
                reason=("healthy_runtime_already_listening" if responding else "runtime_port_in_use_but_unresponsive"),
            ),
        )
        return 2

    while True:
        attempt = restart_count + 1
        starting_state = "starting" if restart_count == 0 else "restarting"
        write_state(
            config.state_file,
            _state(
                config,
                starting_state,
                attempt=attempt,
                restart_count=restart_count,
                last_crash=last_crash,
                availability_code="ISAAC_RUNTIME_RECOVERING",
            ),
        )
        try:
            command = build_launcher_command(config)
            process = launch_process(command)
        except OSError as exc:
            exit_code = None
            launch_error = str(exc)[:512]
            was_ready = False
            last_health = {"responding": False, "error": launch_error, "checked_at": utc_now()}
        else:
            exit_code = None
            launch_error = None
            was_ready = False
            last_healthy_at: str | None = None
            last_health: dict[str, Any] = {"responding": False, "checked_at": utc_now()}
            while exit_code is None:
                exit_code = process.poll()
                if exit_code is not None:
                    break
                last_health = health_probe(
                    host="127.0.0.1",
                    port=config.port,
                    timeout=config.health_timeout_seconds,
                )
                responding = bool(last_health.get("responding"))
                was_ready = was_ready or responding
                if responding:
                    last_healthy_at = last_health.get("checked_at")
                live_state = "ready" if responding else ("unresponsive" if was_ready else starting_state)
                write_state(
                    config.state_file,
                    _state(
                        config,
                        live_state,
                        attempt=attempt,
                        restart_count=restart_count,
                        runtime_pid=getattr(process, "pid", None),
                        last_crash=last_crash,
                        last_healthy_at=last_healthy_at,
                        health=last_health,
                        availability_code=("ISAAC_RUNTIME_READY" if responding else "ISAAC_RUNTIME_UNAVAILABLE"),
                    ),
                )
                sleep(config.health_interval_seconds)

        if exit_code == 0:
            write_state(
                config.state_file,
                _state(
                    config,
                    "stopped",
                    reason="normal_exit",
                    exit_code=0,
                    attempt=attempt,
                    restart_count=restart_count,
                    last_crash=last_crash,
                    availability_code="ISAAC_RUNTIME_UNAVAILABLE",
                ),
            )
            return 0

        crashed_at = time.monotonic()
        last_crash = {
            "occurred_at": utc_now(),
            "exit_code": exit_code,
            "launch_error": launch_error,
            "was_ready": was_ready,
            "last_health": last_health,
        }
        while restart_times and crashed_at - restart_times[0] > config.restart_window_seconds:
            restart_times.popleft()
        if len(restart_times) >= config.max_restarts:
            write_state(
                config.state_file,
                _state(
                    config,
                    "recovery_failed",
                    attempt=attempt,
                    restart_count=restart_count,
                    last_crash=last_crash,
                    availability_code="ISAAC_RUNTIME_CRASHED",
                ),
            )
            return exit_code if isinstance(exit_code, int) and exit_code != 0 else 1

        restart_times.append(crashed_at)
        restart_count += 1
        delay = min(config.backoff_seconds * (2 ** (restart_count - 1)), 60.0)
        next_restart_epoch = time.time() + delay
        next_restart_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_restart_epoch))
        write_state(
            config.state_file,
            _state(
                config,
                "restart_backoff",
                attempt=attempt,
                restart_count=restart_count,
                next_restart_at=next_restart_at,
                last_crash=last_crash,
                availability_code="ISAAC_RUNTIME_RECOVERING",
            ),
        )
        sleep(delay)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch and restart Isaac Sim after bounded abnormal exits")
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--isaac-sim-root", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, default=default_state_file())
    parser.add_argument("--port", type=int, default=int(os.getenv("ISAAC_MCP_PORT", "8766")))
    parser.add_argument("--physics-gpu")
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--restart-window-seconds", type=float, default=300.0)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--health-interval-seconds", type=float, default=5.0)
    parser.add_argument("--health-timeout-seconds", type=float, default=1.0)
    parser.add_argument("isaac_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_restarts < 0:
        raise ValueError("--max-restarts must be >= 0")
    if (
        min(
            args.restart_window_seconds,
            args.backoff_seconds,
            args.health_interval_seconds,
            args.health_timeout_seconds,
        )
        <= 0
    ):
        raise ValueError("supervisor timing values must be > 0")
    passthrough = tuple(args.isaac_args[1:] if args.isaac_args[:1] == ["--"] else args.isaac_args)
    config = SupervisorConfig(
        repository_root=args.repository_root.resolve(),
        isaac_sim_root=args.isaac_sim_root.resolve(),
        state_file=args.state_file.expanduser().resolve(),
        port=args.port,
        physics_gpu=args.physics_gpu,
        max_restarts=args.max_restarts,
        restart_window_seconds=args.restart_window_seconds,
        backoff_seconds=args.backoff_seconds,
        health_interval_seconds=args.health_interval_seconds,
        health_timeout_seconds=args.health_timeout_seconds,
        isaac_args=passthrough,
    )
    print(f"Isaac Sim supervisor state: {config.state_file}", flush=True)
    try:
        return run_supervisor(config)
    except KeyboardInterrupt:
        write_runtime_state(
            config.state_file,
            _state(
                config,
                "supervisor_interrupted",
                supervised=False,
                availability_code="ISAAC_RUNTIME_UNAVAILABLE",
                reason="keyboard_interrupt",
            ),
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
