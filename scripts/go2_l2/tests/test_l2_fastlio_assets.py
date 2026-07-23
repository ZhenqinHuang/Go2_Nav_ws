from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "scripts" / "go2_l2" / "config" / "go2_l2.yaml"


class L2FastlioConfigTest(unittest.TestCase):
    def load_parameters(self):
        with CONFIG_PATH.open("r", encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
        return document["/**"]["ros__parameters"]

    def test_uses_onboard_l2_topics_and_timestamps(self):
        params = self.load_parameters()
        common = params["common"]
        preprocess = params["preprocess"]

        self.assertEqual(common["lid_topic"], "/utlidar/cloud")
        self.assertEqual(common["imu_topic"], "/utlidar/imu")
        self.assertFalse(common["time_sync_en"])
        self.assertEqual(common["time_offset_lidar_to_imu"], 0.0)
        self.assertEqual(preprocess["lidar_type"], 2)
        self.assertEqual(preprocess["timestamp_unit"], 0)
        self.assertEqual(preprocess["scan_line"], 1)

    def test_uses_l2_fixed_lidar_to_imu_extrinsic(self):
        mapping = self.load_parameters()["mapping"]

        self.assertFalse(mapping["extrinsic_est_en"])
        self.assertEqual(
            mapping["extrinsic_T"],
            [0.007698, 0.014655, -0.00667],
        )
        self.assertEqual(
            mapping["extrinsic_R"],
            [
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ],
        )

    def test_static_smoke_test_does_not_save_a_map(self):
        params = self.load_parameters()

        self.assertEqual(
            params["map_file_path"],
            "/home/nvidia/Go2_Nav_ws/maps/Go2_L2.pcd",
        )
        self.assertFalse(params["pcd_save"]["pcd_save_en"])


if __name__ == "__main__":
    unittest.main()
