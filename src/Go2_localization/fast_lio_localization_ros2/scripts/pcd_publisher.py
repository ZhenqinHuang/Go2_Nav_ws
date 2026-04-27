#!/usr/bin/env python3
# coding: utf-8

import os
import numpy as np
import open3d as o3d

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Header
from sensor_msgs_py import point_cloud2 as pc2


class PcdPublisherNode(Node):
	def __init__(self) -> None:
		super().__init__('pcd_publisher')
		self.declare_parameter('map', '')
		self.declare_parameter('frame_id', 'map')
		self.declare_parameter('rate', 1.0)

		transient_local_qos = QoSProfile(depth=1)
		transient_local_qos.reliability = ReliabilityPolicy.RELIABLE
		transient_local_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

		self.pub = self.create_publisher(PointCloud2, '/map3d', transient_local_qos)

		path = self.get_parameter('map').value
		if not path or not os.path.isfile(path):
			self.get_logger().error(f'Invalid PCD path: {path}')
			self._points_bytes = b''
			self._points_count = 0
		else:
			pcd = o3d.io.read_point_cloud(path)
			pts = np.asarray(pcd.points, dtype=np.float32)
			self._points_count = pts.shape[0]
			self._points_bytes = pts.tobytes()
			self.get_logger().info(f'Loaded PCD: {path} with {self._points_count} points')

		rate = float(self.get_parameter('rate').value)
		self.timer = self.create_timer(1.0 / max(1e-6, rate), self.on_timer)

	def on_timer(self) -> None:
		if self._points_count == 0:
			return
		header = Header()
		header.frame_id = self.get_parameter('frame_id').value
		header.stamp = self.get_clock().now().to_msg()
		msg = PointCloud2()
		msg.header = header
		msg.height = 1
		msg.width = self._points_count
		msg.is_dense = False
		msg.is_bigendian = False
		msg.point_step = 12
		msg.row_step = 12 * self._points_count
		msg.fields = [
			pc2.PointField(name='x', offset=0,  datatype=pc2.PointField.FLOAT32, count=1),
			pc2.PointField(name='y', offset=4,  datatype=pc2.PointField.FLOAT32, count=1),
			pc2.PointField(name='z', offset=8,  datatype=pc2.PointField.FLOAT32, count=1),
		]
		msg.data = self._points_bytes
		self.pub.publish(msg)


def main():
	rclpy.init()
	node = PcdPublisherNode()
	try:
		rclpy.spin(node)
	except KeyboardInterrupt:
		pass
	finally:
		node.destroy_node()
		rclpy.shutdown()


if __name__ == '__main__':
	main() 