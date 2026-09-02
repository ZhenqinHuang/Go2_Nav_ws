import math

import numpy as np


def calibration_ready(data: dict) -> bool:
    camera = data.get("lidar_to_camera", {})
    imu = data.get("lidar_to_imu", {})
    translation = camera.get("translation_m")
    rotation = camera.get("rotation_matrix")
    imu_translation = imu.get("translation_m")
    imu_rotation = imu.get("rotation_matrix")
    offset = data.get("residual_time_offset_s")
    if (
        data.get("status") != "calibrated"
        or camera.get("calibrated") is not True
        or len(translation or []) != 3
        or len(rotation or []) != 9
        or len(imu_translation or []) != 3
        or len(imu_rotation or []) != 9
        or offset is None
    ):
        return False
    try:
        return all(
            math.isfinite(float(value))
            for value in translation
            + rotation
            + imu_translation
            + imu_rotation
            + [offset]
        )
    except (TypeError, ValueError):
        return False


def mask_depth_points(
    mask: np.ndarray,
    depth_mm: np.ndarray,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    max_depth_m: float = 10.0,
    stride: int = 4,
) -> np.ndarray:
    rows, cols = np.nonzero(mask[::stride, ::stride])
    rows *= stride
    cols *= stride
    z = depth_mm[rows, cols].astype(np.float32) / 1000.0
    valid = (z > 0.0) & (z <= max_depth_m)
    rows, cols, z = rows[valid], cols[valid], z[valid]
    return np.column_stack(((cols - cx) * z / fx, (rows - cy) * z / fy, z)).astype(
        np.float32
    )


def quaternion_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    norm = x * x + y * y + z * z + w * w
    if norm == 0.0:
        raise ValueError("zero-length quaternion")
    x, y, z, w = np.asarray([x, y, z, w], dtype=float) * math.sqrt(2.0 / norm)
    q = np.outer([x, y, z, w], [x, y, z, w])
    return np.array(
        [
            [1.0 - q[1, 1] - q[2, 2], q[0, 1] - q[2, 3], q[0, 2] + q[1, 3]],
            [q[0, 1] + q[2, 3], 1.0 - q[0, 0] - q[2, 2], q[1, 2] - q[0, 3]],
            [q[0, 2] - q[1, 3], q[1, 2] + q[0, 3], 1.0 - q[0, 0] - q[1, 1]],
        ]
    )


def camera_points_to_map(points: np.ndarray, calibration: dict, pose) -> np.ndarray:
    camera = calibration["lidar_to_camera"]
    r_camera_lidar = np.asarray(camera["rotation_matrix"], dtype=float).reshape(3, 3)
    t_camera_lidar = np.asarray(camera["translation_m"], dtype=float)
    lidar = (points - t_camera_lidar) @ r_camera_lidar

    lidar_imu = calibration["lidar_to_imu"]
    r_imu_lidar = np.asarray(lidar_imu["rotation_matrix"], dtype=float).reshape(3, 3)
    t_imu_lidar = np.asarray(lidar_imu["translation_m"], dtype=float)
    body = lidar @ r_imu_lidar.T + t_imu_lidar

    orientation = pose.orientation
    r_map_body = quaternion_matrix(
        orientation.x, orientation.y, orientation.z, orientation.w
    )
    position = pose.position
    return (body @ r_map_body.T + [position.x, position.y, position.z]).astype(
        np.float32
    )
