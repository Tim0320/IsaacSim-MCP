"""Camera and LiDAR operations for the Isaac Sim 6 adapter facade."""

from __future__ import annotations

import weakref
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..base import IsaacAdapterBase, SensorLifecycleState
from .scene import SceneRuntime

CAMERA_ANNOTATORS = [
    "rgb",
    "distance_to_camera",
    "distance_to_image_plane",
    "semantic_segmentation",
    "instance_segmentation",
    "instance_id_segmentation",
    "normals",
    "motion_vectors",
]


class SensorPolicyBridge:
    """Reuse shared sensor teardown policy without retaining the facade."""

    def __init__(self, adapter: IsaacAdapterBase) -> None:
        self._adapter_ref = weakref.ref(adapter)

    def release_sensor(self, prim_path: str, *, evict_metadata: bool = True) -> Dict[str, Any]:
        adapter = self._adapter_ref()
        if adapter is None:
            raise RuntimeError("Isaac adapter facade is no longer available")
        return adapter.release_sensor(prim_path, evict_metadata=evict_metadata)


class SensorRuntime:
    """Own Camera/LiDAR caches, metadata, render requests, and V6 API calls."""

    def __init__(self, scene: SceneRuntime, bridge: SensorPolicyBridge) -> None:
        self._scene = scene
        self._bridge = bridge
        self._state = SensorLifecycleState()
        self._render_request = None

    @property
    def lifecycle_state(self) -> SensorLifecycleState:
        return self._state

    @property
    def _camera_sensors(self) -> Dict[str, Any]:
        return self._state.camera_sensors

    @property
    def _lidar_sensors(self) -> Dict[str, Any]:
        return self._state.lidar_sensors

    @property
    def _lidar_actual_paths(self) -> Dict[str, str]:
        return self._state.lidar_actual_paths

    @property
    def _lidar_config_metadata(self) -> Dict[str, Dict[str, Any]]:
        return self._state.lidar_config_metadata

    def get_stage(self):
        return self._scene.get_stage()

    def get_prim_transform(self, prim_path: str) -> Dict[str, Any]:
        return self._scene.get_prim_transform(prim_path)

    def release_sensor(self, prim_path: str, *, evict_metadata: bool = True) -> Dict[str, Any]:
        return self._bridge.release_sensor(prim_path, evict_metadata=evict_metadata)

    def _request_render_frame(self) -> bool:
        """Ask Replicator to render one frame, without starting the timeline.

        RTX sensor data comes from Replicator's orchestrator, which by default
        only captures while the timeline plays (/omni/replicator/captureOnPlay).
        The documented debug loop is step-only and never plays, so on 6.0.1 the
        orchestrator sat at STOPPED and every camera returned an empty frame
        forever.

        Two obvious remedies are wrong here:

          * orchestrator.run() starts the timeline. Measured on 6.0.1: from a
            stopped timeline it left playing=True, which turns the sim loose and
            destroys the frame-exact stepping step_simulation exists to provide.
          * The synchronous orchestrator.step() is refused outright by
            Replicator from inside kit — "Synchronous call to `step` can only be
            performed in a standalone workflow ... Please use the async function
            `step_async`" — which matches the rule that handlers must not pump
            kit's event loop.

        So schedule step_async and return immediately. It runs on kit's loop
        once this handler is done, captures a single frame with pause_timeline
        set, and leaves the timeline exactly as it found it. Measured: timeline
        stayed stopped, orchestrator reached STEPPED, the next capture returned
        a real image, and the kit log recorded no reentry errors.

        The frame is therefore ready on the *next* call, not this one — the
        caller is told to retry rather than being handed a blank image.
        """
        try:
            import asyncio

            import omni.replicator.core as rep

            # While Play is active, Kit's normal update loop is already
            # producing render frames. Calling step_async(pause_timeline=True)
            # here would stop that run and fire GLOBAL_EVENT_STOP, which releases
            # the long-lived CameraSensor before its first non-RGB frame arrives.
            try:
                import omni.timeline

                if omni.timeline.get_timeline_interface().is_playing():
                    return True
            except Exception:
                pass

            pending = self._render_request
            if pending is not None and not pending.done():
                return True
            self._render_request = asyncio.ensure_future(rep.orchestrator.step_async(pause_timeline=True))
            return True
        except Exception:
            return False

    def _apply_sensor_schema(self, prim_path: str) -> None:
        """Make an already-present prim acceptable to the RTX sensor wrappers.

        No-op when the prim does not exist yet — the wrapper will create it with
        the right schema itself. See create_camera for why this is needed.
        """
        try:
            prim = self.get_stage().GetPrimAtPath(prim_path)
            if prim and prim.IsValid() and "OmniSensorAPI" not in prim.GetAppliedSchemas():
                prim.ApplyAPI("OmniSensorAPI")
        except Exception:
            # Leave it to the sensor wrapper to raise a meaningful error.
            pass

    def create_camera(self, prim_path: str, resolution: Tuple[int, int] = (1280, 720), **kwargs) -> Any:
        # 6.0 RtxCamera takes a single `path: str` — the 5.x batched
        # (`prim_paths=[...], resolutions=[...]`) signature was removed.
        # Also stand up the CameraSensor runtime + RGB annotator now so kit's
        # background render ticks start filling the annotator immediately;
        # later capture_image calls read accumulated frames from the cache.
        from isaacsim.sensors.experimental.rtx import CameraSensor, RtxCamera

        # RtxCamera adopts an existing prim rather than redefining it, and it
        # does not apply OmniSensorAPI to one it did not create. Pointing
        # create_camera at a path that already holds a plain UsdGeom.Camera —
        # which imported USD scenes routinely ship — therefore failed with
        # "Prim at <path> does not have the 'OmniSensorAPI' schema", while the
        # same call on a fresh path succeeded. Reproduced on 6.0.1: fresh path
        # OK, plain Camera at the path FAIL, existing RTX camera OK.
        #
        # Apply the schema first so an existing camera prim reaches RtxCamera in
        # the same shape a newly created one would. A prim that does not exist
        # yet needs nothing: RtxCamera creates it correctly.
        if prim_path in self._camera_sensors:
            self.release_sensor(prim_path, evict_metadata=False)
        self._apply_sensor_schema(prim_path)
        camera = RtxCamera(path=prim_path)
        # CameraSensor expects (height, width). Adapter callers historically
        # pass (width, height) — translate so the cached resolution is sane.
        h, w = (resolution[1], resolution[0]) if len(resolution) == 2 else (720, 1280)
        self._camera_sensors[prim_path] = CameraSensor(
            path=prim_path,
            resolution=(h, w),
            annotators=CAMERA_ANNOTATORS,
        )
        return camera

    def capture_camera_image(self, prim_path: str) -> np.ndarray:
        # Reuse the wrapper cached by create_camera. Building a fresh
        # CameraSensor on every call re-registers the annotator with the
        # render pipeline and discards any frames produced since the prim
        # was created, so `get_data` returns None — that was the root cause
        # of the "empty data" symptom. With a long-lived wrapper, kit's
        # background update tick fills the annotator between MCP commands
        # and get_data returns the latest rendered frame.
        from isaacsim.sensors.experimental.rtx import CameraSensor

        sensor = self._camera_sensors.get(prim_path)
        if sensor is None:
            sensor = CameraSensor(path=prim_path, resolution=(720, 1280), annotators=CAMERA_ANNOTATORS)
            self._camera_sensors[prim_path] = sensor
        data, _info = sensor.get_data("rgb")
        if data is None:
            # Nothing rendered yet. Ask Replicator for a frame so the next call
            # succeeds, instead of leaving cameras permanently blank in the
            # step-only debug loop.
            self._request_render_frame()
            return np.zeros((0,), dtype=np.uint8)
        return data.numpy() if hasattr(data, "numpy") else np.asarray(data)

    def capture_camera_output(self, prim_path: str, annotator: str) -> tuple[np.ndarray, Dict[str, Any]]:
        """Return one Isaac Sim 6.x CameraSensor annotator frame.

        Annotators are attached lazily to the long-lived CameraSensor. Reusing
        the same render product is required: replacing the wrapper here would
        discard every frame accumulated between MCP calls.
        """
        from isaacsim.sensors.experimental.rtx import CameraSensor

        sensor = self._camera_sensors.get(prim_path)
        if sensor is None:
            sensor = CameraSensor(path=prim_path, resolution=(720, 1280), annotators=CAMERA_ANNOTATORS)
            self._camera_sensors[prim_path] = sensor
        elif annotator not in getattr(sensor, "_annotators", {}):
            sensor.attach_annotators(annotator)

        data, info = sensor.get_data(annotator)
        if data is None:
            self._request_render_frame()
            return np.zeros((0,), dtype=np.uint8), {}
        array = data.numpy() if hasattr(data, "numpy") else np.asarray(data)
        return array, info or {}

    def get_camera_calibration(self, prim_path: str) -> Dict[str, Any]:
        """Read a pinhole calibration contract from the USD camera and sensor."""
        from pxr import Usd, UsdGeom

        stage = self.get_stage()
        if stage is None:
            raise RuntimeError("USD stage is not available")
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.Camera):
            raise ValueError(f"Camera prim not found at {prim_path}")

        sensor = self._camera_sensors.get(prim_path)
        if sensor is None:
            raise RuntimeError(
                f"Camera resolution is unavailable for {prim_path}; create_camera must initialize it in this session"
            )
        height, width = (int(value) for value in sensor.resolution)

        camera = UsdGeom.Camera(prim)
        focal_length = float(camera.GetFocalLengthAttr().Get())
        horizontal_aperture = float(camera.GetHorizontalApertureAttr().Get())
        vertical_aperture = float(camera.GetVerticalApertureAttr().Get())
        horizontal_offset = float(camera.GetHorizontalApertureOffsetAttr().Get() or 0.0)
        vertical_offset = float(camera.GetVerticalApertureOffsetAttr().Get() or 0.0)
        projection = str(camera.GetProjectionAttr().Get())
        clipping = camera.GetClippingRangeAttr().Get()
        if horizontal_aperture <= 0 or vertical_aperture <= 0:
            raise ValueError("Camera aperture must be positive to calculate intrinsics")

        intrinsic_matrix = None
        if projection == "perspective":
            fx = width * focal_length / horizontal_aperture
            fy = height * focal_length / vertical_aperture
            cx = width * (0.5 + horizontal_offset / horizontal_aperture)
            cy = height * (0.5 + vertical_offset / vertical_aperture)
            intrinsic_matrix = [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]

        camera_to_world_matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        world_to_camera_matrix = camera_to_world_matrix.GetInverse()

        def matrix_rows(matrix):
            return [[float(matrix[row][column]) for column in range(4)] for row in range(4)]

        meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
        return {
            "camera_prim": prim_path,
            "resolution": {"width": width, "height": height},
            "projection": projection,
            "intrinsic_matrix": intrinsic_matrix,
            "intrinsic_convention": "pixels; origin top-left; x right; y down",
            "camera_to_world": matrix_rows(camera_to_world_matrix),
            "world_to_camera": matrix_rows(world_to_camera_matrix),
            "extrinsic_convention": "USD row-vector matrix; camera looks along local -Z with +Y up",
            "focal_length": focal_length,
            "horizontal_aperture": horizontal_aperture,
            "vertical_aperture": vertical_aperture,
            "horizontal_aperture_offset": horizontal_offset,
            "vertical_aperture_offset": vertical_offset,
            "optical_attribute_units": "tenths_of_stage_unit",
            "clipping_range": {"near": float(clipping[0]), "far": float(clipping[1]), "units": "stage_units"},
            "depth_units": "meters",
            "stage_units": "meters_per_unit",
            "meters_per_unit": meters_per_unit,
        }

    def create_lidar(self, prim_path: str, config: Optional[str] = None, **kwargs) -> Any:
        """Create a preset or validated generic Isaac Sim 6 RTX LiDAR."""
        from isaacsim.sensors.experimental.rtx import Lidar, LidarSensor

        from ..lidar_config import build_generic_lidar_config

        if prim_path in self._lidar_sensors:
            self.release_sensor(prim_path, evict_metadata=False)
        variant = kwargs.pop("variant", None)
        custom_names = (
            "horizontal_fov_deg",
            "vertical_fov_deg",
            "horizontal_resolution_deg",
            "vertical_resolution_deg",
            "rotation_rate_hz",
            "min_range_m",
            "max_range_m",
        )
        custom_values = {name: kwargs.pop(name, None) for name in custom_names}
        if kwargs:
            raise ValueError("Unsupported LiDAR settings: " + ", ".join(sorted(kwargs)))
        if config is not None and any(value is not None for value in custom_values.values()):
            from ..lidar_config import LidarConfigError

            raise LidarConfigError(
                "LIDAR_PRESET_CUSTOM_CONFIG_CONFLICT",
                "Named config presets cannot be combined with generic FOV, resolution, rate, or range settings",
            )
        if variant is not None and config is None:
            from ..lidar_config import LidarConfigError

            raise LidarConfigError("LIDAR_VARIANT_REQUIRES_PRESET", "variant requires a named config preset")

        if config is not None:
            lidar = Lidar.create(
                path=prim_path,
                config=config,
                variant=variant,
                aux_output_level="FULL",
            )
            source_metadata = {"source": "preset", "config": config, "variant": variant}
        else:
            attributes, effective = build_generic_lidar_config(**custom_values)
            # Replicator's functional authoring path expands a plain Python
            # list into positional Vt array constructor arguments. Isaac Sim
            # 6.0.1 then raises FloatArray.__init__(FloatArray, float, ...).
            # Supply the exact USD value types at the adapter boundary.
            try:
                from pxr import Vt

                float_arrays = (
                    "omni:sensor:Core:emitterState:s001:azimuthDeg",
                    "omni:sensor:Core:emitterState:s001:elevationDeg",
                )
                uint_arrays = (
                    "omni:sensor:Core:numRaysPerLine",
                    "omni:sensor:Core:emitterState:s001:channelId",
                    "omni:sensor:Core:emitterState:s001:fireTimeNs",
                )
                for name in float_arrays:
                    attributes[name] = Vt.FloatArray(attributes[name])
                for name in uint_arrays:
                    attributes[name] = Vt.UIntArray(attributes[name])
            except (ImportError, AttributeError):
                # Offline unit tests intentionally run without pxr. Production
                # Kit always provides Vt, and the live harness covers this path.
                pass
            lidar = Lidar(
                path=prim_path,
                # A partial valid-azimuth window does not publish a completed
                # frame reliably when the model accumulates a full rotary
                # scan. Stream each sensor tick so callers can observe the
                # configured partial FOV while the timeline is running.
                accumulate_outputs=False,
                aux_output_level="FULL",
                attributes=attributes,
            )
            source_metadata = {"source": "generic", "requested": effective}

        actual_path = str(getattr(lidar, "paths", [prim_path])[0])
        self._lidar_actual_paths[prim_path] = actual_path
        self._lidar_config_metadata[prim_path] = source_metadata
        self._lidar_sensors[prim_path] = LidarSensor(
            lidar,
            annotators=["generic-model-output", "stable-id-map"],
        )
        return lidar

    def get_lidar_config(self, prim_path: str) -> Dict[str, Any]:
        """Read back the effective Core schema values from the USD prim."""
        actual_path = self._lidar_actual_paths.get(prim_path, prim_path)
        stage = self.get_stage()
        prim = stage.GetPrimAtPath(actual_path)
        if not prim.IsValid():
            raise ValueError(f"Prim not found: {actual_path}")

        attribute_names = {
            "valid_start_azimuth_deg": "omni:sensor:Core:validStartAzimuthDeg",
            "valid_end_azimuth_deg": "omni:sensor:Core:validEndAzimuthDeg",
            "start_azimuth_offset_deg": "omni:sensor:Core:startAzimuthOffsetDeg",
            "scan_rate_base_hz": "omni:sensor:Core:scanRateBaseHz",
            "tick_rate_hz": "omni:sensor:tickRate",
            "pattern_firing_rate_hz": "omni:sensor:Core:patternFiringRateHz",
            "near_range_m": "omni:sensor:Core:nearRangeM",
            "far_range_m": "omni:sensor:Core:farRangeM",
            "number_of_channels": "omni:sensor:Core:numberOfChannels",
            "number_of_emitters": "omni:sensor:Core:numberOfEmitters",
            "elevation_deg": "omni:sensor:Core:emitterState:s001:elevationDeg",
        }
        raw: Dict[str, Any] = {}
        for name, usd_name in attribute_names.items():
            attribute = prim.GetAttribute(usd_name)
            if not attribute.IsValid():
                raw[name] = None
                continue
            value = attribute.Get()
            if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
                value = [float(item) for item in value]
            raw[name] = value

        start = float(raw["valid_start_azimuth_deg"])
        end = float(raw["valid_end_azimuth_deg"])
        scan_rate = float(raw["scan_rate_base_hz"])
        firing_rate = float(raw["pattern_firing_rate_hz"])
        horizontal_fov = end - start
        horizontal_samples = int(round(firing_rate / scan_rate)) if scan_rate > 0 else 0
        elevations = sorted(set(float(value) for value in (raw["elevation_deg"] or [])))
        vertical_fov = elevations[-1] - elevations[0] if len(elevations) > 1 else 0.0
        gaps = [b - a for a, b in zip(elevations, elevations[1:])]
        vertical_resolution = gaps[0] if gaps and all(abs(value - gaps[0]) <= 1e-6 for value in gaps) else None
        effective = {
            "horizontal_fov_deg": horizontal_fov,
            "vertical_fov_deg": vertical_fov,
            "horizontal_resolution_deg": horizontal_fov / horizontal_samples if horizontal_samples else None,
            "vertical_resolution_deg": vertical_resolution,
            "rotation_rate_hz": scan_rate,
            "min_range_m": float(raw["near_range_m"]),
            "max_range_m": float(raw["far_range_m"]),
            "horizontal_samples": horizontal_samples,
            "vertical_channels": len(elevations),
        }
        return {
            "requested_prim_path": prim_path,
            "actual_prim_path": actual_path,
            **self._lidar_config_metadata.get(prim_path, {"source": "existing"}),
            "effective": effective,
            "schema_attributes": raw,
        }

    def get_lidar_point_cloud(self, prim_path: str) -> np.ndarray:
        frame = self.get_lidar_point_cloud_frame(prim_path)
        return frame["fields"]["points"]["data"]

    def get_lidar_point_cloud_frame(self, prim_path: str) -> Dict[str, Any]:
        """Decode one V6 GenericModelOutput frame into typed point fields."""
        # 6.0 LidarSensor uses the unified "generic-model-output" annotator;
        # the 5.x `RtxSensorCpu+IsaacComputeRTXLidarPointCloud` chain is gone.
        # See `capture_camera_image` for the caching rationale.
        import math

        from isaacsim.sensors.experimental.rtx import LidarSensor, parse_generic_model_output_data

        try:
            from isaacsim.sensors.experimental.rtx import parse_object_ids, parse_stable_id_map_data
        except ImportError:
            parse_object_ids = None
            parse_stable_id_map_data = None

        sensor = self._lidar_sensors.get(prim_path)
        if sensor is None:
            from isaacsim.sensors.experimental.rtx import Lidar

            actual_path = self._lidar_actual_paths.get(prim_path, prim_path)
            lidar = Lidar(path=actual_path, aux_output_level="FULL")
            sensor = LidarSensor(lidar, annotators=["generic-model-output", "stable-id-map"])
            self._lidar_sensors[prim_path] = sensor
        data, info = sensor.get_data("generic-model-output")
        array = None
        if data is not None:
            array = data.numpy() if hasattr(data, "numpy") else np.asarray(data)
        # LidarSensor signals "nothing rendered yet" with an empty array rather
        # than None (measured on 6.0.1: shape (0,), info {}), unlike CameraSensor
        # which returns None — so testing only for None missed the empty case.
        #
        # Deliberately no _request_render_frame() here. A single Replicator frame
        # fills a camera but not a lidar: measured on 6.0.1 with the orchestrator
        # at STEPPED and the request completed, the sensor was still empty, and
        # only play_simulation produced data. Requesting one would just make the
        # caller retry forever.
        if array is None or getattr(array, "size", 0) == 0:
            return self._empty_lidar_frame()

        # The "generic-model-output" annotator returns a packed GenericModelOutput
        # struct, not points: a uint8 buffer whose first four bytes are the magic
        # 0x4E474D4F ("OMGN"). Returning it raw meant callers received bytes and
        # the handler reported len(buffer) as a point count — 19,353,864 for one
        # frame on 6.0.1, which is the byte length.
        #
        # 5.x had a point-cloud annotator that needed no decoding; 6.0 replaced it
        # with this unified buffer plus parse_generic_model_output_data, and the
        # port kept the new annotator without adopting the decode.
        gmo = parse_generic_model_output_data(data)
        count = int(getattr(gmo, "numElements", 0) or 0)
        if count <= 0:
            return self._empty_lidar_frame()

        raw_x = list(np.asarray(gmo.x)[:count])
        raw_y = list(np.asarray(gmo.y)[:count])
        raw_z = list(np.asarray(gmo.z)[:count])
        coords_value = getattr(gmo, "elementsCoordsType", "CARTESIAN")
        coords_name = str(getattr(coords_value, "name", coords_value)).upper()
        spherical = "SPHERICAL" in coords_name

        if spherical:
            azimuth = [float(value) for value in raw_x]
            elevation = [float(value) for value in raw_y]
            ranges = [float(value) for value in raw_z]
            point_x = []
            point_y = []
            point_z = []
            for azimuth_deg, elevation_deg, range_m in zip(azimuth, elevation, ranges):
                azimuth_rad = math.radians(azimuth_deg)
                elevation_rad = math.radians(elevation_deg)
                range_xy = range_m * math.cos(elevation_rad)
                point_x.append(range_xy * math.cos(azimuth_rad))
                point_y.append(range_xy * math.sin(azimuth_rad))
                point_z.append(range_m * math.sin(elevation_rad))
            points = np.stack([point_x, point_y, point_z], axis=-1).astype(np.float32)
        else:
            point_x = [float(value) for value in raw_x]
            point_y = [float(value) for value in raw_y]
            point_z = [float(value) for value in raw_z]
            points = np.stack([point_x, point_y, point_z], axis=-1).astype(np.float32)
            ranges = [math.sqrt(x * x + y * y + z * z) for x, y, z in zip(point_x, point_y, point_z)]
            azimuth = [math.degrees(math.atan2(y, x)) for x, y in zip(point_x, point_y)]
            elevation = [
                math.degrees(math.atan2(z, math.sqrt(x * x + y * y))) for x, y, z in zip(point_x, point_y, point_z)
            ]

        fields: Dict[str, Dict[str, Any]] = {
            "points": {"data": points, "dtype": "float32", "units": "meters"},
            "range": {"data": np.asarray(ranges, dtype=np.float32), "dtype": "float32", "units": "meters"},
            "azimuth": {"data": np.asarray(azimuth, dtype=np.float32), "dtype": "float32", "units": "degrees"},
            "elevation": {"data": np.asarray(elevation, dtype=np.float32), "dtype": "float32", "units": "degrees"},
        }
        unavailable = ["semantic_id"]

        intensity = getattr(gmo, "scalar", None)
        if intensity is not None and len(intensity) >= count:
            fields["intensity"] = {
                "data": np.asarray(intensity[:count], dtype=np.float32),
                "dtype": "float32",
                "units": "normalized_return_strength",
            }
        else:
            unavailable.append("intensity")

        object_id_map: Dict[str, str] = {}
        object_ids = None
        if parse_object_ids is not None:
            try:
                object_ids = parse_object_ids(gmo.objId)[:count]
            except Exception:
                object_ids = None
        if object_ids is not None and len(object_ids) == count:
            mask = (1 << 64) - 1
            fields["object_id_low"] = {
                "data": np.asarray([int(value) & mask for value in object_ids], dtype=np.uint64),
                "dtype": "uint64",
                "units": "stable_object_id_low64",
            }
            fields["object_id_high"] = {
                "data": np.asarray([int(value) >> 64 for value in object_ids], dtype=np.uint64),
                "dtype": "uint64",
                "units": "stable_object_id_high64",
            }
            if parse_stable_id_map_data is not None:
                try:
                    stable_data, _stable_info = sensor.get_data("stable-id-map")
                    if stable_data is not None and getattr(stable_data, "size", 0) > 0:
                        stable_map = parse_stable_id_map_data(stable_data)
                        object_id_map = {f"{int(key):032x}": str(value) for key, value in stable_map.items()}
                except Exception:
                    object_id_map = {}
        else:
            unavailable.append("object_id")

        frame_value = getattr(gmo, "frameOfReference", "unknown")
        frame_name = str(getattr(frame_value, "name", frame_value)).lower()
        try:
            sensor_pose = self.get_prim_transform(self._lidar_actual_paths.get(prim_path, prim_path))
        except Exception:
            sensor_pose = None

        return {
            "fields": fields,
            "coordinate_type": "spherical" if spherical else "cartesian",
            "coordinate_frame": frame_name,
            "sensor_pose": sensor_pose,
            "sensor_timestamp_ns": int(getattr(gmo, "timestampNs", 0) or 0),
            "sensor_frame_id": int(getattr(gmo, "frameId", 0) or 0),
            "object_id_map": object_id_map,
            "unavailable_fields": unavailable,
        }

    def _empty_lidar_frame() -> Dict[str, Any]:
        return {
            "fields": {
                "points": {
                    "data": np.zeros((0, 3), dtype=np.float32),
                    "dtype": "float32",
                    "units": "meters",
                }
            },
            "coordinate_frame": "unknown",
            "unavailable_fields": ["intensity", "range", "azimuth", "elevation", "object_id", "semantic_id"],
        }
