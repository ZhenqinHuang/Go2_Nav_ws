#!/usr/bin/env python3
from __future__ import annotations

import numpy as np


def pointcloud_xyz(message) -> np.ndarray:
    offsets = {field.name: field.offset for field in message.fields}
    if not all(name in offsets for name in ("x", "y", "z")):
        raise ValueError("PointCloud2 does not contain x/y/z fields")
    byte_order = ">" if message.is_bigendian else "<"
    dtype = np.dtype(
        {
            "names": ["x", "y", "z"],
            "formats": [f"{byte_order}f4"] * 3,
            "offsets": [offsets["x"], offsets["y"], offsets["z"]],
            "itemsize": message.point_step,
        }
    )
    points = np.frombuffer(message.data, dtype=dtype, count=message.width * message.height)
    xyz = np.column_stack((points["x"], points["y"], points["z"]))
    return xyz[np.isfinite(xyz).all(axis=1)]


def image_array(message) -> np.ndarray:
    if message.encoding == "rgb8":
        row = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
        return row[:, : message.width * 3].reshape(message.height, message.width, 3)
    if message.encoding == "16UC1":
        row = np.frombuffer(message.data, dtype="<u2").reshape(
            message.height, message.step // 2
        )
        return row[:, : message.width]
    raise ValueError(f"unsupported image encoding: {message.encoding}")


def path_xyz(message) -> np.ndarray:
    return np.asarray(
        [
            [pose.pose.position.x, pose.pose.position.y, pose.pose.position.z]
            for pose in message.poses
        ],
        dtype=float,
    ).reshape(-1, 3)
