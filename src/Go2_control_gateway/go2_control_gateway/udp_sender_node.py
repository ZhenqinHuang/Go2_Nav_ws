"""ROS 2 adapter and UDP transport for the external Go2 command sender."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import socket
import threading
import time
from typing import Callable, Optional

from .protocol import ProtocolError, decode_ack, encode_control
from .sender_core import SenderConfig, SenderCore


@dataclass(frozen=True)
class NetworkConfig:
    local_ip: str = "192.168.123.5"
    local_port: int = 15001
    remote_ip: str = "192.168.123.18"
    remote_port: int = 15000
    send_hz: float = 20.0
    receive_timeout_sec: float = 0.1
    bind_retry_sec: float = 5.0

    def __post_init__(self) -> None:
        for name in ("local_port", "remote_port"):
            value = int(getattr(self, name))
            if not 1 <= value <= 65535:
                raise ValueError(f"{name} must be in [1, 65535]")
        if not math.isfinite(self.send_hz) or self.send_hz <= 0.0:
            raise ValueError("send_hz must be finite and positive")
        if (
            not math.isfinite(self.receive_timeout_sec)
            or self.receive_timeout_sec <= 0.0
        ):
            raise ValueError("receive_timeout_sec must be finite and positive")
        if not math.isfinite(self.bind_retry_sec) or self.bind_retry_sec <= 0.0:
            raise ValueError("bind_retry_sec must be finite and positive")


class UdpSenderAdapter:
    """Thread-safe socket adapter around :class:`SenderCore`."""

    def __init__(
        self,
        *,
        core: SenderCore,
        config: Optional[NetworkConfig] = None,
        socket_factory: Callable[..., socket.socket] = socket.socket,
        clock: Callable[[], float] = time.monotonic,
        waiter: Callable[[float], None] = time.sleep,
    ) -> None:
        self.core = core
        self.config = config or NetworkConfig()
        self._clock = clock
        self._waiter = waiter
        self._core_lock = threading.RLock()
        self._command_condition = threading.Condition(self._core_lock)
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._receiver_thread: Optional[threading.Thread] = None
        self._last_valid_ack_at: Optional[float] = None
        self._closed = False
        self._socket_factory = socket_factory
        self._socket: Optional[socket.socket] = None
        self._network_error: Optional[str] = None
        self._next_bind_attempt_at = 0.0
        self._ensure_socket()

    @property
    def destination(self) -> tuple[str, int]:
        return (self.config.remote_ip, self.config.remote_port)

    @property
    def send_period_sec(self) -> float:
        return 1.0 / self.config.send_hz

    def start_receiver(self) -> None:
        if self._receiver_thread and self._receiver_thread.is_alive():
            return
        if self._closed:
            raise RuntimeError("UDP adapter is closed")
        self._stop_event.clear()
        self._receiver_thread = threading.Thread(
            target=self._receive_loop,
            name="go2-gateway-ack",
            daemon=True,
        )
        self._receiver_thread.start()

    def send_once(self) -> int:
        with self._core_lock:
            packet = self.core.next_packet()
            payload = encode_control(packet)
        with self._send_lock:
            if not self._ensure_socket():
                raise OSError(self._network_error or "control network unavailable")
            assert self._socket is not None
            return self._socket.sendto(payload, self.destination)

    def handle_datagram(self, payload: bytes, source: tuple[str, int]) -> bool:
        if source != self.destination:
            return False
        try:
            ack = decode_ack(payload)
        except (ProtocolError, TypeError, ValueError):
            return False
        with self._core_lock:
            accepted = self.core.handle_ack(ack)
            if accepted:
                self._last_valid_ack_at = self._clock()
                self._command_condition.notify_all()
            return accepted

    def set_nav_active(self, active: bool) -> None:
        with self._core_lock:
            self.core.set_nav_active(active)

    def update_nav_cmd(self, vx: float, vy: float, vyaw: float) -> bool:
        with self._core_lock:
            return self.core.update_nav_cmd(vx, vy, vyaw)

    def update_manual_cmd(self, vx: float, vy: float, vyaw: float) -> bool:
        with self._core_lock:
            return self.core.update_manual_cmd(vx, vy, vyaw)

    def update_localization(self, x: float, y: float, yaw: float) -> bool:
        with self._core_lock:
            return self.core.update_localization(x, y, yaw)

    def request_emergency_stop(self) -> bool:
        with self._core_lock:
            return self.core.request_emergency_stop()

    def request_reset_emergency_stop(self) -> bool:
        with self._core_lock:
            return self.core.request_reset_emergency_stop()

    def request_posture(self, posture: str) -> bool:
        with self._core_lock:
            return self.core.request_posture(posture)

    def emergency_stop(self, timeout_sec: float = 1.0) -> bool:
        return self._execute_command(
            self.request_emergency_stop,
            lambda: self.core.estop_latched and not self.core.command_pending,
            timeout_sec,
        )

    def reset_emergency_stop(self, timeout_sec: float = 1.0) -> bool:
        return self._execute_command(
            self.request_reset_emergency_stop,
            lambda: not self.core.estop_latched and not self.core.command_pending,
            timeout_sec,
        )

    def set_posture(self, posture: str, timeout_sec: float = 2.0) -> bool:
        expected = "standing" if posture == "stand" else "lying"
        return self._execute_command(
            lambda: self.request_posture(posture),
            lambda: self.core.posture == expected and not self.core.command_pending,
            timeout_sec,
        )

    def status_json(self) -> str:
        now = self._clock()
        with self._send_lock:
            network_ready = self._socket is not None
            network_error = self._network_error
        with self._core_lock:
            last_ack_age = (
                None
                if self._last_valid_ack_at is None
                else max(0.0, now - self._last_valid_ack_at)
            )
            link_online = (
                last_ack_age is not None
                and last_ack_age <= self.core.config.ack_timeout_sec
            )
            localization_ready = self.core.localization_ready
            estop_latched = self.core.estop_latched
            control_ready = (
                link_online
                and self.core.control_ready
                and localization_ready
                and not estop_latched
            )
            if not network_ready:
                block_reason = "control_network_unavailable"
            elif estop_latched:
                block_reason = "estop_latched"
            elif not link_online or not self.core.control_ready:
                block_reason = "gateway_ack_stale"
            elif not localization_ready:
                block_reason = "localization_stale"
            else:
                block_reason = None
            status = {
                "gateway_link": "online" if link_online else "offline",
                "network_ready": network_ready,
                "network_error": network_error,
                "control_ready": control_ready,
                "localization_ready": localization_ready,
                "nav_active": self.core.nav_active,
                "active_source": self.core.active_source,
                "estop_latched": estop_latched,
                "posture": self.core.posture,
                "command_pending": self.core.command_pending,
                "block_reason": block_reason,
                "last_ack_age_sec": (
                    None if last_ack_age is None else round(last_ack_age, 3)
                ),
                "send_hz": self.config.send_hz,
            }
        return json.dumps(status, ensure_ascii=False, separators=(",", ":"))

    def shutdown(
        self,
        *,
        repeat_count: int = 5,
        repeat_interval_sec: float = 0.02,
    ) -> None:
        if self._closed:
            return
        self._stop_event.set()
        with self._core_lock:
            self.core.clear_commands()
        for index in range(max(1, int(repeat_count))):
            try:
                self.send_once()
            except OSError:
                break
            if repeat_interval_sec > 0.0 and index + 1 < repeat_count:
                self._waiter(repeat_interval_sec)
        if self._receiver_thread and self._receiver_thread.is_alive():
            self._receiver_thread.join(timeout=0.3)
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._closed = True

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._send_lock:
                self._ensure_socket()
                active_socket = self._socket
            if active_socket is None:
                self._stop_event.wait(min(0.5, self.config.bind_retry_sec))
                continue
            try:
                payload, source = active_socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_datagram(payload, source)

    def _ensure_socket(self) -> bool:
        if self._socket is not None:
            return True
        now = self._clock()
        if now < self._next_bind_attempt_at:
            return False
        candidate = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            candidate.bind((self.config.local_ip, self.config.local_port))
            candidate.settimeout(self.config.receive_timeout_sec)
        except OSError as exc:
            candidate.close()
            self._network_error = str(exc)
            self._next_bind_attempt_at = now + self.config.bind_retry_sec
            return False
        self._socket = candidate
        self._network_error = None
        self._next_bind_attempt_at = 0.0
        return True

    def _execute_command(
        self,
        request: Callable[[], bool],
        completed: Callable[[], bool],
        timeout_sec: float,
    ) -> bool:
        timeout_sec = max(0.0, float(timeout_sec))
        if not request():
            return False
        try:
            self.send_once()
        except OSError:
            pass
        deadline = time.monotonic() + timeout_sec
        with self._command_condition:
            while not completed():
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._command_condition.wait(timeout=min(remaining, 0.1))
            return True


try:
    import rclpy
    from action_msgs.msg import GoalStatusArray
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from std_srvs.srv import Trigger
except ImportError:  # Allows protocol/adapter tests on a non-ROS development host.
    rclpy = None
    Node = object


if rclpy is not None:

    class Go2CmdVelUdpSender(Node):
        def __init__(self) -> None:
            super().__init__("go2_cmd_vel_udp_sender")
            callback_group = ReentrantCallbackGroup()

            network_defaults = NetworkConfig()
            sender_defaults = SenderConfig()
            for name, default in (
                ("local_ip", network_defaults.local_ip),
                ("local_port", network_defaults.local_port),
                ("remote_ip", network_defaults.remote_ip),
                ("remote_port", network_defaults.remote_port),
                ("send_hz", network_defaults.send_hz),
                ("bind_retry_sec", network_defaults.bind_retry_sec),
                ("max_vx", sender_defaults.max_vx),
                ("max_vy", sender_defaults.max_vy),
                ("max_vyaw", sender_defaults.max_vyaw),
                ("velocity_deadband", sender_defaults.velocity_deadband),
                ("vyaw_smooth_alpha", sender_defaults.vyaw_smooth_alpha),
                ("nav_cmd_timeout_sec", sender_defaults.nav_cmd_timeout_sec),
                ("manual_cmd_timeout_sec", sender_defaults.manual_cmd_timeout_sec),
                ("ack_timeout_sec", sender_defaults.ack_timeout_sec),
                (
                    "localization_guard_enabled",
                    sender_defaults.localization_guard_enabled,
                ),
                (
                    "localization_timeout_sec",
                    sender_defaults.localization_timeout_sec,
                ),
                ("correction_pause_sec", sender_defaults.correction_pause_sec),
                (
                    "correction_pause_delta_xy",
                    sender_defaults.correction_pause_delta_xy,
                ),
                (
                    "correction_pause_delta_yaw",
                    sender_defaults.correction_pause_delta_yaw,
                ),
                ("cmd_vel_topic", "/cmd_vel"),
                ("manual_cmd_vel_topic", "/go2/manual_cmd_vel"),
                ("localization_topic", "/map_to_odom"),
                ("nav_status_topic", "/navigate_to_pose/_action/status"),
            ):
                self.declare_parameter(name, default)

            network_config = NetworkConfig(
                local_ip=self.get_parameter("local_ip").value,
                local_port=self.get_parameter("local_port").value,
                remote_ip=self.get_parameter("remote_ip").value,
                remote_port=self.get_parameter("remote_port").value,
                send_hz=self.get_parameter("send_hz").value,
                bind_retry_sec=self.get_parameter("bind_retry_sec").value,
            )
            sender_config = SenderConfig(
                max_vx=self.get_parameter("max_vx").value,
                max_vy=self.get_parameter("max_vy").value,
                max_vyaw=self.get_parameter("max_vyaw").value,
                velocity_deadband=self.get_parameter("velocity_deadband").value,
                vyaw_smooth_alpha=self.get_parameter("vyaw_smooth_alpha").value,
                nav_cmd_timeout_sec=self.get_parameter("nav_cmd_timeout_sec").value,
                manual_cmd_timeout_sec=self.get_parameter(
                    "manual_cmd_timeout_sec"
                ).value,
                ack_timeout_sec=self.get_parameter("ack_timeout_sec").value,
                localization_guard_enabled=self.get_parameter(
                    "localization_guard_enabled"
                ).value,
                localization_timeout_sec=self.get_parameter(
                    "localization_timeout_sec"
                ).value,
                correction_pause_sec=self.get_parameter(
                    "correction_pause_sec"
                ).value,
                correction_pause_delta_xy=self.get_parameter(
                    "correction_pause_delta_xy"
                ).value,
                correction_pause_delta_yaw=self.get_parameter(
                    "correction_pause_delta_yaw"
                ).value,
            )
            self._adapter = UdpSenderAdapter(
                core=SenderCore(config=sender_config),
                config=network_config,
            )
            self._adapter.start_receiver()

            self._status_publisher = self.create_publisher(
                String, "/go2_cmd_vel_gateway/status", 10
            )
            self.create_subscription(
                Twist,
                self.get_parameter("cmd_vel_topic").value,
                self._nav_cmd_callback,
                10,
                callback_group=callback_group,
            )
            self.create_service(
                Trigger,
                "/go2_cmd_vel_gateway/stand_up",
                self._stand_up_callback,
                callback_group=callback_group,
            )
            self.create_service(
                Trigger,
                "/go2_cmd_vel_gateway/stand_down",
                self._stand_down_callback,
                callback_group=callback_group,
            )
            self.create_service(
                Trigger,
                "/go2_cmd_vel_gateway/emergency_stop",
                self._emergency_stop_callback,
                callback_group=callback_group,
            )
            self.create_service(
                Trigger,
                "/go2_cmd_vel_gateway/reset_emergency_stop",
                self._reset_emergency_stop_callback,
                callback_group=callback_group,
            )
            self.create_subscription(
                Twist,
                self.get_parameter("manual_cmd_vel_topic").value,
                self._manual_cmd_callback,
                10,
                callback_group=callback_group,
            )
            self.create_subscription(
                Odometry,
                self.get_parameter("localization_topic").value,
                self._localization_callback,
                10,
                callback_group=callback_group,
            )
            self.create_subscription(
                GoalStatusArray,
                self.get_parameter("nav_status_topic").value,
                self._nav_status_callback,
                10,
                callback_group=callback_group,
            )
            self.create_timer(
                self._adapter.send_period_sec,
                self._send_tick,
                callback_group=callback_group,
            )
            self.get_logger().info(
                "UDP sender ready: %s:%d -> %s:%d at %.1f Hz"
                % (
                    network_config.local_ip,
                    network_config.local_port,
                    network_config.remote_ip,
                    network_config.remote_port,
                    network_config.send_hz,
                )
            )

        def _send_tick(self) -> None:
            try:
                self._adapter.send_once()
            except OSError as exc:
                self.get_logger().error(f"UDP send failed: {exc}")
            message = String()
            message.data = self._adapter.status_json()
            self._status_publisher.publish(message)

        def _nav_cmd_callback(self, message: Twist) -> None:
            self._adapter.update_nav_cmd(
                message.linear.x, message.linear.y, message.angular.z
            )

        def _manual_cmd_callback(self, message: Twist) -> None:
            self._adapter.update_manual_cmd(
                message.linear.x, message.linear.y, message.angular.z
            )

        def _localization_callback(self, message: Odometry) -> None:
            position = message.pose.pose.position
            orientation = message.pose.pose.orientation
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
            self._adapter.update_localization(position.x, position.y, yaw)

        def _nav_status_callback(self, message: GoalStatusArray) -> None:
            # ACCEPTED, EXECUTING, and CANCELING all keep manual control locked.
            active = any(item.status in (1, 2, 3) for item in message.status_list)
            self._adapter.set_nav_active(active)

        def _stand_up_callback(self, _request, response):
            response.success = self._adapter.set_posture("stand")
            response.message = (
                "stand acknowledged" if response.success else "stand blocked or timed out"
            )
            return response

        def _stand_down_callback(self, _request, response):
            response.success = self._adapter.set_posture("lie")
            response.message = (
                "lie acknowledged" if response.success else "lie blocked or timed out"
            )
            return response

        def _emergency_stop_callback(self, _request, response):
            response.success = self._adapter.emergency_stop()
            response.message = (
                "emergency stop acknowledged"
                if response.success
                else "emergency stop latched locally; internal ACK timed out"
            )
            return response

        def _reset_emergency_stop_callback(self, _request, response):
            response.success = self._adapter.reset_emergency_stop()
            response.message = (
                "emergency stop reset acknowledged"
                if response.success
                else "reset blocked or timed out"
            )
            return response

        def destroy_node(self):
            self._adapter.shutdown()
            return super().destroy_node()


def main(args=None) -> None:
    if rclpy is None:
        raise RuntimeError("ROS 2 rclpy is required to run udp_sender_node")
    rclpy.init(args=args)
    node = Go2CmdVelUdpSender()
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
