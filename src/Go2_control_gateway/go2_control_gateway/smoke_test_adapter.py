"""Minimal ROS 2 I/O used by the guarded motion smoke test."""

from __future__ import annotations

from copy import deepcopy
import json
import threading


try:
    import rclpy
    from action_msgs.msg import GoalStatusArray
    from geometry_msgs.msg import Twist
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:
    rclpy = None


NAV_STATUS_NAMES = {
    0: "UNKNOWN",
    1: "ACCEPTED",
    2: "EXECUTING",
    3: "CANCELING",
    4: "SUCCEEDED",
    5: "CANCELED",
    6: "ABORTED",
}


class RclpySmokeTestAdapter:
    """Expose only gateway status, Nav2 state, and manual velocity."""

    def __init__(self) -> None:
        if rclpy is None:
            raise RuntimeError("ROS 2 rclpy is required for the smoke test")
        self._owns_context = not rclpy.ok()
        if self._owns_context:
            rclpy.init()

        self._lock = threading.RLock()
        self._state = {
            "gateway_link": "offline",
            "last_ack_age_sec": None,
            "nav2_status": "IDLE",
        }
        self._node = Node("go2_motion_smoke_test_adapter")
        self._manual_publisher = self._node.create_publisher(
            Twist, "/go2/manual_cmd_vel", 10
        )
        self._subscriptions = [
            self._node.create_subscription(
                String,
                "/go2_cmd_vel_gateway/status",
                self._gateway_status_callback,
                10,
            ),
            self._node.create_subscription(
                GoalStatusArray,
                "/navigate_to_pose/_action/status",
                self._nav_status_callback,
                10,
            ),
        ]
        self._executor = MultiThreadedExecutor(num_threads=2)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            name="go2-motion-smoke-test-ros",
            daemon=True,
        )
        self._spin_thread.start()
        self._closed = False

    def get_state(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def manual_command(self, vx: float, vy: float, vyaw: float) -> None:
        message = Twist()
        message.linear.x = float(vx)
        message.linear.y = float(vy)
        message.angular.z = float(vyaw)
        self._manual_publisher.publish(message)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.manual_command(0.0, 0.0, 0.0)
        finally:
            self._executor.shutdown(timeout_sec=1.0)
            self._spin_thread.join(timeout=1.0)
            self._node.destroy_node()
            if self._owns_context and rclpy.ok():
                rclpy.shutdown()
            self._closed = True

    def _gateway_status_callback(self, message) -> None:
        try:
            status = json.loads(message.data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return
        with self._lock:
            if status.get("gateway_link") in {"online", "offline"}:
                self._state["gateway_link"] = status["gateway_link"]
            ack_age = status.get("last_ack_age_sec")
            if ack_age is None or isinstance(ack_age, (int, float)):
                self._state["last_ack_age_sec"] = ack_age

    def _nav_status_callback(self, message) -> None:
        statuses = [int(item.status) for item in message.status_list]
        if any(status == 2 for status in statuses):
            value = "EXECUTING"
        elif any(status == 3 for status in statuses):
            value = "CANCELING"
        elif any(status == 1 for status in statuses):
            value = "ACCEPTED"
        elif statuses:
            value = NAV_STATUS_NAMES.get(statuses[-1], "UNKNOWN")
        else:
            value = "IDLE"
        with self._lock:
            self._state["nav2_status"] = value
