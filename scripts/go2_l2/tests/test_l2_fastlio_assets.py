from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "scripts" / "go2_l2" / "config" / "go2_l2.yaml"
LAUNCHER_PATH = REPO_ROOT / "scripts" / "go2_l2" / "run_fastlio2_l2.sh"


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


class L2FastlioLauncherTest(unittest.TestCase):
    def launcher_source(self):
        return LAUNCHER_PATH.read_text(encoding="utf-8")

    def test_sources_required_workspaces_and_l2_config(self):
        source = self.launcher_source()

        self.assertIn('UNITREE_INTERFACE="${UNITREE_INTERFACE:-eth0}"', source)
        self.assertIn("/home/nvidia/unitree_ros2/setup.sh", source)
        self.assertIn("/home/nvidia/ws_Livox/install/setup.bash", source)
        self.assertIn("/home/nvidia/ws_fastlio2/install/setup.bash", source)
        self.assertIn("ros2 launch fast_lio mapping.launch.py", source)
        self.assertIn("config_file:=go2_l2.yaml", source)
        self.assertIn("exec ros2 launch", source)

    def test_supports_probe_only_gate(self):
        source = self.launcher_source()

        self.assertIn("--probe-only", source)
        self.assertIn("l2_input_probe.py", source)

    def test_contains_no_robot_motion_interface(self):
        source = self.launcher_source()

        self.assertNotIn("/api/sport/request", source)
        self.assertNotIn("SportClient", source)
        self.assertNotIn("Move(", source)
        self.assertNotIn("create_publisher", source)


if __name__ == "__main__":
    unittest.main()
