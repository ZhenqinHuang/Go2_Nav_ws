#!/usr/bin/env python3
"""
odom_tf_bridge_node.py
══════════════════════════════════════════════════════════════════════
功能：
  将 FAST-LIO2 输出的里程计消息转换为 NAV2 标准格式，并广播对应 TF。

FAST-LIO2 输出（原始）：
  话题  : /Odometry
  类型  : nav_msgs/msg/Odometry
  坐标系: header.frame_id = "camera_init"
          child_frame_id  = "body"
  TF   : FAST-LIO2 自身会广播 camera_init → body（100 Hz）

NAV2 需要（目标）：
  话题  : /odom
  类型  : nav_msgs/msg/Odometry
  坐标系: header.frame_id = "odom"
          child_frame_id  = "base_link"
  TF   : odom → base_link（本节点广播）

适配说明（机器狗 Go2）：
  ┌───────────────────────────────────────────────────────────┐
  │  FAST-LIO2 坐标系    →     NAV2 坐标系                    │
  │  camera_init         →     odom  (全局起点帧，等价)        │
  │  body (IMU 帧)       →     base_link (机器人基座帧)        │
  │                                                           │
  │  Go2 默认 base_link 与 IMU 帧几乎重合（偏差 < 5 cm），    │
  │  本节点直接做 frame_id 重命名，不做坐标变换。             │
  │  若实际安装有偏移，通过 body_to_base_link_* 参数配置。    │
  └───────────────────────────────────────────────────────────┘

TF 树（NAV2 要求）：
  map ──── odom ──── base_link ──── (sensor frames)
             ↑
       本节点广播

协方差策略：
  FAST-LIO2 /Odometry 的协方差字段均为 0（未填充）。
  本节点为 NAV2 设置合理的默认协方差：
    位置  xyz: 0.01 m²   (±10 cm 1σ)
    姿态 rpy:  0.005 rad² (±4° 1σ)
  若 FAST-LIO2 的协方差非零则直接透传。

参数（均可 YAML 或 launch 时覆盖）：
  fastlio_odom_topic  : 输入话题（默认 /Odometry）
  odom_topic          : 输出话题（默认 /odom）
  odom_frame          : 输出 header.frame_id（默认 odom）
  base_frame          : 输出 child_frame_id（默认 base_link）
  publish_tf          : 是否广播 TF（默认 true）
  body_to_base_link_x : IMU → base_link 平移 x (m)（默认 0.0）
  body_to_base_link_y : IMU → base_link 平移 y (m)（默认 0.0）
  body_to_base_link_z : IMU → base_link 平移 z (m)（默认 0.0）
  default_pos_cov     : 位置协方差对角线值（默认 0.01）
  default_rot_cov     : 姿态协方差对角线值（默认 0.005）
"""

import math
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile, QoSReliabilityPolicy,
    QoSHistoryPolicy, QoSDurabilityPolicy
)

from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


# ──────────────────────────────────────────────────────────────────
#  协方差模板（6×6 行主序，36 元素，位置 xyz + 姿态 rpy）
# ──────────────────────────────────────────────────────────────────
def _make_default_covariance(pos_cov: float, rot_cov: float) -> list:
    """生成对角协方差矩阵，[x,y,z,rx,ry,rz] 各轴独立。"""
    cov = [0.0] * 36
    for i, val in enumerate([pos_cov, pos_cov, pos_cov,
                              rot_cov, rot_cov, rot_cov]):
        cov[i * 6 + i] = val
    return cov


def _is_zero_cov(cov) -> bool:
    """判断协方差是否全零（FAST-LIO2 未填充时的情况）。"""
    return all(abs(v) < 1e-9 for v in cov)


class OdomTfBridgeNode(Node):

    def __init__(self):
        super().__init__('odom_tf_bridge_node')

        # ── 参数声明 ─────────────────────────────────────────────
        self.declare_parameter('fastlio_odom_topic', '/Odometry')
        self.declare_parameter('odom_topic',         '/odom')
        self.declare_parameter('odom_frame',         'odom')
        self.declare_parameter('base_frame',         'base_link')
        self.declare_parameter('publish_tf',         True)

        # Go2: IMU 安装位置与 base_link（机体中心/肩部中点）的偏移
        # 通常 < 5 cm，默认设为 0（直接等价）
        self.declare_parameter('body_to_base_link_x', 0.0)
        self.declare_parameter('body_to_base_link_y', 0.0)
        self.declare_parameter('body_to_base_link_z', 0.0)

        # 协方差默认值
        self.declare_parameter('default_pos_cov', 0.01)
        self.declare_parameter('default_rot_cov', 0.005)

        # ── 读取参数 ─────────────────────────────────────────────
        self._in_topic   = self.get_parameter('fastlio_odom_topic').value
        self._out_topic  = self.get_parameter('odom_topic').value
        self._odom_frame = self.get_parameter('odom_frame').value
        self._base_frame = self.get_parameter('base_frame').value
        self._pub_tf     = self.get_parameter('publish_tf').value

        self._dx = float(self.get_parameter('body_to_base_link_x').value)
        self._dy = float(self.get_parameter('body_to_base_link_y').value)
        self._dz = float(self.get_parameter('body_to_base_link_z').value)

        pos_cov = float(self.get_parameter('default_pos_cov').value)
        rot_cov = float(self.get_parameter('default_rot_cov').value)
        self._default_cov = _make_default_covariance(pos_cov, rot_cov)

        # ── QoS ─────────────────────────────────────────────────
        # FAST-LIO2 以 BEST_EFFORT 发布 /Odometry，订阅端必须匹配
        sub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            durability=QoSDurabilityPolicy.VOLATILE,
            depth=10,
        )
        # NAV2 推荐 RELIABLE
        pub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            durability=QoSDurabilityPolicy.VOLATILE,
            depth=10,
        )

        # ── 发布器 / TF ─────────────────────────────────────────
        self._odom_pub = self.create_publisher(
            Odometry, self._out_topic, pub_qos)

        if self._pub_tf:
            self._tf_broadcaster = TransformBroadcaster(self)

        # ── 订阅器 ───────────────────────────────────────────────
        self._sub = self.create_subscription(
            Odometry, self._in_topic,
            self._odom_callback, sub_qos)

        self.get_logger().info(
            f'odom_tf_bridge_node 已启动\n'
            f'  输入  : {self._in_topic}  (camera_init → body)\n'
            f'  输出  : {self._out_topic}  ({self._odom_frame} → {self._base_frame})\n'
            f'  发布TF: {self._pub_tf}\n'
            f'  body→base偏移: [{self._dx:.3f}, {self._dy:.3f}, {self._dz:.3f}] m'
        )

    # ──────────────────────────────────────────────────────────────
    def _odom_callback(self, msg: Odometry):
        stamp = msg.header.stamp

        # ── 构建输出 Odometry ────────────────────────────────────
        odom_out = Odometry()
        odom_out.header.stamp    = stamp
        odom_out.header.frame_id = self._odom_frame     # odom
        odom_out.child_frame_id  = self._base_frame     # base_link

        # 位置：若有 body→base_link 偏移，在 body 坐标系下加上旋转后的平移
        # （通常偏移极小，直接加在全局坐标系也可）
        q = msg.pose.pose.orientation
        if abs(self._dx) + abs(self._dy) + abs(self._dz) > 1e-4:
            # 将偏移向量从 body 坐标系旋转到 world/odom 坐标系
            dx_w, dy_w, dz_w = _rotate_vector_by_quat(
                self._dx, self._dy, self._dz, q)
        else:
            dx_w = dy_w = dz_w = 0.0

        odom_out.pose.pose.position.x = msg.pose.pose.position.x + dx_w
        odom_out.pose.pose.position.y = msg.pose.pose.position.y + dy_w
        odom_out.pose.pose.position.z = msg.pose.pose.position.z + dz_w
        odom_out.pose.pose.orientation = q

        # 速度（body 坐标系下，直接透传）
        odom_out.twist.twist = msg.twist.twist

        # 协方差：FAST-LIO2 不填充时补充默认值
        if _is_zero_cov(msg.pose.covariance):
            odom_out.pose.covariance = self._default_cov
        else:
            odom_out.pose.covariance = msg.pose.covariance

        if _is_zero_cov(msg.twist.covariance):
            odom_out.twist.covariance = self._default_cov
        else:
            odom_out.twist.covariance = msg.twist.covariance

        self._odom_pub.publish(odom_out)

        # ── 广播 TF: odom → base_link ────────────────────────────
        if self._pub_tf:
            tf = TransformStamped()
            tf.header.stamp    = stamp
            tf.header.frame_id = self._odom_frame    # odom
            tf.child_frame_id  = self._base_frame    # base_link

            tf.transform.translation.x = odom_out.pose.pose.position.x
            tf.transform.translation.y = odom_out.pose.pose.position.y
            tf.transform.translation.z = odom_out.pose.pose.position.z
            tf.transform.rotation      = q

            self._tf_broadcaster.sendTransform(tf)


# ──────────────────────────────────────────────────────────────────
#  辅助：四元数旋转向量（用于 body→base_link 偏移变换）
# ──────────────────────────────────────────────────────────────────
def _rotate_vector_by_quat(vx, vy, vz, q):
    """将向量 (vx,vy,vz) 按四元数 q 旋转（q 表示 body→world 旋转）。"""
    # q * v * q^{-1}，使用纯四元数乘法
    qx, qy, qz, qw = q.x, q.y, q.z, q.w
    # 旋转矩阵中第一行、第二行、第三行与 v 点乘
    wx = (1 - 2*(qy*qy + qz*qz))*vx + 2*(qx*qy - qz*qw)*vy + 2*(qx*qz + qy*qw)*vz
    wy = 2*(qx*qy + qz*qw)*vx + (1 - 2*(qx*qx + qz*qz))*vy + 2*(qy*qz - qx*qw)*vz
    wz = 2*(qx*qz - qy*qw)*vx + 2*(qy*qz + qx*qw)*vy + (1 - 2*(qx*qx + qy*qy))*vz
    return wx, wy, wz


# ──────────────────────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)
    node = OdomTfBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
