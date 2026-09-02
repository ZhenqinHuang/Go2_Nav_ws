import unittest

from leakage_bringup.trajectory_math import should_publish_path


class ShouldPublishPathTest(unittest.TestCase):
    def test_publishes_first_pose_and_then_at_interval(self):
        self.assertTrue(should_publish_path(None, 10.0, interval_seconds=1.0))
        self.assertFalse(should_publish_path(10.0, 10.5, interval_seconds=1.0))
        self.assertTrue(should_publish_path(10.0, 11.0, interval_seconds=1.0))

    def test_rejects_non_positive_interval(self):
        with self.assertRaises(ValueError):
            should_publish_path(1.0, 2.0, interval_seconds=0.0)


if __name__ == "__main__":
    unittest.main()
