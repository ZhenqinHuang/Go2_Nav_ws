"""Narrow ROS 2 adapter used by the authenticated console backend.

The browser never supplies topic or service names.  Only the fixed operations
defined here are reachable through the HTTP API.
"""

from __future__ import annotations

from copy import deepcopy
import json
import threading
import time


def _resolve_multi_navigation_action(nav2_actions):
    """Return the newest multi-pose action supported by this Nav2 release."""
    action = getattr(nav2_actions, "NavigateThroughPoses", None)
    if action is not None:
        return action, "/navigate_through_poses"
    action = getattr(nav2_actions, "FollowWaypoints", None)
    if action is not None:
        return action, "/follow_waypoints"
    raise ImportError("Nav2 does not provide a multi-pose navigation action")


try:
    import rclpy
    from action_msgs.msg import GoalInfo, GoalStatusArray
    from action_msgs.srv import CancelGoal
    from geometry_msgs.msg import (
        PoseStamped,
        PoseWithCovarianceStamped,
        Twist,
    )
    from nav2_msgs import action as nav2_actions
    from nav_msgs.msg import Odometry
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
    from std_srvs.srv import Trigger
    from unitree_api.msg import Request
    from unitree_go.msg import LowState, SportModeState

    NavigateToPose = nav2_actions.NavigateToPose
    MultiNavigationAction, MULTI_NAVIGATION_ACTION_NAME = (
        _resolve_multi_navigation_action(nav2_actions)
    )
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

SPORT_API_STAND_UP = 1004
SPORT_API_STAND_DOWN = 1005
SPORT_API_RECOVERY_STAND = 1006


class DemoRosAdapter:
    """Motion-free adapter for local UI checks and operator training."""

    def __init__(self, *, nav2_status: str = "IDLE") -> None:
        self._lock = threading.RLock()
        self._state = {
            "battery_percent": 78,
            "control_ready": True,
            "gateway_link": "online",
            "last_ack_age_sec": 0.0,
            "motion_mode": "demo",
            "velocity": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
            "odometry": {"x": 1.24, "y": -0.38, "yaw": 0.12},
            "nav2_status": str(nav2_status).upper(),
        }

    def get_state(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def stand_up(self) -> bool:
        with self._lock:
            self._state["motion_mode"] = "standing"
        return True

    def stand_down(self) -> bool:
        with self._lock:
            self._state["motion_mode"] = "lying"
        return True

    def recovery_stand(self) -> bool:
        with self._lock:
            self._state["motion_mode"] = "standing"
        return True

    def emergency_stop(self) -> bool:
        return self.manual_command(0.0, 0.0, 0.0)

    def manual_command(self, vx: float, vy: float, vyaw: float) -> bool:
        with self._lock:
            self._state["velocity"] = {
                "vx": float(vx),
                "vy": float(vy),
                "vyaw": float(vyaw),
            }
        return True

    def cancel_navigation(self) -> bool:
        with self._lock:
            self._state["nav2_status"] = "IDLE"
        return True

    def navigate_to_pose(self, x: float, y: float, yaw: float) -> bool:
        with self._lock:
            self._state["nav2_status"] = "ACCEPTED"
        return True

    def navigate_through_poses(self, poses: list[dict[str, float]]) -> bool:
        with self._lock:
            self._state["nav2_status"] = "ACCEPTED"
        return bool(poses)

    def set_initial_pose(self, x: float, y: float, yaw: float) -> bool:
        with self._lock:
            self._state["odometry"] = {"x": x, "y": y, "yaw": yaw}
        return True

    def close(self) -> None:
        self.manual_command(0.0, 0.0, 0.0)


class RclpyRosAdapter:
    """Owns a small ROS node and exposes fixed synchronous operations."""

    def __init__(self) -> None:
        if rclpy is None:
            raise RuntimeError("ROS 2 and unitree_go messages are required")
        self._owns_context = not rclpy.ok()
        if self._owns_context:
            rclpy.init()

        self._lock = threading.RLock()
        self._state = {
            "battery_percent": None,
            "control_ready": False,
            "gateway_link": "offline",
            "last_ack_age_sec": None,
            "motion_mode": "unknown",
            "velocity": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
            "odometry": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "nav2_status": "IDLE",
        }
        self._node = Node("go2_console_ros_adapter")
        best_effort = QoSProfile(
            depth=10, reliability=ReliabilityPolicy.BEST_EFFORT
        )

        self._manual_publisher = self._node.create_publisher(
            Twist, "/go2/manual_cmd_vel", 10
        )
        self._sport_request_publisher = self._node.create_publisher(
            Request, "/api/sport/request", 10
        )
        self._emergency_stop_client = self._node.create_client(
            Trigger, "/go2_cmd_vel_gateway/emergency_stop"
        )
        self._cancel_client = self._node.create_client(
            CancelGoal, "/navigate_to_pose/_action/cancel_goal"
        )
        self._navigate_to_pose_client = ActionClient(
            self._node, NavigateToPose, "/navigate_to_pose"
        )
        self._navigate_through_poses_client = ActionClient(
            self._node, MultiNavigationAction, MULTI_NAVIGATION_ACTION_NAME
        )
        self._initial_pose_publisher = self._node.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10
        )
        self._subscriptions = [
            self._node.create_subscription(
                String,
                "/go2_cmd_vel_gateway/status",
                self._gateway_status_callback,
                10,
            ),
            self._node.create_subscription(
                Odometry, "/odom", self._odometry_callback, 10
            ),
            self._node.create_subscription(
                GoalStatusArray,
                "/navigate_to_pose/_action/status",
                self._nav_status_callback,
                10,
            ),
            self._node.create_subscription(
                LowState, "/lowstate", self._low_state_callback, best_effort
            ),
            self._node.create_subscription(
                SportModeState,
                "/sportmodestate",
                self._sport_state_callback,
                best_effort,
            ),
        ]

        self._executor = MultiThreadedExecutor(num_threads=2)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            name="go2-console-ros",
            daemon=True,
        )
        self._spin_thread.start()
        self._closed = False

    def get_state(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def stand_up(self) -> bool:
        return self._publish_sport_request(SPORT_API_STAND_UP)

    def stand_down(self) -> bool:
        return self._publish_sport_request(SPORT_API_STAND_DOWN)

    def recovery_stand(self) -> bool:
        return self._publish_sport_request(SPORT_API_RECOVERY_STAND)

    def emergency_stop(self) -> bool:
        self.manual_command(0.0, 0.0, 0.0)
        response = self._call_service(
            self._emergency_stop_client, Trigger.Request(), timeout_sec=1.0
        )
        return bool(response and response.success)

    def manual_command(self, vx: float, vy: float, vyaw: float) -> bool:
        message = Twist()
        message.linear.x = float(vx)
        message.linear.y = float(vy)
        message.angular.z = float(vyaw)
        self._manual_publisher.publish(message)
        return True

    def _publish_sport_request(self, api_id: int) -> bool:
        message = Request()
        message.header.identity.api_id = int(api_id)
        self._sport_request_publisher.publish(message)
        return True

    def cancel_navigation(self) -> bool:
        request = CancelGoal.Request()
        request.goal_info = GoalInfo()
        response = self._call_service(
            self._cancel_client, request, timeout_sec=1.0
        )
        return bool(
            response
            and response.return_code == CancelGoal.Response.ERROR_NONE
        )

    def navigate_to_pose(self, x: float, y: float, yaw: float) -> bool:
        goal = NavigateToPose.Goal()
        goal.pose = self._pose_stamped(x, y, yaw)
        return self._send_action_goal(self._navigate_to_pose_client, goal)

    def navigate_through_poses(self, poses: list[dict[str, float]]) -> bool:
        goal = MultiNavigationAction.Goal()
        goal.poses = [
            self._pose_stamped(pose["x"], pose["y"], pose["yaw"])
            for pose in poses
        ]
        return self._send_action_goal(
            self._navigate_through_poses_client, goal
        )

    def set_initial_pose(self, x: float, y: float, yaw: float) -> bool:
        message = PoseWithCovarianceStamped()
        message.header.frame_id = "map"
        message.header.stamp = self._node.get_clock().now().to_msg()
        pose = self._pose_stamped(x, y, yaw).pose
        message.pose.pose = pose
        message.pose.covariance[0] = 0.25
        message.pose.covariance[7] = 0.25
        message.pose.covariance[35] = 0.06853891945200942
        self._initial_pose_publisher.publish(message)
        return True

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

    def _call_service(self, client, request, *, timeout_sec: float):
        if not client.wait_for_service(timeout_sec=min(0.5, timeout_sec)):
            return None
        future = client.call_async(request)
        deadline = time.monotonic() + timeout_sec
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not future.done():
            return None
        try:
            return future.result()
        except Exception:
            return None

    def _send_action_goal(self, client, goal, *, timeout_sec: float = 2.0):
        if not client.wait_for_server(timeout_sec=min(0.5, timeout_sec)):
            return False
        future = client.send_goal_async(goal)
        result = self._wait_future(future, timeout_sec=timeout_sec)
        if result is None or not result.accepted:
            return False
        with self._lock:
            self._state["nav2_status"] = "ACCEPTED"
        return True

    @staticmethod
    def _wait_future(future, *, timeout_sec: float):
        deadline = time.monotonic() + timeout_sec
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not future.done():
            return None
        try:
            return future.result()
        except Exception:
            return None

    def _pose_stamped(self, x: float, y: float, yaw: float):
        import math

        message = PoseStamped()
        message.header.frame_id = "map"
        message.header.stamp = self._node.get_clock().now().to_msg()
        message.pose.position.x = float(x)
        message.pose.position.y = float(y)
        message.pose.orientation.z = math.sin(float(yaw) / 2.0)
        message.pose.orientation.w = math.cos(float(yaw) / 2.0)
        return message

    def _gateway_status_callback(self, message) -> None:
        try:
            status = json.loads(message.data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return
        with self._lock:
            if status.get("gateway_link") in {"online", "offline"}:
                self._state["gateway_link"] = status["gateway_link"]
            if isinstance(status.get("control_ready"), bool):
                self._state["control_ready"] = status["control_ready"]
            ack_age = status.get("last_ack_age_sec")
            if ack_age is None or isinstance(ack_age, (int, float)):
                self._state["last_ack_age_sec"] = ack_age
            posture = status.get("posture")
            if posture in {"standing", "lying"}:
                self._state["motion_mode"] = posture
            battery_soc = status.get("battery_soc")
            if isinstance(battery_soc, (int, float)) and 0 <= battery_soc <= 100:
                self._state["battery_percent"] = int(battery_soc)

    def _odometry_callback(self, message) -> None:
        pose = message.pose.pose
        orientation = pose.orientation
        import math

        yaw = math.atan2(
            2.0
            * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            ),
            1.0
            - 2.0
            * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            ),
        )
        with self._lock:
            self._state["odometry"] = {
                "x": float(pose.position.x),
                "y": float(pose.position.y),
                "yaw": yaw,
            }
            self._state["velocity"] = {
                "vx": float(message.twist.twist.linear.x),
                "vy": float(message.twist.twist.linear.y),
                "vyaw": float(message.twist.twist.angular.z),
            }

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

    def _low_state_callback(self, message) -> None:
        battery = None
        bms_state = getattr(message, "bms_state", None)
        if bms_state is not None:
            battery = getattr(bms_state, "soc", None)
        if battery is None:
            battery = getattr(message, "soc", None)
        if battery is not None:
            with self._lock:
                self._state["battery_percent"] = int(battery)

    def _sport_state_callback(self, message) -> None:
        mode = getattr(message, "mode", "unknown")
        velocity = getattr(message, "velocity", None)
        yaw_speed = getattr(message, "yaw_speed", 0.0)
        with self._lock:
            self._state["motion_mode"] = str(mode)
            if velocity is not None and len(velocity) >= 2:
                self._state["velocity"] = {
                    "vx": float(velocity[0]),
                    "vy": float(velocity[1]),
                    "vyaw": float(yaw_speed),
                }
