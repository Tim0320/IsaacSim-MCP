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

"""Socket connection to the Isaac Sim extension server."""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from isaac_mcp.command_context import command_id_var, idempotency_key_var
from isaac_mcp.responses import normalize_response
from isaac_mcp.runtime_status import IsaacRuntimeUnavailableError, get_runtime_status

logger = logging.getLogger("IsaacMCPServer")

DEFAULT_PORT = 8766
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_REQUEST_BYTES = 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _positive_env_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


@dataclass
class IsaacConnection:
    """Manages a persistent TCP socket connection to the Isaac Sim extension."""

    host: str = "localhost"
    port: int = 0

    def __post_init__(self):
        if self.port == 0:
            self.port = int(os.environ.get("ISAAC_MCP_PORT", DEFAULT_PORT))

    sock: Optional[socket.socket] = field(default=None, repr=False)

    def _peer_is_gone(self) -> bool:
        """True when the cached socket's peer has already closed it.

        This connection outlives the Isaac Sim process it was dialled to: the
        MCP server keeps running across Kit restarts, so `self.sock` routinely
        refers to a Kit that has exited. Peeking without consuming distinguishes
        "nothing to read yet" (BlockingIOError — healthy idle socket) from "FIN
        received" (b"" — peer gone).

        Checked *before* sending rather than retrying after a failure, because a
        retry cannot tell whether Isaac already executed the command; replaying
        a create_robot or a delete would be worse than the error it fixes.
        """
        if self.sock is None:
            return True
        previous_timeout = self.sock.gettimeout()
        try:
            # settimeout(0) — not MSG_DONTWAIT alone. send_command leaves a 300s
            # timeout on the socket, and CPython waits for readability using that
            # timeout before issuing the syscall, so the flag alone would block
            # for five minutes on a healthy idle connection instead of answering
            # immediately. Non-blocking mode makes the probe unconditionally cheap.
            self.sock.settimeout(0)
            return self.sock.recv(1, socket.MSG_PEEK) == b""
        except (BlockingIOError, InterruptedError):
            return False
        except OSError:
            return True
        finally:
            try:
                self.sock.settimeout(previous_timeout)
            except OSError:
                pass

    def connect(self) -> bool:
        if self.sock:
            if not self._peer_is_gone():
                return True
            # Isaac Sim restarted under us — drop the dead socket and redial so
            # the caller does not eat a spurious "connection closed" error.
            logger.info("Cached Isaac connection is stale; reconnecting")
            self.disconnect()
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Isaac at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Isaac: {e}")
            self.sock = None
            return False

    def disconnect(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
            finally:
                self.sock = None

    def receive_full_response(self, sock: socket.socket, buffer_size: int = 16384) -> bytes:
        chunks = []
        timed_out = False
        timeout_seconds = _positive_env_number("ISAAC_MCP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        max_response_bytes = int(_positive_env_number("ISAAC_MCP_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES))
        sock.settimeout(timeout_seconds)
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    chunks.append(chunk)
                    if sum(len(item) for item in chunks) > max_response_bytes:
                        raise ValueError(f"Isaac response exceeds {max_response_bytes} bytes")
                    try:
                        data = b"".join(chunks)
                        json.loads(data.decode("utf-8"))
                        return data
                    except json.JSONDecodeError:
                        continue
                except socket.timeout:
                    timed_out = True
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError):
                    raise
        except socket.timeout:
            timed_out = True

        if chunks:
            data = b"".join(chunks)
            try:
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                if timed_out:
                    raise TimeoutError("Timeout waiting for complete Isaac response")
                raise Exception("Incomplete JSON response received")
        if timed_out:
            raise TimeoutError("Timeout waiting for Isaac response")
        raise Exception("No data received")

    def send_command(
        self,
        command_type: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        command_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        command_id = str(command_id or command_id_var.get() or uuid.uuid4())
        # connect() also validates a cached socket, so always route through it.
        if not self.connect():
            raise IsaacRuntimeUnavailableError(
                get_runtime_status(host=self.host, port=self.port),
                command_id=command_id,
            )

        command = {"type": command_type, "params": params or {}, "command_id": command_id}
        effective_key = idempotency_key or idempotency_key_var.get()
        if effective_key is not None:
            command["idempotency_key"] = str(effective_key)
        try:
            encoded_command = json.dumps(command).encode("utf-8")
            max_request_bytes = int(_positive_env_number("ISAAC_MCP_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES))
            if len(encoded_command) > max_request_bytes:
                return normalize_response(
                    {
                        "status": "error",
                        "code": "REQUEST_TOO_LARGE",
                        "message": f"Request exceeds {max_request_bytes} bytes",
                    },
                    command_id=command_id,
                )
            self.sock.sendall(encoded_command)
            self.sock.settimeout(_positive_env_number("ISAAC_MCP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
            response_data = self.receive_full_response(self.sock)
            response = json.loads(response_data.decode("utf-8"))

            # Schema 1.0 responses are passed through. Older extensions used
            # {status, result}; normalize those during rolling upgrades.
            if "result" in response:
                legacy_result = response.get("result") or {
                    "status": response.get("status", "error"),
                    "message": response.get("message", "Unknown error from Isaac"),
                }
                return normalize_response(legacy_result, command_id=command_id)
            return normalize_response(response, command_id=command_id)
        except (socket.timeout, TimeoutError) as e:
            self.sock = None
            return normalize_response(
                {"status": "timeout", "code": "TIMEOUT", "message": str(e) or "Timeout waiting for Isaac response"},
                command_id=command_id,
            )
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            self.sock = None
            status = get_runtime_status(host=self.host, port=self.port)
            status["command_delivery"] = "unknown"
            status["transport_error"] = str(e)[:512]
            raise IsaacRuntimeUnavailableError(status, command_id=command_id) from e
        except json.JSONDecodeError as e:
            self.sock = None
            raise Exception(f"Invalid response from Isaac: {e}")
        except Exception as e:
            self.sock = None
            raise Exception(f"Communication error with Isaac: {e}")


_isaac_connection: Optional[IsaacConnection] = None


def get_isaac_connection() -> IsaacConnection:
    """Get or create a persistent Isaac connection singleton."""
    global _isaac_connection
    if _isaac_connection is not None:
        return _isaac_connection
    _isaac_connection = IsaacConnection(host=os.getenv("ISAAC_MCP_HOST", "127.0.0.1"))
    if not _isaac_connection.connect():
        status = get_runtime_status(host=_isaac_connection.host, port=_isaac_connection.port)
        _isaac_connection = None
        raise IsaacRuntimeUnavailableError(status, command_id=command_id_var.get())
    return _isaac_connection


def reset_isaac_connection() -> None:
    """Disconnect and clear the global connection (used during shutdown)."""
    global _isaac_connection
    if _isaac_connection:
        _isaac_connection.disconnect()
        _isaac_connection = None
