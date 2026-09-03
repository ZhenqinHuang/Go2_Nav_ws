import numpy as np
from types import SimpleNamespace

from leakage_bringup.leakage_projection import (
    calibration_ready,
    camera_points_to_map,
    mask_depth_points,
    synchronized_inputs,
)


def test_mask_depth_points_projects_valid_pixels_and_converts_mm():
    mask = np.array([[False, True], [True, True]])
    depth = np.array([[0, 1000], [2000, 0]], dtype=np.uint16)

    points = mask_depth_points(
        mask, depth, fx=2.0, fy=4.0, cx=0.0, cy=0.0, stride=1
    )

    np.testing.assert_allclose(points, [[0.5, 0.0, 1.0], [0.0, 0.5, 2.0]])


def test_calibration_gate_rejects_placeholder_values():
    assert not calibration_ready(
        {
            "status": "uncalibrated",
            "lidar_to_camera": {"calibrated": False},
            "residual_time_offset_s": None,
        }
    )


def test_calibration_gate_accepts_complete_measured_values():
    assert calibration_ready(
        {
            "status": "calibrated",
            "lidar_to_camera": {
                "calibrated": True,
                "translation_m": [0.1, 0.2, 0.3],
                "rotation_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            },
            "lidar_to_imu": {
                "translation_m": [0.0, 0.0, 0.0],
                "rotation_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            },
            "residual_time_offset_s": 0.0,
        }
    )


def test_camera_points_transform_through_lidar_body_and_map():
    calibration = {
        "lidar_to_camera": {
            "translation_m": [0.1, 0.2, 0.3],
            "rotation_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        },
        "lidar_to_imu": {
            "translation_m": [0.0, 0.0, 0.0],
            "rotation_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        },
    }
    pose = SimpleNamespace(
        position=SimpleNamespace(x=1.0, y=0.0, z=0.0),
        orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
    )

    mapped = camera_points_to_map(np.array([[1.0, 2.0, 3.0]]), calibration, pose)

    np.testing.assert_allclose(mapped, [[1.9, 1.8, 2.7]])


def stamped(seconds):
    whole = int(seconds)
    return SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=whole, nanosec=round((seconds - whole) * 1e9))
        )
    )


def test_synchronized_inputs_selects_nearest_frames_with_time_offset():
    rgb = stamped(10.0)
    depths = [stamped(10.001), stamped(10.04)]
    odoms = [stamped(9.99), stamped(10.03), stamped(10.08)]

    depth, odom = synchronized_inputs(rgb, depths, odoms, 0.03, 0.02)

    assert depth is depths[0]
    assert odom is odoms[1]


def test_synchronized_inputs_rejects_frames_outside_tolerance():
    rgb = stamped(10.0)

    assert synchronized_inputs(rgb, [stamped(10.1)], [stamped(10.13)], 0.03, 0.02) == (
        None,
        None,
    )
