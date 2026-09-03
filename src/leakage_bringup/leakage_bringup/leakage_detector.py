from collections import deque
from pathlib import Path

import numpy as np
import rclpy
import yaml
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image, PointCloud2, PointField

from .leakage_projection import (
    calibration_ready,
    camera_points_to_map,
    mask_depth_points,
    synchronized_inputs,
)


class LeakageDetector(Node):
    def __init__(self) -> None:
        super().__init__("leakage_detector")
        self.declare_parameter("model_path", "models/best.pt")
        self.declare_parameter("calibration_file", "config/common/calibration.yaml")
        self.declare_parameter("confidence", 0.25)
        self.declare_parameter("image_size", 1024)
        self.declare_parameter("point_stride", 4)
        self.declare_parameter("max_depth_m", 10.0)
        self.declare_parameter("max_sync_delta_s", 0.05)
        self.declare_parameter("inference_hz", 2.0)

        from ultralytics import YOLO

        model_path = Path(self.get_parameter("model_path").value)
        calibration_path = Path(self.get_parameter("calibration_file").value)
        if not model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {model_path}")
        if not calibration_path.is_file():
            raise FileNotFoundError(f"calibration file not found: {calibration_path}")
        self.model = YOLO(str(model_path))
        self.calibration = yaml.safe_load(calibration_path.read_text())
        self.enable_3d = calibration_ready(self.calibration)
        if not self.enable_3d:
            self.get_logger().warning("calibration gate closed; publishing 2D masks only")

        self.rgb = self.info = None
        self.depths = deque(maxlen=30)
        self.odoms = deque(maxlen=30)
        self.mask_pub = self.create_publisher(Image, "/leakage/mask", 10)
        self.cloud_pub = self.create_publisher(PointCloud2, "/leakage/points", 10)
        camera_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(
            Image, "/camera/aligned_depth_to_color/image_raw", self._depth, camera_qos
        )
        self.create_subscription(
            CameraInfo, "/camera/color/camera_info", self._info, camera_qos
        )
        self.create_subscription(Odometry, "/Odometry", self._odom, 1)
        self.create_subscription(Image, "/camera/color/image_raw", self._rgb, camera_qos)
        inference_hz = float(self.get_parameter("inference_hz").value)
        if inference_hz <= 0.0:
            raise ValueError("inference_hz must be positive")
        self.create_timer(1.0 / inference_hz, self._infer)

    def _depth(self, message):
        self.depths.append(message)

    def _info(self, message):
        self.info = message

    def _odom(self, message):
        self.odoms.append(message)

    def _rgb(self, message):
        if message.encoding != "rgb8":
            self.get_logger().error(f"unsupported RGB encoding: {message.encoding}")
            return
        self.rgb = message

    def _infer(self):
        message = self.rgb
        if message is None:
            return
        self.rgb = None
        rgb = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
        rgb = rgb[:, : message.width * 3].reshape(message.height, message.width, 3)
        result = self.model.predict(
            np.ascontiguousarray(rgb[:, :, ::-1]),
            conf=float(self.get_parameter("confidence").value),
            imgsz=int(self.get_parameter("image_size").value),
            retina_masks=True,
            device=0,
            half=True,
            verbose=False,
        )[0]
        mask = np.zeros((message.height, message.width), dtype=np.uint8)
        if result.masks is not None:
            masks = result.masks.data.detach().cpu().numpy()
            mask[np.any(masks > 0.5, axis=0)] = 255
        self.mask_pub.publish(self._mask_message(mask, message))
        if self.enable_3d and np.any(mask):
            self._publish_3d(mask > 0, message)

    @staticmethod
    def _mask_message(mask, source):
        output = Image()
        output.header = source.header
        output.height, output.width = mask.shape
        output.encoding = "mono8"
        output.is_bigendian = False
        output.step = output.width
        output.data = mask.tobytes()
        return output

    def _publish_3d(self, mask, rgb):
        if self.info is None:
            return
        depth, odom = synchronized_inputs(
            rgb,
            self.depths,
            self.odoms,
            float(self.calibration["residual_time_offset_s"]),
            float(self.get_parameter("max_sync_delta_s").value),
        )
        if depth is None or odom is None:
            return
        if depth.encoding != "16UC1":
            self.get_logger().error(
                f"unsupported aligned-depth encoding: {depth.encoding}"
            )
            return
        depth_image = np.frombuffer(depth.data, dtype="<u2").reshape(
            depth.height, depth.step // 2
        )[:, : depth.width]
        points = mask_depth_points(
            mask,
            depth_image,
            self.info.k[0],
            self.info.k[4],
            self.info.k[2],
            self.info.k[5],
            float(self.get_parameter("max_depth_m").value),
            int(self.get_parameter("point_stride").value),
        )
        if len(points):
            mapped = camera_points_to_map(points, self.calibration, odom.pose.pose)
            self.cloud_pub.publish(self._cloud_message(mapped, rgb, odom.header.frame_id))

    @staticmethod
    def _cloud_message(points, source, frame_id):
        cloud = PointCloud2()
        cloud.header = source.header
        cloud.header.frame_id = frame_id
        cloud.height = 1
        cloud.width = len(points)
        cloud.fields = [
            PointField(name=name, offset=index * 4, datatype=PointField.FLOAT32, count=1)
            for index, name in enumerate(("x", "y", "z"))
        ]
        cloud.is_bigendian = False
        cloud.point_step = 12
        cloud.row_step = cloud.point_step * cloud.width
        cloud.is_dense = True
        cloud.data = np.asarray(points, dtype="<f4").tobytes()
        return cloud


def main() -> None:
    rclpy.init()
    node = LeakageDetector()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
