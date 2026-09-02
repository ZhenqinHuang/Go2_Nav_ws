from pathlib import Path

import numpy as np
import rclpy
import yaml
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image, PointCloud2, PointField

from .leakage_projection import calibration_ready, camera_points_to_map, mask_depth_points


def stamp_seconds(stamp) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1e9


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

        self.depth = self.info = self.odom = None
        self.mask_pub = self.create_publisher(Image, "/leakage/mask", 10)
        self.cloud_pub = self.create_publisher(PointCloud2, "/leakage/points", 10)
        self.create_subscription(
            Image, "/camera/aligned_depth_to_color/image_raw", self._depth, 1
        )
        self.create_subscription(CameraInfo, "/camera/color/camera_info", self._info, 1)
        self.create_subscription(Odometry, "/Odometry", self._odom, 1)
        self.create_subscription(Image, "/camera/color/image_raw", self._rgb, 1)

    def _depth(self, message):
        self.depth = message

    def _info(self, message):
        self.info = message

    def _odom(self, message):
        self.odom = message

    def _rgb(self, message):
        if message.encoding != "rgb8":
            self.get_logger().error(f"unsupported RGB encoding: {message.encoding}")
            return
        rgb = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
        rgb = rgb[:, : message.width * 3].reshape(message.height, message.width, 3)
        result = self.model.predict(
            np.ascontiguousarray(rgb[:, :, ::-1]),
            conf=float(self.get_parameter("confidence").value),
            imgsz=int(self.get_parameter("image_size").value),
            retina_masks=True,
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
        if self.depth is None or self.info is None or self.odom is None:
            return
        if self.depth.encoding != "16UC1":
            self.get_logger().error(
                f"unsupported aligned-depth encoding: {self.depth.encoding}"
            )
            return
        max_delta = float(self.get_parameter("max_sync_delta_s").value)
        rgb_time = stamp_seconds(rgb.header.stamp)
        if any(
            abs(rgb_time - stamp_seconds(item.header.stamp)) > max_delta
            for item in (self.depth, self.odom)
        ):
            return
        depth = np.frombuffer(self.depth.data, dtype="<u2").reshape(
            self.depth.height, self.depth.step // 2
        )[:, : self.depth.width]
        points = mask_depth_points(
            mask,
            depth,
            self.info.k[0],
            self.info.k[4],
            self.info.k[2],
            self.info.k[5],
            float(self.get_parameter("max_depth_m").value),
            int(self.get_parameter("point_stride").value),
        )
        if len(points):
            mapped = camera_points_to_map(points, self.calibration, self.odom.pose.pose)
            self.cloud_pub.publish(self._cloud_message(mapped, rgb, self.odom.header.frame_id))

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
