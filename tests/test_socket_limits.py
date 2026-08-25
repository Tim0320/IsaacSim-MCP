"""Socket transport request and response bounds."""

import json

from isaac_sim_mcp_extension.socket_server import SocketServer, encode_bounded_response


class _Client:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def settimeout(self, _value):
        pass

    def recv(self, _size):
        return self.chunks.pop(0) if self.chunks else b""

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


def test_oversized_request_fails_closed_before_dispatch():
    dispatched = []
    server = SocketServer("localhost", 0, lambda command: dispatched.append(command))
    server.running = True
    server.max_request_bytes = 16
    client = _Client([b'{"type":"' + b"x" * 32])
    server._handle_client(client)

    response = json.loads(client.sent[0].decode("utf-8"))
    assert response["code"] == "REQUEST_TOO_LARGE"
    assert dispatched == []
    assert client.closed is True


def test_oversized_response_is_replaced_by_bounded_envelope():
    encoded = encode_bounded_response(
        {"status": "success", "data": {"pixels": "x" * 1024}},
        512,
        "cmd-1",
    )
    response = json.loads(encoded.decode("utf-8"))
    assert response["code"] == "RESPONSE_TOO_LARGE"
    assert response["command_id"] == "cmd-1"
    assert response["data"]["response_bytes"] > 512
