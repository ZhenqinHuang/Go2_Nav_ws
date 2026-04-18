#!/usr/bin/env python3
"""
PTP 同步状态监控节点
订阅同步状态并输出到终端，可用于调试
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool


class PtpMonitorNode(Node):
    def __init__(self):
        super().__init__('ptp_monitor_node')
        self.create_subscription(String, '/ptp_sync/status', self._status_cb, 10)
        self.create_subscription(Bool, '/ptp_sync/is_synced', self._synced_cb, 10)
        self.get_logger().info('PTP 监控节点已启动，等待同步状态...')

    def _status_cb(self, msg: String):
        self.get_logger().info(f'[状态] {msg.data}')

    def _synced_cb(self, msg: Bool):
        if msg.data:
            self.get_logger().info('[同步] 硬件时间戳已同步')
        else:
            self.get_logger().warn('[同步] 等待 PTP 同步...')


def main(args=None):
    rclpy.init(args=args)
    node = PtpMonitorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
