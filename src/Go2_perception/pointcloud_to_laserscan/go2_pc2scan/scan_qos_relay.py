#!/usr/bin/env python3
"""
scan_qos_relay.py
订阅 RELIABLE QoS 的 /scan_reliable_in，重发为 BEST_EFFORT QoS 的 /scan。
用途：pointcloud_to_laserscan 默认发 RELIABLE，而 nav2_costmap_2d (Foxy)
      用 SensorDataQoS (BEST_EFFORT) 订阅传感器话题，QoS 不匹配导致数据丢失。
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan


class ScanQosRelay(Node):
    def __init__(self):
        super().__init__('scan_qos_relay')

        self.declare_parameter('input_topic', '/scan_raw')
        self.declare_parameter('output_topic', '/scan')

        input_topic = self.get_parameter('input_topic').value
        output_topic = self.get_parameter('output_topic').value

        reliable_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        best_effort_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self._pub = self.create_publisher(LaserScan, output_topic, best_effort_qos)
        self._sub = self.create_subscription(
            LaserScan, input_topic, self._cb, reliable_qos
        )
        self.get_logger().info(
            f'scan_qos_relay: {input_topic} (RELIABLE) -> {output_topic} (BEST_EFFORT)'
        )

    def _cb(self, msg: LaserScan):
        self._pub.publish(msg)


def main():
    rclpy.init()
    node = ScanQosRelay()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == '__main__':
    main()
