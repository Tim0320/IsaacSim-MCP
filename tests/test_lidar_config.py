"""Isaac Sim 6 generic RTX LiDAR configuration contract tests."""

from __future__ import annotations

import pytest
from isaac_sim_mcp_extension.adapters.lidar_config import LidarConfigError, build_generic_lidar_config


def test_build_generic_lidar_config_maps_all_supported_settings():
    attributes, effective = build_generic_lidar_config(
        horizontal_fov_deg=120.0,
        vertical_fov_deg=20.0,
        horizontal_resolution_deg=0.5,
        vertical_resolution_deg=2.0,
        rotation_rate_hz=10,
        min_range_m=0.5,
        max_range_m=80.0,
    )

    assert effective == {
        "horizontal_fov_deg": 120.0,
        "vertical_fov_deg": 20.0,
        "horizontal_resolution_deg": 0.5,
        "vertical_resolution_deg": 2.0,
        "rotation_rate_hz": 10,
        "min_range_m": 0.5,
        "max_range_m": 80.0,
        "horizontal_samples": 240,
        "vertical_channels": 11,
    }
    assert attributes["omni:sensor:Core:validStartAzimuthDeg"] == 0.0
    assert attributes["omni:sensor:Core:validEndAzimuthDeg"] == 120.0
    assert attributes["omni:sensor:Core:startAzimuthOffsetDeg"] == -60.0
    assert attributes["omni:sensor:Core:scanRateBaseHz"] == 10
    assert attributes["omni:sensor:tickRate"] == 10.0
    assert attributes["omni:sensor:Core:patternFiringRateHz"] == 2400
    assert attributes["omni:sensor:Core:nearRangeM"] == 0.5
    assert attributes["omni:sensor:Core:farRangeM"] == 80.0
    assert attributes["omni:sensor:Core:numberOfChannels"] == 11
    assert attributes["omni:sensor:Core:numberOfEmitters"] == 11
    assert attributes["omni:sensor:Core:emitterState:s001:elevationDeg"] == [
        -10.0,
        -8.0,
        -6.0,
        -4.0,
        -2.0,
        0.0,
        2.0,
        4.0,
        6.0,
        8.0,
        10.0,
    ]
    assert attributes["omni:sensor:Core:emitterState:s001:azimuthDeg"] == [0.0] * 11
    assert attributes["omni:sensor:Core:emitterState:s001:channelId"] == list(range(1, 12))
    assert attributes["omni:sensor:Core:emitterState:s001:fireTimeNs"] == [0] * 11


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"horizontal_fov_deg": 361.0}, "INVALID_LIDAR_HORIZONTAL_FOV"),
        ({"vertical_fov_deg": -1.0}, "INVALID_LIDAR_VERTICAL_FOV"),
        ({"horizontal_resolution_deg": 0.0}, "INVALID_LIDAR_HORIZONTAL_RESOLUTION"),
        (
            {"horizontal_fov_deg": 100.0, "horizontal_resolution_deg": 3.0},
            "LIDAR_HORIZONTAL_RESOLUTION_NOT_DIVISIBLE",
        ),
        (
            {"vertical_fov_deg": 20.0, "vertical_resolution_deg": 3.0},
            "LIDAR_VERTICAL_RESOLUTION_NOT_DIVISIBLE",
        ),
        ({"rotation_rate_hz": 12.5}, "INVALID_LIDAR_ROTATION_RATE"),
        ({"min_range_m": 5.0, "max_range_m": 5.0}, "INVALID_LIDAR_RANGE"),
    ],
)
def test_build_generic_lidar_config_rejects_unsupported_values(overrides, code):
    with pytest.raises(LidarConfigError) as exc_info:
        build_generic_lidar_config(**overrides)

    assert exc_info.value.code == code


def test_zero_vertical_fov_creates_one_channel():
    attributes, effective = build_generic_lidar_config(vertical_fov_deg=0.0, vertical_resolution_deg=1.0)

    assert effective["vertical_channels"] == 1
    assert attributes["omni:sensor:Core:emitterState:s001:elevationDeg"] == [0.0]
