"""Disabled-by-default direct ROS 2 DDS fallback for the Go2 Sport API."""

from __future__ import annotations

import json
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger
from unitree_api.msg import Request
from unitree_go.msg import LowState, SportModeState


API_STOP_MOVE = 1003
API_STAND_UP = 1004
API_STAND_DOWN = 1005
API_MOVE = 1008
MODE_NAMES = {
    0: "idle",
    1: "balance_stand",
    2: "pose",
    3: "locomotion",
    5: "lie_down",
    6: "joint_lock",
    7: "damping",
    8: "recovery_stand",
    10: "sit",
}
STANDING_MODES = {0, 1, 2, 3, 8}
LYING_MODES = {5, 7}


class DirectSportBridge(Node):
    """Legacy diagnostic fallback; the deployed service remains disabled."""

    def __init__(self) -> None:
        super().__init__("go2_direct_sport_bridge")
        group = ReentrantCallbackGroup()
        self.declare_parameter("send_hz", 20.0)
        self.declare_parameter("command_timeout_sec", 0.5)
        self.declare_parameter("state_timeout_sec", 2.0)
        self.declare_parameter("max_vx", 0.8)
        self.declare_parameter("max_vy", 0.5)
        self.declare_parameter("max_vyaw", 1.0)

        self._lock = threading.RLock()
        self._last_manual = None
        self._last_nav = None
        self._last_manual_at = 0.0
        self._last_nav_at = 0.0
        self._last_state_at = 0.0
        self._mode = None
        self._soc = None
        self._moving = False

        self._sport_pub = self.create_publisher(Request, "/api/sport/request", 10)
        self._status_pub = self.create_publisher(
            String, "/go2_cmd_vel_gateway/status", 10
        )
        self.create_subscription(
            Twist, "/cmd_vel", self._on_nav, 10, callback_group=group
        )
        self.create_subscription(
            Twist,
            "/go2/manual_cmd_vel",
            self._on_manual,
            10,
            callback_group=group,
        )
        self.create_subscription(
            SportModeState,
            "/sportmodestate",
            self._on_state,
            10,
            callback_group=group,
        )
        self.create_subscription(
            LowState, "/lowstate", self._on_lowstate, 10, callback_group=group
        )
        self.create_service(
            Trigger,
            "/go2_cmd_vel_gateway/stand_up",
            self._on_stand_up,
            callback_group=group,
        )
        self.create_service(
            Trigger,
            "/go2_cmd_vel_gateway/stand_down",
            self._on_stand_down,
            callback_group=group,
        )
        self.create_service(
            Trigger,
            "/go2_cmd_vel_gateway/emergency_stop",
            self._on_estop,
            callback_group=group,
        )
        hz = float(self.get_parameter("send_hz").value)
        self.create_timer(1.0 / hz, self._tick, callback_group=group)
        self.get_logger().info(
            "Direct Unitree DDS fallback ready; state and command timeouts active"
        )

    @staticmethod
    def _clamp(value: float, limit: float) -> float:
        return max(-limit, min(limit, float(value)))

    def _send(self, api_id: int, parameters: dict) -> None:
        message = Request()
        message.header.identity.id = time.monotonic_ns()
        message.header.identity.api_id = api_id
        message.header.lease.id = 0
        message.header.policy.priority = 0
        message.header.policy.noreply = True
        message.parameter = json.dumps(parameters, separators=(",", ":"))
        self._sport_pub.publish(message)

    def _stop(self) -> None:
        self._send(API_STOP_MOVE, {})
        self._moving = False

    def _on_nav(self, message: Twist) -> None:
        with self._lock:
            self._last_nav = message
            self._last_nav_at = time.monotonic()

    def _on_manual(self, message: Twist) -> None:
        with self._lock:
            self._last_manual = message
            self._last_manual_at = time.monotonic()

    def _on_state(self, message: SportModeState) -> None:
        with self._lock:
            self._mode = int(message.mode)
            self._last_state_at = time.monotonic()

    def _on_lowstate(self, message: LowState) -> None:
        with self._lock:
            self._soc = int(message.bms_state.soc)

    def _posture(self, api_id: int, label: str, response):
        with self._lock:
            self._stop()
            self._send(api_id, {})
        response.success = True
        response.message = label
        return response

    def _on_stand_up(self, _request, response):
        return self._posture(API_STAND_UP, "StandUp sent", response)

    def _on_stand_down(self, _request, response):
        return self._posture(API_STAND_DOWN, "StandDown sent", response)

    def _on_estop(self, _request, response):
        with self._lock:
            self._last_manual = self._last_nav = None
            self._stop()
        response.success = True
        response.message = "Emergency StopMove sent; control locked"
        return response

    def _tick(self) -> None:
        now = time.monotonic()
        timeout = float(self.get_parameter("command_timeout_sec").value)
        with self._lock:
            command = None
            if self._last_manual is not None and now - self._last_manual_at <= timeout:
                command = self._last_manual
            elif self._last_nav is not None and now - self._last_nav_at <= timeout:
                command = self._last_nav

            state_age = (
                None
                if not self._last_state_at
                else max(0.0, now - self._last_state_at)
            )
            online = state_age is not None and state_age <= float(
                self.get_parameter("state_timeout_sec").value
            )

            if online and command is not None:
                x = self._clamp(
                    command.linear.x, float(self.get_parameter("max_vx").value)
                )
                y = self._clamp(
                    command.linear.y, float(self.get_parameter("max_vy").value)
                )
                yaw = self._clamp(
                    command.angular.z, float(self.get_parameter("max_vyaw").value)
                )
                if any(abs(value) > 1e-4 for value in (x, y, yaw)):
                    self._send(API_MOVE, {"x": x, "y": y, "z": yaw})
                    self._moving = True
                elif self._moving:
                    self._stop()
            elif self._moving:
                self._stop()

            status = {
                "gateway_link": "online" if online else "offline",
                "control_ready": online,
                "nav_active": self._last_nav is not None
                and now - self._last_nav_at <= timeout,
                "last_ack_age_sec": (
                    None if state_age is None else round(state_age, 3)
                ),
                "send_hz": float(self.get_parameter("send_hz").value),
                "posture": (
                    "standing"
                    if self._mode in STANDING_MODES
                    else "lying"
                    if self._mode in LYING_MODES
                    else "unknown"
                ),
                "motion_mode": MODE_NAMES.get(self._mode, "unknown"),
                "sport_mode": self._mode,
                "battery_soc": self._soc,
                "transport": "unitree_ros2_dds",
            }
            output = String()
            output.data = json.dumps(
                status, ensure_ascii=False, separators=(",", ":")
            )
            self._status_pub.publish(output)

    def destroy_node(self):
        with self._lock:
            for _ in range(3):
                self._stop()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DirectSportBridge()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
