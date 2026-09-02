#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

import numpy as np
import yaml


def quaternion_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    quaternion = np.asarray([x, y, z, w], dtype=float)
    norm = np.linalg.norm(quaternion)
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("calibration quaternion is invalid")
    x, y, z, w = quaternion / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def lidar_to_camera_config(result: dict, provenance: str, residual_time_offset_s):
    transform = result.get("results", {}).get("T_lidar_camera")
    if not isinstance(transform, list) or len(transform) != 7:
        raise ValueError("calib.json is missing a 7-value results.T_lidar_camera")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in transform):
        raise ValueError("T_lidar_camera contains a non-finite value")
    if residual_time_offset_s is not None and not math.isfinite(residual_time_offset_s):
        raise ValueError("residual time offset must be finite")

    translation_lidar_camera = np.asarray(transform[:3], dtype=float)
    rotation_lidar_camera = quaternion_matrix(*transform[3:])
    rotation_camera_lidar = rotation_lidar_camera.T
    translation_camera_lidar = -rotation_camera_lidar @ translation_lidar_camera
    if not np.allclose(rotation_camera_lidar.T @ rotation_camera_lidar, np.eye(3), atol=1e-6):
        raise ValueError("inverted rotation matrix is not orthonormal")
    if not math.isclose(float(np.linalg.det(rotation_camera_lidar)), 1.0, abs_tol=1e-6):
        raise ValueError("inverted rotation matrix determinant is not 1")

    return {
        "status": "calibrated" if residual_time_offset_s is not None else "uncalibrated",
        "lidar_to_camera": {
            "calibrated": True,
            "translation_m": translation_camera_lidar.tolist(),
            "rotation_matrix": rotation_camera_lidar.reshape(-1).tolist(),
            "provenance": provenance,
        },
        "residual_time_offset_s": residual_time_offset_s,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely import direct_visual_lidar_calibration output"
    )
    parser.add_argument("result", type=Path)
    parser.add_argument("base_config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--residual-time-offset-s", type=float)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite: {args.output}")
    result = json.loads(args.result.read_text(encoding="utf-8"))
    config = yaml.safe_load(args.base_config.read_text(encoding="utf-8")) or {}
    config.update(
        lidar_to_camera_config(
            result, str(args.result.resolve()), args.residual_time_offset_s
        )
    )
    args.output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(f"status={config['status']}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
