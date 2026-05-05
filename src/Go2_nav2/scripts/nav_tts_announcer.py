#!/usr/bin/env python3
"""
nav_tts_announcer.py
监听 /rosout，bt_navigator 打印 "Goal succeeded" 时通过 /tts_text 播报。
"""

import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
from rcl_interfaces.msg import Log
from std_msgs.msg import String


class NavTtsAnnouncer(Node):
    def __init__(self):
        super().__init__('nav_tts_announcer')

        self.declare_parameter('success_text', '导航成功，已到达目标位置')
        self.declare_parameter('tts_topic', '/tts_text')

        self._success_text = self.get_parameter('success_text').value
        tts_topic = self.get_parameter('tts_topic').value

        self._tts_pub = self.create_publisher(String, tts_topic, 10)

        # /rosout 发布者使用 TRANSIENT_LOCAL，订阅侧必须匹配否则 ROS 2 Foxy 下消息全部丢弃
        rosout_qos = QoSProfile(
            depth=50,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(Log, '/rosout', self._rosout_cb, rosout_qos)

        self._last_announce_time = 0.0

        self.get_logger().info(
            f'NavTtsAnnouncer 启动  tts_topic={tts_topic}  '
            f'播报文本="{self._success_text}"'
        )

    def _rosout_cb(self, msg: Log):
        if msg.name != 'bt_navigator':
            return

        if 'Goal succeeded' not in msg.msg:
            return

        now = time.monotonic()
        if now - self._last_announce_time < 5.0:
            return
        self._last_announce_time = now

        self.get_logger().info(f'检测到导航成功，播报: {self._success_text}')
        tts_msg = String()
        tts_msg.data = self._success_text
        self._tts_pub.publish(tts_msg)


def main(args=None):
    rclpy.init(args=args)
    node = NavTtsAnnouncer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
