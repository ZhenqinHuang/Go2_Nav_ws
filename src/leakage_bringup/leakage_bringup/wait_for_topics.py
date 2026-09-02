import rclpy
from nav_msgs.msg import Path
from rclpy.node import Node
from sensor_msgs.msg import Image, PointCloud2

from .preflight_state import PreflightState


class TopicPreflight(Node):
    def __init__(self) -> None:
        super().__init__("leakage_topic_preflight")
        self.state = PreflightState({"odom", "cloud", "rgb", "depth"})
        self._subscriptions = [
            self.create_subscription(Path, "/fastlio_path", lambda _: self._seen("odom"), 10),
            self.create_subscription(
                PointCloud2,
                "/record/cloud_registered",
                lambda _: self._seen("cloud"),
                10,
            ),
            self.create_subscription(Image, "/camera/color/image_raw", lambda _: self._seen("rgb"), 10),
            self.create_subscription(Image, "/camera/depth/image_rect_raw", lambda _: self._seen("depth"), 10),
        ]

    def _seen(self, name: str) -> None:
        if name not in self.state._seen:
            print(f"received: {name}", flush=True)
        self.state.mark_seen(name)


def main() -> None:
    rclpy.init()
    node = TopicPreflight()
    while rclpy.ok() and not node.state.ready:
        rclpy.spin_once(node, timeout_sec=1.0)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
