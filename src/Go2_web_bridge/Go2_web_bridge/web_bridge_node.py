#!/usr/bin/env python3
"""
Go2 WebSocket Bridge Node — rosbridge 协议版

上行（Robot → Server）:
  /odom                            → nav_msgs/msg/Odometry
  /localization                    → nav_msgs/msg/Odometry
  /navigate_to_pose/_action/status → action_msgs/msg/GoalStatusArray

下行（Server → Robot）:
  /goal_pose    → 发布到 ROS /goal_pose（Nav2 接收）
  /initialpose  → 发布到 ROS /initialpose
  /tts_text     → 发布到 ROS /tts_text

心跳：每 30 秒发 {"action": "ping"}
"""

import json
import math
import queue
import threading
import asyncio

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from std_msgs.msg import String
from action_msgs.msg import GoalStatusArray

try:
    import websockets
    import websockets.exceptions
except ImportError:
    raise RuntimeError("请安装 websockets 库: pip3 install websockets")

# ── ANSI 颜色 ────────────────────────────────────────────────────
_G = '\033[0;32m'   # 绿色：上行（发送）
_R = '\033[0;31m'   # 红色：下行（接收）
_C = '\033[0;36m'   # 青色：连接状态
_Y = '\033[1;33m'   # 黄色：警告
_NC = '\033[0m'     # 重置

PING_INTERVAL = 30.0

# GoalStatus 状态码 → 人类可读
_STATUS_NAMES = {
    0: 'UNKNOWN', 1: 'ACCEPTED', 2: 'EXECUTING',
    3: 'CANCELING', 4: 'SUCCEEDED', 5: 'CANCELED', 6: 'ABORTED',
}


def cprint(color: str, msg: str):
    """带颜色的终端输出（同时会进入 ROS launch 捕获的日志）。"""
    print(f'{color}{msg}{_NC}', flush=True)


class WebBridgeNode(Node):
    def __init__(self):
        super().__init__('web_bridge_node')

        # ── 参数 ──────────────────────────────────────────────────
        self.declare_parameter('server_url',
            'ws://121.40.212.85:30100/ws/source?token=c7e4a9d2b5f1c8e3a6d4b7f2c9a1e5d8&source_id=dog_001')
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter('localization_topic', '/localization')
        self.declare_parameter('odom_publish_hz', 2.0)
        self.declare_parameter('nav_status_publish_hz', 1.0)
        self.declare_parameter('reconnect_delay_sec', 5.0)

        self.server_url = self.get_parameter('server_url').value
        odom_topic = self.get_parameter('odom_topic').value
        loc_topic = self.get_parameter('localization_topic').value
        self.odom_hz = self.get_parameter('odom_publish_hz').value
        self.nav_hz = self.get_parameter('nav_status_publish_hz').value
        self.reconnect_delay = self.get_parameter('reconnect_delay_sec').value

        # ── 状态缓存 ──────────────────────────────────────────────
        self._odom_msg: Odometry = None
        self._loc_msg: Odometry = None
        self._nav_status_msg: GoalStatusArray = None
        self._lock = threading.Lock()
        self._last_nav_status_hash = None   # 仅状态变化时上报

        # 线程安全队列（ROS 线程写，asyncio 线程读）
        self._send_queue: queue.Queue = queue.Queue(maxsize=60)

        # ── ROS 订阅 ─────────────────────────────────────────────
        reliable_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            depth=10,
        )

        self.sub_odom = self.create_subscription(
            Odometry, odom_topic, self._odom_cb, reliable_qos)
        self.sub_loc = self.create_subscription(
            Odometry, loc_topic, self._loc_cb, reliable_qos)
        self.sub_nav_status = self.create_subscription(
            GoalStatusArray,
            '/navigate_to_pose/_action/status',
            self._nav_status_cb,
            reliable_qos)

        # ── ROS 发布 ─────────────────────────────────────────────
        self.pub_goal = self.create_publisher(PoseStamped, '/goal_pose', 10)
        self.pub_initialpose = self.create_publisher(
            PoseWithCovarianceStamped, '/initialpose', 10)
        self.pub_tts = self.create_publisher(String, '/tts_text', 10)

        # ── 定时器 ────────────────────────────────────────────────
        self.create_timer(1.0 / self.odom_hz, self._timer_odom)
        self.create_timer(1.0 / self.nav_hz, self._timer_nav_status)

        # ── WebSocket 线程 ────────────────────────────────────────
        self._ws_thread = threading.Thread(target=self._ws_thread_main, daemon=True)
        self._ws_thread.start()

        cprint(_C, f'[WebBridge] 启动，服务器: {self.server_url}')
        cprint(_C, f'[WebBridge] 上行话题: {odom_topic}, {loc_topic}, /navigate_to_pose/_action/status')

    # ── ROS 订阅回调 ─────────────────────────────────────────────

    def _odom_cb(self, msg: Odometry):
        with self._lock:
            self._odom_msg = msg

    def _loc_cb(self, msg: Odometry):
        with self._lock:
            self._loc_msg = msg

    def _nav_status_cb(self, msg: GoalStatusArray):
        with self._lock:
            self._nav_status_msg = msg
        # 状态变化时立刻上报（不等定时器）
        status_hash = tuple(s.status for s in msg.status_list)
        if status_hash != self._last_nav_status_hash:
            self._last_nav_status_hash = status_hash
            self._enqueue_broadcast(
                '/navigate_to_pose/_action/status',
                'action_msgs/msg/GoalStatusArray',
                self._goal_status_array_to_rosbridge(msg),
                log_label=self._format_nav_status(msg),
            )

    # ── 定时器 ───────────────────────────────────────────────────

    def _timer_odom(self):
        with self._lock:
            msg = self._odom_msg
        if msg is None:
            return
        p = msg.pose.pose.position
        label = f'x={p.x:.2f} y={p.y:.2f}'
        self._enqueue_broadcast('/odom', 'nav_msgs/msg/Odometry',
                                self._odom_to_rosbridge(msg), log_label=label)

    def _timer_nav_status(self):
        with self._lock:
            msg = self._loc_msg
        if msg is None:
            return
        p = msg.pose.pose.position
        label = f'x={p.x:.2f} y={p.y:.2f}'
        self._enqueue_broadcast('/localization', 'nav_msgs/msg/Odometry',
                                self._odom_to_rosbridge(msg), log_label=label)

    # ── 消息序列化 ───────────────────────────────────────────────

    def _enqueue_broadcast(self, topic: str, msg_type: str,
                           msg_dict: dict, log_label: str = ''):
        payload = json.dumps({
            'action': 'broadcast',
            'message': {
                'op': 'publish',
                'topic': topic,
                'type': msg_type,
                'msg': msg_dict,
            },
        })
        cprint(_G, f'[TX] {topic}  {log_label}')
        try:
            self._send_queue.put_nowait(payload)
        except queue.Full:
            try:
                self._send_queue.get_nowait()
                self._send_queue.put_nowait(payload)
            except queue.Empty:
                pass

    @staticmethod
    def _odom_to_rosbridge(msg: Odometry) -> dict:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        v = msg.twist.twist.linear
        w = msg.twist.twist.angular
        return {
            'header': {
                'stamp': {'sec': msg.header.stamp.sec,
                          'nanosec': msg.header.stamp.nanosec},
                'frame_id': msg.header.frame_id,
            },
            'child_frame_id': msg.child_frame_id,
            'pose': {
                'pose': {
                    'position': {'x': p.x, 'y': p.y, 'z': p.z},
                    'orientation': {'x': q.x, 'y': q.y, 'z': q.z, 'w': q.w},
                },
                'covariance': list(msg.pose.covariance),
            },
            'twist': {
                'twist': {
                    'linear': {'x': v.x, 'y': v.y, 'z': v.z},
                    'angular': {'x': w.x, 'y': w.y, 'z': w.z},
                },
                'covariance': list(msg.twist.covariance),
            },
        }

    @staticmethod
    def _goal_status_array_to_rosbridge(msg: GoalStatusArray) -> dict:
        return {
            'status_list': [
                {
                    'goal_info': {
                        'goal_id': {'uuid': list(s.goal_info.goal_id.uuid)},
                        'stamp': {
                            'sec': s.goal_info.stamp.sec,
                            'nanosec': s.goal_info.stamp.nanosec,
                        },
                    },
                    'status': s.status,
                }
                for s in msg.status_list
            ]
        }

    @staticmethod
    def _format_nav_status(msg: GoalStatusArray) -> str:
        if not msg.status_list:
            return '(no active goals)'
        parts = [_STATUS_NAMES.get(s.status, str(s.status))
                 for s in msg.status_list]
        return ' | '.join(parts)

    # ── 下行消息处理 ─────────────────────────────────────────────

    def _handle_server_message(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            cprint(_Y, f'[RX] 非 JSON 消息: {raw[:80]}')
            return

        # 心跳响应，忽略
        if 'ok' in data or data.get('action') == 'pong':
            return

        # 格式一：小程序下发 miniprogram_push
        if data.get('type') == 'miniprogram_push':
            self._handle_miniprogram_push(data.get('message', {}))
            return

        # 格式二：调试页直接发 topic/msg
        inner = data.get('message', {})
        topic = inner.get('topic', '')
        msg_data = inner.get('msg', {})

        if not topic:
            cprint(_Y, f'[RX] 无法识别的消息格式: {str(data)[:200]}')
            return

        cprint(_R, f'[RX] topic={topic}  msg={json.dumps(msg_data, ensure_ascii=False)[:200]}')

        if topic == '/goal_pose':
            self._handle_goal_pose(msg_data)
        elif topic == '/initialpose':
            self._handle_initialpose(msg_data)
        elif topic == '/tts_text':
            self._handle_tts(msg_data)
        else:
            cprint(_Y, f'[RX] 未处理 topic: {topic}')

    def _handle_miniprogram_push(self, message: dict):
        # 小程序发的是 {"message": {"topic": ..., "msg": ...}}，服务端转发后多了一层
        nested = message.get('message', {})
        topic = nested.get('topic', '')
        msg_data = nested.get('msg', {})
        if not topic:
            cprint(_Y, f'[RX] miniprogram_push 缺少 topic: {str(message)[:200]}')
            return
        cprint(_R, f'[RX] miniprogram_push → topic={topic}  msg={json.dumps(msg_data, ensure_ascii=False)[:200]}')
        if topic == '/goal_pose':
            self._handle_goal_pose(msg_data)
        elif topic == '/initialpose':
            self._handle_initialpose(msg_data)
        elif topic == '/tts_text':
            self._handle_tts(msg_data)
        else:
            cprint(_Y, f'[RX] 未处理 topic: {topic}')

    def _handle_goal_pose(self, msg_data: dict):
        try:
            pose = msg_data.get('pose', {})
            pos = pose.get('position', {})
            ori = pose.get('orientation', {})

            goal = PoseStamped()
            goal.header.frame_id = msg_data.get('header', {}).get('frame_id', 'map')
            goal.header.stamp = self.get_clock().now().to_msg()
            goal.pose.position.x = float(pos.get('x', 0.0))
            goal.pose.position.y = float(pos.get('y', 0.0))
            goal.pose.position.z = float(pos.get('z', 0.0))
            goal.pose.orientation.x = float(ori.get('x', 0.0))
            goal.pose.orientation.y = float(ori.get('y', 0.0))
            goal.pose.orientation.z = float(ori.get('z', 0.0))
            goal.pose.orientation.w = float(ori.get('w', 1.0))

            yaw = math.degrees(math.atan2(
                2.0 * (goal.pose.orientation.w * goal.pose.orientation.z),
                1.0 - 2.0 * goal.pose.orientation.z ** 2
            ))
            cprint(_R, f'[RX] 导航目标已发布: x={goal.pose.position.x:.3f} '
                       f'y={goal.pose.position.y:.3f} yaw={yaw:.1f}°')
            self.pub_goal.publish(goal)
        except Exception as e:
            cprint(_Y, f'[RX] goal_pose 解析失败: {e}')

    def _handle_initialpose(self, msg_data: dict):
        try:
            pose = msg_data.get('pose', {}).get('pose', {})
            pos = pose.get('position', {})
            ori = pose.get('orientation', {})
            cov = msg_data.get('pose', {}).get('covariance', [0.0] * 36)

            ip = PoseWithCovarianceStamped()
            ip.header.frame_id = msg_data.get('header', {}).get('frame_id', 'map')
            ip.header.stamp = self.get_clock().now().to_msg()
            ip.pose.pose.position.x = float(pos.get('x', 0.0))
            ip.pose.pose.position.y = float(pos.get('y', 0.0))
            ip.pose.pose.position.z = float(pos.get('z', 0.0))
            ip.pose.pose.orientation.x = float(ori.get('x', 0.0))
            ip.pose.pose.orientation.y = float(ori.get('y', 0.0))
            ip.pose.pose.orientation.z = float(ori.get('z', 0.0))
            ip.pose.pose.orientation.w = float(ori.get('w', 1.0))
            ip.pose.covariance = list(cov[:36]) + [0.0] * max(0, 36 - len(cov[:36]))

            cprint(_R, f'[RX] 初始位姿已发布到 /initialpose')
            self.pub_initialpose.publish(ip)
        except Exception as e:
            cprint(_Y, f'[RX] initialpose 解析失败: {e}')

    def _handle_tts(self, msg_data: dict):
        text = msg_data.get('data', '')
        if not text:
            return
        cprint(_R, f'[RX] TTS 文本: {text}')
        msg = String()
        msg.data = text
        self.pub_tts.publish(msg)

    # ── WebSocket 事件循环 ────────────────────────────────────────

    def _ws_thread_main(self):
        asyncio.run(self._ws_main())

    async def _ws_main(self):
        while rclpy.ok():
            try:
                await self._ws_connect_and_run()
            except Exception as e:
                cprint(_Y, f'[WebBridge] 断开: {e}，{self.reconnect_delay:.0f}s 后重连...')
            await asyncio.sleep(self.reconnect_delay)

    async def _ws_connect_and_run(self):
        cprint(_C, f'[WebBridge] 正在连接 {self.server_url} ...')
        async with websockets.connect(
            self.server_url,
            ping_interval=None,
            close_timeout=5,
        ) as ws:
            cprint(_C, '[WebBridge] 连接成功 ✓')
            await asyncio.gather(
                self._ws_sender(ws),
                self._ws_receiver(ws),
                self._ws_keepalive(ws),
            )

    async def _ws_sender(self, ws):
        loop = asyncio.get_event_loop()
        while True:
            payload = await loop.run_in_executor(None, self._send_queue.get)
            await ws.send(payload)

    async def _ws_receiver(self, ws):
        loop = asyncio.get_event_loop()
        async for message in ws:
            await loop.run_in_executor(None, self._handle_server_message, message)

    async def _ws_keepalive(self, ws):
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await ws.send(json.dumps({'action': 'ping'}))
            except Exception:
                break


def main(args=None):
    rclpy.init(args=args)
    node = WebBridgeNode()
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
