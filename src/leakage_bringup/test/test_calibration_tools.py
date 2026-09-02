from types import SimpleNamespace

import numpy as np

from scripts.import_calibration_result import lidar_to_camera_config
from scripts.prepare_calibration_bag import custom_points_array


def test_custom_livox_points_become_xyzi_float32():
    message = SimpleNamespace(
        points=[
            SimpleNamespace(x=1.0, y=2.0, z=3.0, reflectivity=42),
            SimpleNamespace(x=4.0, y=5.0, z=6.0, reflectivity=99),
        ]
    )

    points = custom_points_array(message)

    assert points.dtype == np.dtype("<f4")
    np.testing.assert_allclose(points, [[1.0, 2.0, 3.0, 42.0], [4.0, 5.0, 6.0, 99.0]])


def test_import_inverts_camera_to_lidar_result_and_keeps_gate_closed_without_time():
    result = {"results": {"T_lidar_camera": [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0]}}

    config = lidar_to_camera_config(result, "calib.json", None)

    assert config["status"] == "uncalibrated"
    assert config["residual_time_offset_s"] is None
    np.testing.assert_allclose(config["lidar_to_camera"]["translation_m"], [-1.0, -2.0, -3.0])
    np.testing.assert_allclose(config["lidar_to_camera"]["rotation_matrix"], np.eye(3).reshape(-1))


def test_import_opens_gate_only_with_explicit_finite_time_offset():
    result = {"results": {"T_lidar_camera": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]}}

    config = lidar_to_camera_config(result, "calib.json", 0.012)

    assert config["status"] == "calibrated"
    assert config["lidar_to_camera"]["calibrated"] is True
    assert config["residual_time_offset_s"] == 0.012
