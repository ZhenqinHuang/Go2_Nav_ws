#!/usr/bin/env python3
"""
cloud_filter_node.py
订阅 FAST-LIO2 输出的 body 坐标系点云，按高度和距离过滤后发布 /cloud_filtered。
LaserScan 转换由下游的 pointcloud_to_laserscan 节点负责。

参数：
  cloud_in_topic    : 输入点云话题（默认 /cloud_registered_body）
  cloud_out_topic   : 输出点云话题（默认 /cloud_filtered）
  output_frame      : 输出点云坐标系（默认 base_link；空字符串则保留输入 frame）
  z_min             : 最低保留高度 m（默认 -0.25）
  z_max             : 最高保留高度 m（默认  0.40）
  range_min         : 最小水平距离 m（默认 0.25）
  range_max         : 最大水平距离 m（默认 12.0）
  downsample_voxel  : 体素降采样大小 m（0=不降样，默认 0.05）
"""

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import PointCloud2, PointField


def _pc2_to_xyz(msg: PointCloud2) -> np.ndarray:
    fields = {f.name: f for f in msg.fields}
    x_off = fields['x'].offset
    y_off = fields['y'].offset
    z_off = fields['z'].offset
    step = msg.point_step
    n = msg.width * msg.height
    data = np.frombuffer(msg.data, dtype=np.uint8).reshape(n, step)
    xs = np.frombuffer(data[:, x_off:x_off + 4].tobytes(), dtype=np.float32)
    ys = np.frombuffer(data[:, y_off:y_off + 4].tobytes(), dtype=np.float32)
    zs = np.frombuffer(data[:, z_off:z_off + 4].tobytes(), dtype=np.float32)
    return np.column_stack([xs, ys, zs])


def _xyz_to_pc2(xyz: np.ndarray, header, output_frame: str) -> PointCloud2:
    msg = PointCloud2()
    msg.header = header
    if output_frame:
        msg.header.frame_id = output_frame
    msg.height = 1
    msg.width = len(xyz)
    msg.is_dense = False
    msg.is_bigendian = False
    msg.point_step = 12
    msg.row_step = msg.point_step * len(xyz)
    msg.fields = [
        PointField(name='x', offset=0,  datatype=PointField.FLOAT32, count=1),
        PointField(name='y', offset=4,  datatype=PointField.FLOAT32, count=1),
        PointField(name='z', offset=8,  datatype=PointField.FLOAT32, count=1),
    ]
    msg.data = xyz.astype(np.float32).tobytes()
    return msg


def _voxel_downsample(xyz: np.ndarray, voxel_size: float) -> np.ndarray:
    if voxel_size <= 0 or len(xyz) == 0:
        return xyz
    keys = np.floor(xyz / voxel_size).astype(np.int32)
    _, indices = np.unique(
        keys[:, 0] * 1_000_000 + keys[:, 1] * 1_000 + keys[:, 2],
        return_index=True
    )
    return xyz[indices]


class CloudFilterNode(Node):
    def __init__(self):
        super().__init__('cloud_filter_node')

        self.declare_parameter('cloud_in_topic',   '/cloud_registered_body')
        self.declare_parameter('cloud_out_topic',  '/cloud_filtered')
        self.declare_parameter('output_frame',     'base_link')
        self.declare_parameter('z_min',            -0.25)
        self.declare_parameter('z_max',             0.40)
        self.declare_parameter('range_min',         0.25)
        self.declare_parameter('range_max',        12.0)
        self.declare_parameter('downsample_voxel',  0.05)

        self._in_topic  = self.get_parameter('cloud_in_topic').value
        self._out_topic = self.get_parameter('cloud_out_topic').value
        self._out_frame = self.get_parameter('output_frame').value
        self._z_min     = float(self.get_parameter('z_min').value)
        self._z_max     = float(self.get_parameter('z_max').value)
        self._r_min     = float(self.get_parameter('range_min').value)
        self._r_max     = float(self.get_parameter('range_max').value)
        self._voxel     = float(self.get_parameter('downsample_voxel').value)

        # 订阅上游（FAST-LIO2 用 BEST_EFFORT 发布）
        sub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
        )
        # 发布给 pointcloud_to_laserscan（默认 RELIABLE 订阅）
        pub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
        )

        self._cloud_pub = self.create_publisher(PointCloud2, self._out_topic, pub_qos)
        self._sub = self.create_subscription(
            PointCloud2, self._in_topic, self._callback, sub_qos)

        self.get_logger().info(
            f'cloud_filter_node 已启动\n'
            f'  输入  : {self._in_topic}\n'
            f'  输出  : {self._out_topic}\n'
            f'  输出坐标系: {self._out_frame or "保留输入frame"}\n'
            f'  高度切片: z ∈ [{self._z_min}, {self._z_max}] m\n'
            f'  水平范围: [{self._r_min}, {self._r_max}] m\n'
            f'  体素降采: {self._voxel} m'
        )

    def _callback(self, msg: PointCloud2):
        try:
            xyz = _pc2_to_xyz(msg)
        except (KeyError, ValueError) as e:
            self.get_logger().warn(f'点云解析失败: {e}', throttle_duration_sec=5.0)
            return

        if len(xyz) == 0:
            return

        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        xyz = xyz[(xyz[:, 2] >= self._z_min) & (xyz[:, 2] <= self._z_max)]
        if len(xyz) == 0:
            return

        r2 = xyz[:, 0] ** 2 + xyz[:, 1] ** 2
        xyz = xyz[(r2 >= self._r_min ** 2) & (r2 <= self._r_max ** 2)]
        if len(xyz) == 0:
            return

        xyz = _voxel_downsample(xyz, self._voxel)
        self._cloud_pub.publish(_xyz_to_pc2(xyz, msg.header, self._out_frame))

        self.get_logger().debug(
            f'点云过滤: {msg.width * msg.height} → {len(xyz)} 点',
            throttle_duration_sec=2.0
        )


def main(args=None):
    rclpy.init(args=args)
    node = CloudFilterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
