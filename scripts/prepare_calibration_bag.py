#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
from rosbags.rosbag2 import Reader, Writer
from rosbags.typesys import Stores, get_typestore, get_types_from_msg


CUSTOM_POINT = """uint32 offset_time
float32 x
float32 y
float32 z
uint8 reflectivity
uint8 tag
uint8 line
"""
CUSTOM_MSG = """std_msgs/Header header
uint64 timebase
uint32 point_num
uint8 lidar_id
uint8[3] rsvd
CustomPoint[] points
"""
INPUT_TOPICS = {
    "/livox/lidar",
    "/camera/color/image_raw",
    "/camera/color/camera_info",
}


def custom_points_array(message) -> np.ndarray:
    points = np.empty((len(message.points), 4), dtype="<f4")
    for index, point in enumerate(message.points):
        points[index] = point.x, point.y, point.z, point.reflectivity
    return points


def pointcloud_message(message, typestore):
    point_field = typestore.types["sensor_msgs/msg/PointField"]
    point_cloud = typestore.types["sensor_msgs/msg/PointCloud2"]
    points = custom_points_array(message)
    fields = [
        point_field(name, offset, point_field.FLOAT32, 1)
        for name, offset in (("x", 0), ("y", 4), ("z", 8), ("intensity", 12))
    ]
    return point_cloud(
        message.header,
        1,
        len(points),
        fields,
        False,
        16,
        16 * len(points),
        points.view(np.uint8).reshape(-1),
        True,
    )


def convert_bag(source: Path, destination: Path) -> dict[str, int]:
    if not source.is_dir():
        raise FileNotFoundError(f"source bag not found: {source}")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite: {destination}")

    typestore = get_typestore(Stores.ROS2_FOXY)
    typestore.register(
        get_types_from_msg(CUSTOM_POINT, "livox_ros_driver2/msg/CustomPoint")
    )
    typestore.register(get_types_from_msg(CUSTOM_MSG, "livox_ros_driver2/msg/CustomMsg"))
    counts = {
        "/livox/points": 0,
        "/camera/color/image_raw": 0,
        "/camera/color/camera_info": 0,
    }

    with Reader(source) as reader:
        inputs = [connection for connection in reader.connections if connection.topic in INPUT_TOPICS]
        available = {connection.topic for connection in inputs}
        missing = INPUT_TOPICS - available
        if missing:
            raise ValueError(f"source bag is missing: {', '.join(sorted(missing))}")

        with Writer(destination, version=8) as writer:
            outputs = {
                topic: writer.add_connection(topic, connection.msgtype, typestore=typestore)
                for topic in INPUT_TOPICS - {"/livox/lidar"}
                for connection in inputs
                if connection.topic == topic
            }
            outputs["/livox/points"] = writer.add_connection(
                "/livox/points", "sensor_msgs/msg/PointCloud2", typestore=typestore
            )

            for connection, timestamp, raw in reader.messages(connections=inputs):
                if connection.topic == "/livox/lidar":
                    message = typestore.deserialize_cdr(raw, connection.msgtype)
                    cloud = pointcloud_message(message, typestore)
                    raw = typestore.serialize_cdr(cloud, cloud.__msgtype__)
                    topic = "/livox/points"
                else:
                    topic = connection.topic
                writer.write(outputs[topic], timestamp, raw)
                counts[topic] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a standard PointCloud2 LiDAR-camera calibration bag"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    for topic, count in convert_bag(args.source.resolve(), args.destination.resolve()).items():
        print(f"{topic}={count}")


if __name__ == "__main__":
    main()
