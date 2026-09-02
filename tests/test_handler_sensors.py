# MIT License
#
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

"""Sensor handler behaviour that the integration tests cannot pin down.

The live capture test accepts either outcome (`assert resp["status"] in
("success", "error")`), so a capture that never produces a frame passes it. These
tests hold the contract instead.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zipfile

from isaac_sim_mcp_extension.handlers.sensors import capture_camera_output, capture_image, get_camera_calibration


class _Frame:
    """Minimal stand-in for the ndarray the adapter returns (numpy is stubbed offline)."""

    def __init__(self, shape, payload=None):
        self.shape = shape
        self.dtype = "uint8"
        size = 1
        for dim in shape:
            size *= dim
        self.size = size
        self._payload = payload if payload is not None else bytes((index % 251 for index in range(size)))

    def tobytes(self, order="C"):
        assert order == "C"
        return self._payload


class _TypedFrame(_Frame):
    def __init__(self, shape, dtype, payload=None):
        super().__init__(shape, payload=payload)
        self.dtype = dtype


class _Adapter:
    """Adapter without a render-request path (V5-shaped)."""

    def __init__(self, image):
        self._image = image
        self.calls = []

    def capture_camera_image(self, prim_path):
        self.calls.append(prim_path)
        return self._image


class _AdapterWithRenderRequest(_Adapter):
    """Adapter that schedules a Replicator frame (V6-shaped)."""

    def __init__(self, image):
        super().__init__(image)
        self._render_request = None  # starts None, as the real adapter does

    def _request_render_frame(self):
        self._render_request = object()
        return True


def test_capture_reports_an_error_when_no_frame_is_available():
    """An empty array means "no frame", and must not be reported as success.

    On 6.0.1 the step-only debug loop never plays the timeline, so Replicator's
    orchestrator stays STOPPED and every capture came back empty — while the
    tool answered {"status": "success", "shape": [0]}.
    """
    result = capture_image(_Adapter(_Frame((0,))), prim_path="/World/Cam")

    assert result["status"] == "error"
    assert result["code"] == "CAMERA_FRAME_NOT_READY"
    assert "/World/Cam" in result["message"]
    # The message has to say what to do about it, not just that it failed.
    assert "playing" in result["message"]
    assert "again" in result["message"]


def test_capture_reports_an_error_when_the_adapter_returns_none():
    result = capture_image(_Adapter(None), prim_path="/World/Cam")

    assert result["status"] == "error"
    assert result["code"] == "CAMERA_FRAME_NOT_READY"


def test_capture_succeeds_with_a_real_frame():
    frame = _Frame((480, 640, 3))

    result = capture_image(_Adapter(frame), prim_path="/World/Cam", return_mode="metadata")

    assert result["status"] == "success"
    assert result["return_mode"] == "metadata"
    assert result["image"]["shape"] == [480, 640, 3]
    assert result["image"]["width"] == 640
    assert result["image"]["height"] == 480
    assert result["image"]["channels"] == 3
    assert result["image"]["color_space"] == "RGB"
    assert result["image"]["dtype"] == "uint8"
    assert result["image"]["pixel_sha256"] == hashlib.sha256(frame.tobytes()).hexdigest()
    assert result["image"]["timestamp_ns"] > 0
    assert "frame" in result["image"]


def test_empty_frame_is_never_written_to_disk(tmp_path):
    """With output_path set, an empty array used to reach Image.fromarray."""
    out = tmp_path / "shot.png"

    result = capture_image(_Adapter(_Frame((0,))), prim_path="/World/Cam", output_path=str(out))

    assert result["status"] == "error"
    assert not out.exists()


def test_retry_advice_only_when_the_adapter_can_request_a_render():
    """V5 has no render-request path; telling it to "call again to collect it"
    sends the caller round a loop that never terminates."""
    v5 = capture_image(_Adapter(_Frame((0,))), prim_path="/World/Cam")
    v6 = capture_image(_AdapterWithRenderRequest(_Frame((0,))), prim_path="/World/Cam")

    assert "render has been requested" not in v5["message"]
    assert "Play the simulation" in v5["message"]
    assert "render has been requested" in v6["message"]


def test_artifact_is_default_and_writes_a_hash_verified_managed_png(tmp_path, monkeypatch):
    from isaac_sim_mcp_extension.handlers import sensors

    png = b"\x89PNG\r\n\x1a\nmanaged-test"
    frame = _Frame((2, 3, 3), payload=b"pixels" * 3)
    monkeypatch.setenv("ISAAC_MCP_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr(sensors, "_encode_png", lambda _image: png)

    result = capture_image(_Adapter(frame), prim_path="/World/Cam")

    assert result["status"] == "success"
    assert result["return_mode"] == "artifact"
    artifact = result["artifacts"][0]
    assert artifact["handle"].startswith("artifact://managed/")
    assert artifact["managed"] is True
    assert artifact["format"] == "png"
    assert artifact["mime_type"] == "image/png"
    assert artifact["sha256"] == hashlib.sha256(png).hexdigest()
    path = tmp_path / f"camera-{artifact['id']}.png"
    assert artifact["path"] == str(path)
    assert path.read_bytes() == png


def test_camera_reports_managed_artifact_size_limit_without_leaving_files(tmp_path, monkeypatch):
    from isaac_sim_mcp_extension.handlers import sensors

    monkeypatch.setenv("ISAAC_MCP_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ISAAC_MCP_ARTIFACT_MAX_FILE_BYTES", "8")
    monkeypatch.setattr(sensors, "_encode_png", lambda _image: b"more-than-eight")

    result = capture_image(_Adapter(_Frame((2, 3, 3))), prim_path="/World/Cam")

    assert result["status"] == "error"
    assert result["code"] == "ARTIFACT_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []


def test_inline_returns_decodable_png_and_enforces_size_limit(monkeypatch):
    from isaac_sim_mcp_extension.handlers import sensors

    png = b"inline-png"
    monkeypatch.setattr(sensors, "_encode_png", lambda _image: png)
    adapter = _Adapter(_Frame((2, 2, 3)))

    result = capture_image(adapter, return_mode="inline", inline_max_bytes=len(png))
    too_large = capture_image(adapter, return_mode="inline", inline_max_bytes=len(png) - 1)

    assert base64.b64decode(result["inline"]["data"]) == png
    assert result["inline"]["sha256"] == hashlib.sha256(png).hexdigest()
    assert too_large["status"] == "error"
    assert too_large["code"] == "INLINE_SIZE_LIMIT_EXCEEDED"
    assert too_large["encoded_size_bytes"] == len(png)


def test_capture_rejects_invalid_return_mode_and_ambiguous_output_path(tmp_path):
    adapter = _Adapter(_Frame((2, 2, 3)))

    invalid = capture_image(adapter, return_mode="bytes")
    ambiguous = capture_image(adapter, return_mode="metadata", output_path=str(tmp_path / "frame.png"))

    assert invalid["code"] == "INVALID_RETURN_MODE"
    assert ambiguous["code"] == "OUTPUT_PATH_REQUIRES_ARTIFACT"


def test_inline_limit_has_a_hard_upper_bound():
    result = capture_image(_Adapter(_Frame((2, 2, 3))), return_mode="inline", inline_max_bytes=4194305)

    assert result["status"] == "error"
    assert result["code"] == "INVALID_INLINE_LIMIT"


def test_camera_metadata_rejects_inconsistent_pixel_bytes():
    frame = _Frame((2, 2, 3), payload=b"too-short")

    result = capture_image(_Adapter(frame), return_mode="metadata")

    assert result["status"] == "error"
    assert "byte length mismatch" in result["message"]


def test_builtin_png_encoder_round_trips_rgb_pixels():
    from isaac_sim_mcp_extension.handlers.sensors import _encode_png

    from scripts.verify_camera_rgb_live import _decode_png

    pixels = bytes(range(18))
    png = _encode_png(_Frame((2, 3, 3), payload=pixels))

    assert _decode_png(png) == (3, 2, 3, pixels)


class _CameraOutputAdapter:
    def __init__(self, frame, info=None):
        self.frame = frame
        self.info = info or {}
        self.calls = []

    def capture_camera_output(self, prim_path, annotator):
        self.calls.append((prim_path, annotator))
        return self.frame, self.info


def test_depth_metadata_has_explicit_dtype_shape_units_and_hash():
    pixels = b"\x00\x00\x80?" * 6
    adapter = _CameraOutputAdapter(_TypedFrame((2, 3, 1), "float32", pixels))

    result = capture_camera_output(
        adapter,
        prim_path="/World/Cam",
        output_type="depth",
        return_mode="metadata",
    )

    assert result["status"] == "success"
    assert adapter.calls == [("/World/Cam", "distance_to_camera")]
    data = result["camera_output"]
    assert data["output_type"] == "depth"
    assert data["annotator"] == "distance_to_camera"
    assert data["dtype"] == "float32"
    assert data["shape"] == [2, 3, 1]
    assert data["width"] == 3
    assert data["height"] == 2
    assert data["channels"] == 1
    assert data["units"] == "meters"
    assert data["raw_sha256"] == hashlib.sha256(pixels).hexdigest()


def test_segmentation_preserves_json_safe_annotator_info():
    frame = _TypedFrame((1, 2, 1), "uint32", b"\x01\x00\x00\x00\x02\x00\x00\x00")
    adapter = _CameraOutputAdapter(frame, {"idToLabels": {1: {"class": "box"}}})

    result = capture_camera_output(
        adapter,
        output_type="semantic_segmentation",
        return_mode="metadata",
    )

    assert result["status"] == "success"
    assert result["camera_output"]["units"] == "semantic_id"
    assert result["camera_output"]["annotator_info"] == {"idToLabels": {"1": {"class": "box"}}}


def test_instance_id_segmentation_uses_prim_path_annotator():
    frame = _TypedFrame((1, 1, 1), "uint32", b"\x02\x00\x00\x00")
    adapter = _CameraOutputAdapter(frame, {"idToLabels": {2: "/World/Box"}})

    result = capture_camera_output(
        adapter,
        output_type="instance_id_segmentation",
        return_mode="metadata",
    )

    assert adapter.calls == [("/World/Camera", "instance_id_segmentation")]
    assert result["camera_output"]["units"] == "instance_prim_id"
    assert result["camera_output"]["annotator_info"] == {"idToLabels": {"2": "/World/Box"}}


def test_camera_output_artifact_is_hash_verified_npy(tmp_path, monkeypatch):
    from isaac_sim_mcp_extension.handlers import sensors

    payload = b"\x00" * (2 * 2 * 3 * 4)
    frame = _TypedFrame((2, 2, 3), "float32", payload)
    monkeypatch.setenv("ISAAC_MCP_ARTIFACT_ROOT", str(tmp_path))

    result = capture_camera_output(_CameraOutputAdapter(frame), output_type="normals")

    assert result["status"] == "success"
    artifact = result["artifacts"][0]
    assert artifact["handle"].startswith("artifact://managed/")
    assert artifact["kind"] == "camera.normals"
    assert artifact["format"] == "npy"
    assert artifact["mime_type"] == "application/x-npy"
    encoded = (tmp_path / f"camera-normals-{artifact['id']}.npy").read_bytes()
    assert encoded.startswith(b"\x93NUMPY\x01\x00")
    assert encoded.endswith(payload)
    assert artifact["sha256"] == hashlib.sha256(encoded).hexdigest()
    assert sensors._decode_npy_header(encoded)["shape"] == (2, 2, 3)
    assert sensors._decode_npy_header(encoded)["descr"] == "<f4"


def test_camera_output_inline_returns_raw_bytes_and_enforces_limit():
    payload = b"\x01\x00\x00\x00" * 4
    adapter = _CameraOutputAdapter(_TypedFrame((2, 2, 1), "uint32", payload))

    result = capture_camera_output(
        adapter,
        output_type="instance_segmentation",
        return_mode="inline",
        inline_max_bytes=len(payload),
    )
    too_large = capture_camera_output(
        adapter,
        output_type="instance_segmentation",
        return_mode="inline",
        inline_max_bytes=len(payload) - 1,
    )

    assert base64.b64decode(result["inline"]["data"]) == payload
    assert result["inline"]["dtype"] == "uint32"
    assert result["inline"]["shape"] == [2, 2, 1]
    assert too_large["code"] == "INLINE_SIZE_LIMIT_EXCEEDED"


def test_camera_output_rejects_invalid_type_and_shape():
    adapter = _CameraOutputAdapter(_TypedFrame((2, 2, 3), "float32"))

    invalid = capture_camera_output(adapter, output_type="optical_flow")
    wrong_shape = capture_camera_output(adapter, output_type="depth", return_mode="metadata")

    assert invalid["code"] == "INVALID_CAMERA_OUTPUT_TYPE"
    assert wrong_shape["status"] == "error"
    assert "shape" in wrong_shape["message"]


def test_camera_output_reports_capability_error_when_adapter_lacks_annotators():
    class _Unsupported:
        def capture_camera_output(self, _prim_path, _annotator):
            raise NotImplementedError("Camera annotators require Isaac Sim 6.x")

    result = capture_camera_output(_Unsupported(), output_type="normals")

    assert result["status"] == "unsupported"
    assert result["code"] == "CAMERA_OUTPUT_UNSUPPORTED"


def test_camera_calibration_returns_intrinsic_extrinsic_and_units():
    calibration = {
        "camera_prim": "/World/Cam",
        "resolution": {"width": 640, "height": 480},
        "projection": "perspective",
        "intrinsic_matrix": [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]],
        "camera_to_world": [[1.0, 0.0, 0.0, 0.0]] * 4,
        "world_to_camera": [[1.0, 0.0, 0.0, 0.0]] * 4,
        "depth_units": "meters",
        "stage_units": "meters_per_unit",
        "meters_per_unit": 1.0,
    }

    class _CalibrationAdapter:
        def get_camera_calibration(self, prim_path):
            assert prim_path == "/World/Cam"
            return calibration

    result = get_camera_calibration(_CalibrationAdapter(), prim_path="/World/Cam")

    assert result == {"status": "success", "message": "Camera calibration read", "calibration": calibration}


# ── V5 camera wrapper reuse ──────────────────────────────────────────────────


class _V5Camera:
    """Legacy Camera: yields frames only after initialize() plus a render tick."""

    instances = []

    def __init__(self, prim_path, resolution=None, **kwargs):
        self.prim_path = prim_path
        self.resolution = resolution
        self.init_calls = 0
        self.reads = 0
        _V5Camera.instances.append(self)

    def initialize(self):
        self.init_calls += 1

    def get_rgba(self):
        if self.init_calls == 0:
            return None
        self.reads += 1
        # The first read after initialize has had no tick to render into.
        return _Frame((0,)) if self.reads == 1 else _Frame((480, 640, 4))


def _v5_adapter(monkeypatch):
    import sys
    import types

    _V5Camera.instances = []
    mod = types.ModuleType("isaacsim.sensors.camera")
    mod.Camera = _V5Camera
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.camera", mod)

    from isaac_sim_mcp_extension.adapters.v5 import IsaacAdapterV5

    return IsaacAdapterV5()


def test_v5_initializes_each_camera_exactly_once(monkeypatch):
    """initialize() per capture left kit alive but unresponsive.

    Each call creates a render product, attaches annotators and registers three
    event subscriptions. Repeating that per request piled up work the renderer
    carried every frame: the integration suite went from 7s to not finishing in
    240s. Initialising once kept it at 2.9s.
    """
    adapter = _v5_adapter(monkeypatch)
    adapter.create_camera("/World/Cam", resolution=(640, 480))

    for _ in range(5):
        adapter.capture_camera_image("/World/Cam")

    assert len(_V5Camera.instances) == 1, "capture must not build extra Cameras"
    assert _V5Camera.instances[0].init_calls == 1, "initialize() must run once per camera, not per capture"


def test_v5_capture_reuses_the_camera_and_keeps_its_resolution(monkeypatch):
    """Rebuilding per call discarded frames and dropped the requested size."""
    adapter = _v5_adapter(monkeypatch)
    adapter.create_camera("/World/Cam", resolution=(640, 480))

    first = adapter.capture_camera_image("/World/Cam")
    second = adapter.capture_camera_image("/World/Cam")

    assert _V5Camera.instances[0].resolution == (640, 480)
    assert first.size == 0
    assert second.shape == (480, 640, 4)


# ── lidar ────────────────────────────────────────────────────────────────────


class _LidarAdapter:
    def __init__(self, points):
        self._points = points

    def get_lidar_point_cloud(self, prim_path):
        return self._points


class _LidarAdapterWithRenderRequest(_LidarAdapter):
    def __init__(self, points):
        super().__init__(points)
        self._render_request = None  # starts None, as the real adapter does

    def _request_render_frame(self):
        self._render_request = object()
        return True


class _ConfiguredLidarAdapter:
    def __init__(self):
        self.calls = []

    def create_lidar(self, prim_path, config=None, **kwargs):
        self.calls.append((prim_path, config, kwargs))
        return type("Lidar", (), {"paths": [prim_path]})()

    def set_prim_transform(self, prim_path, position=None, rotation=None):
        self.calls.append(("transform", prim_path, position, rotation))

    def get_lidar_config(self, prim_path):
        return {
            "requested_prim_path": prim_path,
            "actual_prim_path": prim_path,
            "source": "generic",
            "effective": {"horizontal_fov_deg": 120.0},
        }


def test_create_lidar_returns_effective_config_readback():
    from isaac_sim_mcp_extension.handlers.sensors import create_lidar

    adapter = _ConfiguredLidarAdapter()
    result = create_lidar(
        adapter,
        prim_path="/World/Lidar",
        position=[0.0, 0.0, 1.0],
        horizontal_fov_deg=120.0,
    )

    assert result["status"] == "success"
    assert result["prim_path"] == "/World/Lidar"
    assert result["lidar_config"]["effective"]["horizontal_fov_deg"] == 120.0
    assert result["readback"] == {"lidar_config": result["lidar_config"]}
    assert adapter.calls[0][2]["horizontal_fov_deg"] == 120.0
    assert adapter.calls[1] == ("transform", "/World/Lidar", [0.0, 0.0, 1.0], None)


def test_get_lidar_config_returns_adapter_readback():
    from isaac_sim_mcp_extension.handlers.sensors import get_lidar_config

    result = get_lidar_config(_ConfiguredLidarAdapter(), "/World/Lidar")

    assert result["status"] == "success"
    assert result["lidar_config"]["source"] == "generic"


def test_lidar_reports_an_error_when_no_frame_is_available():
    """ "Got 0 points" with status success is indistinguishable from a lidar
    aimed at empty space. RTX sensor data only flows while Replicator captures,
    so an empty read on a stopped timeline means "no frame", not "no hits"."""
    from isaac_sim_mcp_extension.handlers.sensors import get_point_cloud

    result = get_point_cloud(_LidarAdapter([]), prim_path="/World/Lidar")

    assert result["status"] == "error"
    assert result["code"] == "LIDAR_FRAME_NOT_READY"
    assert "/World/Lidar" in result["message"]
    assert result["point_count"] == 0


def test_lidar_success_reports_the_point_count():
    from isaac_sim_mcp_extension.handlers.sensors import get_point_cloud

    result = get_point_cloud(
        _LidarAdapter([(0, 0, 0)] * 7),
        prim_path="/World/Lidar",
        return_mode="metadata",
    )

    assert result["status"] == "success"
    assert result["point_count"] == 7


class _LidarFrameAdapter:
    def get_lidar_point_cloud_frame(self, prim_path):
        points = struct.pack("<ffffff", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
        ranges = struct.pack("<ff", 3.7416575, 8.774964)
        intensity = struct.pack("<ff", 0.25, 0.75)
        return {
            "fields": {
                "points": {"data": _TypedFrame((2, 3), "float32", points), "dtype": "float32", "units": "meters"},
                "range": {"data": _TypedFrame((2,), "float32", ranges), "dtype": "float32", "units": "meters"},
                "intensity": {
                    "data": _TypedFrame((2,), "float32", intensity),
                    "dtype": "float32",
                    "units": "normalized_return_strength",
                },
            },
            "coordinate_type": "cartesian",
            "coordinate_frame": "world",
            "sensor_pose": {"position": [1.0, 2.0, 3.0]},
            "sensor_timestamp_ns": 123456789,
            "sensor_frame_id": 12,
            "object_id_map": {"00000000000000000000000000000001": "/World/Box"},
            "unavailable_fields": ["semantic_id"],
        }


def test_lidar_artifact_contains_typed_npz_fields(tmp_path, monkeypatch):
    from isaac_sim_mcp_extension.handlers import sensors

    monkeypatch.setenv("ISAAC_MCP_ARTIFACT_ROOT", str(tmp_path))
    result = sensors.get_point_cloud(_LidarFrameAdapter(), prim_path="/World/Lidar")

    assert result["status"] == "success"
    assert result["point_count"] == 2
    metadata = result["lidar_point_cloud"]
    assert metadata["coordinate_frame"] == "world"
    assert metadata["sensor_pose"] == {"position": [1.0, 2.0, 3.0]}
    assert metadata["sensor_timestamp_ns"] == 123456789
    artifact = result["artifacts"][0]
    assert artifact["handle"].startswith("artifact://managed/")
    assert artifact["managed"] is True
    assert artifact["expires_at"]
    assert artifact["ttl_seconds"] == 3600
    assert artifact["format"] == "npz"
    assert artifact["point_count"] == 2
    with zipfile.ZipFile(artifact["path"]) as archive:
        assert sorted(archive.namelist()) == ["intensity.npy", "points.npy", "range.npy"]
        points_npy = archive.read("points.npy")
    assert sensors._decode_npy_header(points_npy) == {
        "descr": "<f4",
        "fortran_order": False,
        "shape": (2, 3),
    }


def test_lidar_inline_enforces_encoded_size_limit():
    from isaac_sim_mcp_extension.handlers.sensors import get_point_cloud

    success = get_point_cloud(_LidarFrameAdapter(), return_mode="inline", inline_max_bytes=4096)
    too_large = get_point_cloud(_LidarFrameAdapter(), return_mode="inline", inline_max_bytes=1)

    assert success["status"] == "success"
    assert base64.b64decode(success["inline"]["data"]).startswith(b"PK")
    assert too_large["code"] == "INLINE_SIZE_LIMIT_EXCEEDED"


def test_lidar_does_not_promise_that_retrying_will_work():
    """A single Replicator frame fills a camera but not a lidar.

    Measured on 6.0.1: with the orchestrator at STEPPED and the render request
    completed, the sensor was still empty; only play_simulation produced data.
    Telling the caller to "call again to collect it" would loop forever.
    """
    from isaac_sim_mcp_extension.handlers.sensors import get_point_cloud

    for adapter in (_LidarAdapter([]), _LidarAdapterWithRenderRequest([])):
        message = get_point_cloud(adapter, prim_path="/World/Lidar")["message"]
        assert "render has been requested" not in message
        assert "play_simulation" in message


def test_v6_lidar_decodes_the_generic_model_output_buffer(monkeypatch):
    """The annotator hands back a packed GMO struct, not points.

    Measured on 6.0.1: dtype uint8, 19,353,864 bytes, first four bytes
    79 77 71 78 ("OMGN"). Returning it raw made the handler report the byte
    length as a point count. Isaac ships parse_generic_model_output_data to
    decode it into x/y/z arrays plus numElements.
    """
    import sys
    import types

    class _Buffer:
        size = 24

        def numpy(self):
            class _A:
                size = 24

            return _A()

    class _GMO:
        numElements = 3
        x = [1.0, 2.0, 3.0]
        y = [4.0, 5.0, 6.0]
        z = [7.0, 8.0, 9.0]

    class _Sensor:
        def get_data(self, name):
            return _Buffer(), {}

    rtx = types.ModuleType("isaacsim.sensors.experimental.rtx")
    rtx.LidarSensor = lambda **kw: _Sensor()
    rtx.parse_generic_model_output_data = lambda data: _GMO()
    monkeypatch.setitem(sys.modules, "isaacsim.sensors.experimental.rtx", rtx)

    calls = []
    from tests.test_adapter_v6 import _v6_with_stub_simulation_manager

    adapter = _v6_with_stub_simulation_manager(monkeypatch, calls)
    adapter._lidar_sensors["/World/Lidar"] = _Sensor()

    pc = adapter.get_lidar_point_cloud("/World/Lidar")

    assert pc.shape == (3, 3), pc
    assert pc[0].tolist() == [1.0, 4.0, 7.0]
    assert pc[2].tolist() == [3.0, 6.0, 9.0]
