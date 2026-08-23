"""Validated high-level configuration for Isaac Sim 6 generic RTX LiDAR."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any, Dict, Optional, Tuple

DEFAULT_GENERIC_LIDAR_CONFIG = {
    "horizontal_fov_deg": 360.0,
    "vertical_fov_deg": 30.0,
    "horizontal_resolution_deg": 1.0,
    "vertical_resolution_deg": 1.0,
    "rotation_rate_hz": 10,
    "min_range_m": 0.3,
    "max_range_m": 200.0,
}

MAX_HORIZONTAL_SAMPLES = 65536
MAX_VERTICAL_CHANNELS = 1024
MAX_POINTS_PER_SCAN = 2_000_000


class LidarConfigError(ValueError):
    """A stable, machine-readable LiDAR configuration validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _finite_number(name: str, value: Any, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise LidarConfigError(code, f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise LidarConfigError(code, f"{name} must be a finite number")
    return number


def _divisible_samples(span: float, resolution: float, axis: str) -> int:
    ratio = span / resolution
    samples = int(round(ratio))
    if not math.isclose(ratio, samples, rel_tol=0.0, abs_tol=1e-7):
        raise LidarConfigError(
            f"LIDAR_{axis.upper()}_RESOLUTION_NOT_DIVISIBLE",
            f"{axis}_fov_deg must be exactly divisible by {axis}_resolution_deg",
        )
    return samples


def build_generic_lidar_config(
    *,
    horizontal_fov_deg: Optional[float] = None,
    vertical_fov_deg: Optional[float] = None,
    horizontal_resolution_deg: Optional[float] = None,
    vertical_resolution_deg: Optional[float] = None,
    rotation_rate_hz: Optional[float] = None,
    min_range_m: Optional[float] = None,
    max_range_m: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Map the supported high-level settings to 6.0.1 Core schema attributes."""
    values = dict(DEFAULT_GENERIC_LIDAR_CONFIG)
    overrides = {
        "horizontal_fov_deg": horizontal_fov_deg,
        "vertical_fov_deg": vertical_fov_deg,
        "horizontal_resolution_deg": horizontal_resolution_deg,
        "vertical_resolution_deg": vertical_resolution_deg,
        "rotation_rate_hz": rotation_rate_hz,
        "min_range_m": min_range_m,
        "max_range_m": max_range_m,
    }
    values.update({name: value for name, value in overrides.items() if value is not None})

    horizontal_fov = _finite_number("horizontal_fov_deg", values["horizontal_fov_deg"], "INVALID_LIDAR_HORIZONTAL_FOV")
    if not 0.0 < horizontal_fov <= 360.0:
        raise LidarConfigError("INVALID_LIDAR_HORIZONTAL_FOV", "horizontal_fov_deg must be in (0, 360]")

    vertical_fov = _finite_number("vertical_fov_deg", values["vertical_fov_deg"], "INVALID_LIDAR_VERTICAL_FOV")
    if not 0.0 <= vertical_fov <= 180.0:
        raise LidarConfigError("INVALID_LIDAR_VERTICAL_FOV", "vertical_fov_deg must be in [0, 180]")

    horizontal_resolution = _finite_number(
        "horizontal_resolution_deg",
        values["horizontal_resolution_deg"],
        "INVALID_LIDAR_HORIZONTAL_RESOLUTION",
    )
    if not 0.0 < horizontal_resolution <= horizontal_fov:
        raise LidarConfigError(
            "INVALID_LIDAR_HORIZONTAL_RESOLUTION",
            "horizontal_resolution_deg must be greater than 0 and no larger than horizontal_fov_deg",
        )

    vertical_resolution = _finite_number(
        "vertical_resolution_deg",
        values["vertical_resolution_deg"],
        "INVALID_LIDAR_VERTICAL_RESOLUTION",
    )
    if vertical_resolution <= 0.0 or (vertical_fov > 0.0 and vertical_resolution > vertical_fov):
        raise LidarConfigError(
            "INVALID_LIDAR_VERTICAL_RESOLUTION",
            "vertical_resolution_deg must be greater than 0 and no larger than a non-zero vertical_fov_deg",
        )

    rate_value = _finite_number("rotation_rate_hz", values["rotation_rate_hz"], "INVALID_LIDAR_ROTATION_RATE")
    rate = int(round(rate_value))
    if not math.isclose(rate_value, rate, rel_tol=0.0, abs_tol=1e-9) or not 1 <= rate <= 100:
        raise LidarConfigError("INVALID_LIDAR_ROTATION_RATE", "rotation_rate_hz must be an integer in [1, 100]")

    min_range = _finite_number("min_range_m", values["min_range_m"], "INVALID_LIDAR_RANGE")
    max_range = _finite_number("max_range_m", values["max_range_m"], "INVALID_LIDAR_RANGE")
    if min_range < 0.0 or max_range <= min_range:
        raise LidarConfigError("INVALID_LIDAR_RANGE", "range must satisfy 0 <= min_range_m < max_range_m")

    horizontal_samples = _divisible_samples(horizontal_fov, horizontal_resolution, "horizontal")
    vertical_intervals = 0 if vertical_fov == 0.0 else _divisible_samples(vertical_fov, vertical_resolution, "vertical")
    vertical_channels = vertical_intervals + 1
    if horizontal_samples > MAX_HORIZONTAL_SAMPLES:
        raise LidarConfigError(
            "LIDAR_HORIZONTAL_SAMPLE_LIMIT_EXCEEDED",
            f"configuration produces {horizontal_samples} horizontal samples; maximum is {MAX_HORIZONTAL_SAMPLES}",
        )
    if vertical_channels > MAX_VERTICAL_CHANNELS:
        raise LidarConfigError(
            "LIDAR_VERTICAL_CHANNEL_LIMIT_EXCEEDED",
            f"configuration produces {vertical_channels} vertical channels; maximum is {MAX_VERTICAL_CHANNELS}",
        )
    points_per_scan = horizontal_samples * vertical_channels
    if points_per_scan > MAX_POINTS_PER_SCAN:
        raise LidarConfigError(
            "LIDAR_POINT_BUDGET_EXCEEDED",
            f"configuration produces {points_per_scan} points per scan; maximum is {MAX_POINTS_PER_SCAN}",
        )

    if vertical_channels == 1:
        elevations = [0.0]
    else:
        elevations = [
            round((-vertical_fov / 2.0) + index * vertical_resolution, 10) for index in range(vertical_channels)
        ]
    firing_rate = horizontal_samples * rate
    attributes = {
        "omni:sensor:Core:validStartAzimuthDeg": 0.0,
        "omni:sensor:Core:validEndAzimuthDeg": horizontal_fov,
        "omni:sensor:Core:startAzimuthOffsetDeg": -horizontal_fov / 2.0,
        "omni:sensor:Core:scanRateBaseHz": rate,
        "omni:sensor:tickRate": float(rate),
        "omni:sensor:Core:patternFiringRateHz": firing_rate,
        "omni:sensor:Core:nearRangeM": min_range,
        "omni:sensor:Core:farRangeM": max_range,
        "omni:sensor:Core:numberOfChannels": vertical_channels,
        "omni:sensor:Core:numberOfEmitters": vertical_channels,
        "omni:sensor:Core:numLines": vertical_channels,
        "omni:sensor:Core:numRaysPerLine": [horizontal_samples] * vertical_channels,
        "omni:sensor:Core:emitterState:s001:azimuthDeg": [0.0] * vertical_channels,
        "omni:sensor:Core:emitterState:s001:elevationDeg": elevations,
        # Isaac Sim 6.0.1 validates generic LiDAR channel IDs as one-based.
        "omni:sensor:Core:emitterState:s001:channelId": list(range(1, vertical_channels + 1)),
        "omni:sensor:Core:emitterState:s001:fireTimeNs": [0] * vertical_channels,
    }
    effective = {
        "horizontal_fov_deg": horizontal_fov,
        "vertical_fov_deg": vertical_fov,
        "horizontal_resolution_deg": horizontal_resolution,
        "vertical_resolution_deg": vertical_resolution,
        "rotation_rate_hz": rate,
        "min_range_m": min_range,
        "max_range_m": max_range,
        "horizontal_samples": horizontal_samples,
        "vertical_channels": vertical_channels,
    }
    return attributes, effective
