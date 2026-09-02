from __future__ import annotations


def relay_topics() -> dict[str, str]:
    return {
        "/Odometry": "/record/odometry",
        "/cloud_registered": "/record/cloud_registered",
    }


def main() -> None:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2

    class RecordRelay(Node):
        def __init__(self) -> None:
            super().__init__("leakage_record_relay")
            odom_pub = self.create_publisher(Odometry, "/record/odometry", 10)
            cloud_pub = self.create_publisher(PointCloud2, "/record/cloud_registered", 10)
            self._subscriptions = [
                self.create_subscription(Odometry, "/Odometry", odom_pub.publish, 10),
                self.create_subscription(
                    PointCloud2,
                    "/cloud_registered",
                    cloud_pub.publish,
                    qos_profile_sensor_data,
                ),
            ]
            self._publishers = [odom_pub, cloud_pub]

    rclpy.init()
    node = RecordRelay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
