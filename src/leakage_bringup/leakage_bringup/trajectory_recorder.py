from __future__ import annotations

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry, Path
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2

from .trajectory_math import append_pose


class TrajectoryRecorder(Node):
    def __init__(self) -> None:
        super().__init__("trajectory_recorder")
        max_poses = int(self.declare_parameter("max_poses", 20000).value)
        publish_hz = float(self.declare_parameter("publish_hz", 1.0).value)
        if max_poses < 1 or publish_hz <= 0:
            raise ValueError("max_poses and publish_hz must be positive")

        self._max_poses = max_poses
        self._poses: list[PoseStamped] = []
        self._dirty = False
        self._path_publisher = self.create_publisher(Path, "/fastlio_path", 1)
        self._odometry_publisher = self.create_publisher(
            Odometry, "/record/odometry", 10
        )
        self._cloud_publisher = self.create_publisher(
            PointCloud2, "/record/cloud_registered", 10
        )
        self._subscription = self.create_subscription(
            Odometry, "/Odometry", self._odometry_callback, 50
        )
        self._cloud_subscription = self.create_subscription(
            PointCloud2,
            "/cloud_registered",
            self._cloud_callback,
            10,
        )
        self._timer = self.create_timer(1.0 / publish_hz, self._publish_path)

    def _odometry_callback(self, message: Odometry) -> None:
        self._odometry_publisher.publish(message)
        pose = PoseStamped()
        pose.header = message.header
        pose.pose = message.pose.pose
        self._poses = append_pose(self._poses, pose, max_length=self._max_poses)
        self._dirty = True

    def _cloud_callback(self, message: PointCloud2) -> None:
        self._cloud_publisher.publish(message)

    def _publish_path(self) -> None:
        if not self._dirty or not self._poses:
            return
        path = Path()
        path.header = self._poses[-1].header
        path.poses = self._poses
        self._path_publisher.publish(path)
        self._dirty = False


def main() -> None:
    rclpy.init()
    node = TrajectoryRecorder()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
