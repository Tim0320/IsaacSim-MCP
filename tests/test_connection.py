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

"""Test the IsaacConnection module structure."""

import ast
import json
import os
import socket
import threading
import time

from isaac_mcp.connection import IsaacConnection


def test_connection_module_exists():
    path = os.path.join(os.path.dirname(__file__), "..", "isaac_mcp", "connection.py")
    assert os.path.exists(path)


def test_connection_has_required_classes_and_functions():
    path = os.path.join(os.path.dirname(__file__), "..", "isaac_mcp", "connection.py")
    with open(path) as f:
        tree = ast.parse(f.read())
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    func_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "IsaacConnection" in class_names
    assert "get_isaac_connection" in func_names
    # Check IsaacConnection has send_command method
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "IsaacConnection":
            methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
            assert "connect" in methods
            assert "disconnect" in methods
            assert "send_command" in methods


class _FakeIsaac(threading.Thread):
    """Stand-in for the Kit extension socket server.

    Accepts one connection and closes it without replying — the state a cached
    socket is left in when Isaac Sim exits — then serves every later connection
    normally, like a freshly relaunched Kit listening on the same port.

    Later connections are kept open across commands, matching the extension's
    own SocketServer._handle_client, which loops on recv() rather than closing
    after each reply. A fake that closed per command would make every call race
    an incoming FIN, which the real server never does.
    """

    daemon = True

    def __init__(self):
        super().__init__()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        self.first_connection_closed = threading.Event()
        self.commands_served = []
        self._stop = threading.Event()

    def run(self):
        served_first = False
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            if not served_first:
                # Isaac Sim goes away: drop the connection without a reply.
                served_first = True
                conn.close()
                self.first_connection_closed.set()
                continue
            with conn:
                conn.settimeout(5)
                while not self._stop.is_set():
                    try:
                        raw = conn.recv(65536)
                    except OSError:
                        break
                    if not raw:  # client hung up
                        break
                    self.commands_served.append(json.loads(raw.decode())["type"])
                    conn.sendall(json.dumps({"status": "success", "result": {"ok": True}}).encode())

    def shutdown(self):
        self._stop.set()
        self._listener.close()


def test_send_command_redials_when_isaac_restarted():
    """A cached socket whose peer has gone must be redialled, not surfaced as an error.

    Reproduces the live symptom: after Isaac Sim restarts, the long-lived MCP
    server still holds the socket from the previous Kit, and the first tool call
    fails with "Connection closed before receiving any data" while the retry
    succeeds.
    """
    server = _FakeIsaac()
    server.start()
    try:
        conn = IsaacConnection(host="127.0.0.1", port=server.port)
        assert conn.connect() is True
        assert server.first_connection_closed.wait(timeout=5)
        # Give the FIN time to land on our side of the cached socket.
        time.sleep(0.2)

        result = conn.send_command("get_simulation_state")
        assert result == {"ok": True}
        assert server.commands_served == ["get_simulation_state"]
    finally:
        server.shutdown()


def test_send_command_does_not_resend_a_command_that_was_already_delivered():
    """Recovery must never replay a command — retrying could double-execute it.

    The stale socket is detected before anything is written, so a command is
    delivered exactly once even across the reconnect.
    """
    server = _FakeIsaac()
    server.start()
    try:
        conn = IsaacConnection(host="127.0.0.1", port=server.port)
        conn.connect()
        assert server.first_connection_closed.wait(timeout=5)
        time.sleep(0.2)

        conn.send_command("create_robot")
        conn.send_command("create_robot")
        assert server.commands_served == ["create_robot", "create_robot"]
    finally:
        server.shutdown()


def test_stale_check_is_instant_on_a_healthy_socket_with_a_timeout_set():
    """The liveness probe must never wait on a healthy connection.

    send_command leaves a 300s timeout on the socket. A probe that respects that
    timeout blocks for five minutes on the next call instead of returning at
    once — observed live: a Kit swap made the following command hang rather than
    reconnect.
    """
    server = _FakeIsaac()
    server.start()
    try:
        conn = IsaacConnection(host="127.0.0.1", port=server.port)
        conn.connect()
        assert server.first_connection_closed.wait(timeout=5)
        time.sleep(0.2)
        conn.send_command("scene.get_info")  # leaves settimeout(300)
        assert conn.sock.gettimeout() == 300.0

        started = time.monotonic()
        assert conn._peer_is_gone() is False  # healthy: nothing to read
        assert time.monotonic() - started < 1.0, "liveness probe blocked on a healthy socket"
        # The probe must not disturb the timeout the caller relies on.
        assert conn.sock.gettimeout() == 300.0
    finally:
        server.shutdown()
