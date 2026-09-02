#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from rosbags.rosbag2 import Reader


TOPICS = (
    "/record/cloud_registered",
    "/fastlio_path",
    "/camera/color/image_raw",
    "/camera/depth/image_rect_raw",
)


def validate_topics(available: set[str]) -> None:
    missing = [topic for topic in TOPICS if topic not in available]
    if missing:
        raise ValueError(f"bag is missing required topics: {', '.join(missing)}")


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


def check_bag(directory: Path) -> None:
    if not directory.is_dir():
        raise FileNotFoundError(f"bag directory not found: {directory}")
    with Reader(directory) as reader:
        validate_topics({connection.topic for connection in reader.connections})
        print(f"duration_seconds={(reader.end_time - reader.start_time) / 1e9:.3f}")
        for topic in TOPICS:
            connection = next(item for item in reader.connections if item.topic == topic)
            print(f"{topic}={connection.msgcount}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Display a synchronized leakage ROS2 bag")
    parser.add_argument("bag", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        parser.error("GUI is not implemented yet; use --check")
    check_bag(args.bag.resolve())


if __name__ == "__main__":
    main()
