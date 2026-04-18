#!/usr/bin/env python3
"""
cloud_filter_node.py
─────────────────────────────────────────────────────────────────────
功能：
  1. 订阅 FAST-LIO2 输出的 body 坐标系三维点云（/cloud_registered_body）
  2. 按高度（z 轴）和距离过滤，保留"导航切片层"内的点
  3. 将过滤后的点云发布到 /cloud_filtered，供下游
     pointcloud_to_laserscan 节点转换为 /scan

背景：
  - 机器狗 Go2，站立高度约 0.35 m
  - MID360 倾斜安装 45°（雷达模块倒扣于机背，头部前下方）
    外参旋转已在 FAST-LIO2 中处理，/cloud_registered_body 已对齐 body 坐标系
  - 应用场景：约 70 平米室内店铺（最大距离约 12 m）
  - 目标：提取机器人周围腰部到低障碍高度范围内的点，生成稳定 /scan

坐标系（body / IMU 坐标系）：
  x 正方向 = 机头前方
  y 正方向 = 机体左侧
  z 正方向 = 竖直向上
  原点     = IMU/机体中心（约离地 0.35 m）

高度切片策略（相对 body 原点）：
  z_min = -0.25 m  →  即离地面 ~0.10 m（过滤地面点）
  z_max = +0.40 m  →  即离地面 ~0.75 m（过滤顶部/天花板及机身遮挡）
  范围约 0.10 m ~ 0.75 m（离地），覆盖桌腿、货架底部、门框等障碍物

参数（均可通过 ROS2 参数覆盖）：
  cloud_in_topic    : 输入点云话题（默认 /cloud_registered_body）
  cloud_out_topic   : 输出点云话题（默认 /cloud_filtered）
  z_min             : 最低保留高度，Body 坐标系 m（默认 -0.25）
  z_max             : 最高保留高度，Body 坐标系 m（默认  0.40）
  range_min         : 最小水平距离 m（默认 0.20，过滤机体反射）
  range_max         : 最大水平距离 m（默认 12.0，店铺对角线约 12 m）
  downsample_voxel  : 体素降采样大小 m（0 = 不降样，默认 0.05）
"""

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import PointCloud2, PointField
import struct


# ──────────────────────────────────────────────────────────────────
#  PointCloud2 辅助函数（纯numpy，不依赖 ros2_numpy）
# ──────────────────────────────────────────────────────────────────

def _pc2_to_xyz(msg: PointCloud2) -> np.ndarray:
    """
    快速从 PointCloud2 消息中提取 XYZ 坐标（float32）。
    返回 shape=(N, 3) 的 numpy 数组。
    """
    # 解析字段偏移
    fields = {f.name: f for f in msg.fields}
    x_off = fields['x'].offset
    y_off = fields['y'].offset
    z_off = fields['z'].offset
    step = msg.point_step

    data = np.frombuffer(msg.data, dtype=np.uint8)
    n = msg.width * msg.height

    # 批量提取：直接切片，避免逐点 struct.unpack
    raw = data.reshape(n, step)
    xs = raw[:, x_off:x_off + 4].view(np.float32).flatten()
    ys = raw[:, y_off:y_off + 4].view(np.float32).flatten()
    zs = raw[:, z_off:z_off + 4].view(np.float32).flatten()

    return np.column_stack([xs, ys, zs])


def _xyz_to_pc2(xyz: np.ndarray, header) -> PointCloud2:
    """
    将 shape=(N,3) 的 float32 xyz 数组打包成 PointCloud2 消息。
    """
    msg = PointCloud2()
    msg.header = header
    msg.height = 1
    msg.width = len(xyz)
    msg.is_dense = False
    msg.is_bigendian = False
    msg.point_step = 12   # 3 × float32
    msg.row_step = msg.point_step * len(xyz)

    msg.fields = [
        PointField(name='x', offset=0,  datatype=PointField.FLOAT32, count=1),
        PointField(name='y', offset=4,  datatype=PointField.FLOAT32, count=1),
        PointField(name='z', offset=8,  datatype=PointField.FLOAT32, count=1),
    ]

    data = xyz.astype(np.float32).tobytes()
    msg.data = data
    return msg


def _voxel_downsample(xyz: np.ndarray, voxel_size: float) -> np.ndarray:
    """
    简单体素降采样：每个 voxel 保留一个点（最先访问的）。
    比 PCL 慢但无外部依赖，适合 Orin NX 上的 Python 节点。
    """
    if voxel_size <= 0 or len(xyz) == 0:
        return xyz
    keys = np.floor(xyz / voxel_size).astype(np.int32)
    # 用字符串 key 去重（简单方案，适合中等点数）
    unique_keys, indices = np.unique(
        keys[:, 0] * 1_000_000 + keys[:, 1] * 1_000 + keys[:, 2],
        return_index=True
    )
    return xyz[indices]


# ──────────────────────────────────────────────────────────────────
#  主节点
# ──────────────────────────────────────────────────────────────────

class CloudFilterNode(Node):
    def __init__(self):
        super().__init__('cloud_filter_node')

        # ── 参数声明 ────────────────────────────────────────────
        self.declare_parameter('cloud_in_topic',   '/cloud_registered_body')
        self.declare_parameter('cloud_out_topic',  '/cloud_filtered')
        # 高度切片（body 坐标系，z 向上为正）
        # 原点离地约 0.35 m，所以：
        #   z_min = -0.25 → 离地 0.10 m（滤除地面点）
        #   z_max = +0.40 → 离地 0.75 m（滤除天花板/机身遮挡）
        self.declare_parameter('z_min',            -0.25)
        self.declare_parameter('z_max',             0.40)
        # 水平距离过滤（滤除机体自身反射和过远无效点）
        self.declare_parameter('range_min',         0.20)
        self.declare_parameter('range_max',        12.0)
        # 体素降采样（0 = 关闭）; 0.05 m 在 70 平米店铺中足够
        self.declare_parameter('downsample_voxel',  0.05)

        # ── 读取参数 ────────────────────────────────────────────
        self._in_topic  = self.get_parameter('cloud_in_topic').value
        self._out_topic = self.get_parameter('cloud_out_topic').value
        self._z_min     = float(self.get_parameter('z_min').value)
        self._z_max     = float(self.get_parameter('z_max').value)
        self._r_min     = float(self.get_parameter('range_min').value)
        self._r_max     = float(self.get_parameter('range_max').value)
        self._voxel     = float(self.get_parameter('downsample_voxel').value)

        # ── QoS（匹配 FAST-LIO2 发布器的 sensor data QoS）──────
        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
        )

        self._pub = self.create_publisher(
            PointCloud2, self._out_topic, sensor_qos)

        self._sub = self.create_subscription(
            PointCloud2, self._in_topic,
            self._callback, sensor_qos)

        self.get_logger().info(
            f'cloud_filter_node 已启动\n'
            f'  输入  : {self._in_topic}\n'
            f'  输出  : {self._out_topic}\n'
            f'  高度切片: z ∈ [{self._z_min}, {self._z_max}] m (body坐标系)\n'
            f'  水平范围: [{self._r_min}, {self._r_max}] m\n'
            f'  体素降采: {self._voxel} m\n'
        )

    def _callback(self, msg: PointCloud2):
        try:
            xyz = _pc2_to_xyz(msg)
        except (KeyError, ValueError) as e:
            self.get_logger().warn(f'点云解析失败: {e}', throttle_duration_sec=5.0)
            return

        if len(xyz) == 0:
            return

        # ── 过滤 NaN / Inf ──────────────────────────────────────
        valid = np.isfinite(xyz).all(axis=1)
        xyz = xyz[valid]
        if len(xyz) == 0:
            return

        # ── 高度过滤（Body z 轴）────────────────────────────────
        z_mask = (xyz[:, 2] >= self._z_min) & (xyz[:, 2] <= self._z_max)
        xyz = xyz[z_mask]
        if len(xyz) == 0:
            return

        # ── 水平距离过滤（XY 平面径向距离）────────────────────
        r2 = xyz[:, 0] ** 2 + xyz[:, 1] ** 2
        r_mask = (r2 >= self._r_min ** 2) & (r2 <= self._r_max ** 2)
        xyz = xyz[r_mask]
        if len(xyz) == 0:
            return

        # ── 体素降采样（降低下游计算量）────────────────────────
        xyz = _voxel_downsample(xyz, self._voxel)

        # ── 发布过滤后点云 ──────────────────────────────────────
        out_msg = _xyz_to_pc2(xyz, msg.header)
        self._pub.publish(out_msg)

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
