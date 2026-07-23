import unittest

from scripts.go2_l2.l2_input_probe import (
    analyze_point_times,
    classify_unitree_lidar,
    evaluate_rates,
    validate_point_fields,
)


class PointFieldValidationTest(unittest.TestCase):
    def test_accepts_required_point_fields(self):
        errors = validate_point_fields(
            {
                "x": 7,
                "y": 7,
                "z": 7,
                "intensity": 7,
                "ring": 4,
                "time": 7,
            }
        )

        self.assertEqual(errors, [])

    def test_reports_missing_time_field(self):
        errors = validate_point_fields(
            {
                "x": 7,
                "y": 7,
                "z": 7,
                "intensity": 7,
                "ring": 4,
            }
        )

        self.assertEqual(errors, ["missing PointCloud2 field: time"])

    def test_reports_wrong_ring_datatype(self):
        errors = validate_point_fields(
            {
                "x": 7,
                "y": 7,
                "z": 7,
                "intensity": 7,
                "ring": 2,
                "time": 7,
            }
        )

        self.assertEqual(
            errors,
            ["PointCloud2 field ring has datatype 2, expected 4"],
        )


class PointTimeAnalysisTest(unittest.TestCase):
    def test_extracts_l2_sampling_interval(self):
        analysis = analyze_point_times(
            [0.0, 0.00000773, 0.00001546, 0.00003092]
        )

        self.assertTrue(analysis["monotonic"])
        self.assertAlmostEqual(analysis["span_s"], 0.00003092)
        self.assertAlmostEqual(
            analysis["mode_positive_delta_s"],
            0.00000773,
            places=10,
        )
        self.assertAlmostEqual(
            analysis["raw_sampling_hz"],
            129366.106,
            places=2,
        )

    def test_empty_times_are_invalid(self):
        analysis = analyze_point_times([])

        self.assertFalse(analysis["monotonic"])
        self.assertIsNone(analysis["raw_sampling_hz"])
        self.assertEqual(analysis["errors"], ["point time array is empty"])

    def test_reports_time_regression(self):
        analysis = analyze_point_times([0.0, 0.02, 0.01])

        self.assertFalse(analysis["monotonic"])
        self.assertIn("point time values regress", analysis["errors"])


class LidarClassificationTest(unittest.TestCase):
    def test_classifies_l2_from_sampling_characteristics(self):
        model = classify_unitree_lidar(
            raw_sampling_hz=129366.0,
            effective_points_hz=64000.0,
        )

        self.assertEqual(model, "L2")

    def test_classifies_l1_from_sampling_characteristics(self):
        model = classify_unitree_lidar(
            raw_sampling_hz=43200.0,
            effective_points_hz=21600.0,
        )

        self.assertEqual(model, "L1")

    def test_returns_unknown_for_unrelated_characteristics(self):
        model = classify_unitree_lidar(
            raw_sampling_hz=10000.0,
            effective_points_hz=5000.0,
        )

        self.assertEqual(model, "unknown")


class TopicRateValidationTest(unittest.TestCase):
    def test_accepts_observed_l2_rates(self):
        self.assertEqual(evaluate_rates(cloud_hz=15.4, imu_hz=249.9), [])

    def test_rejects_slow_cloud_and_imu(self):
        errors = evaluate_rates(cloud_hz=4.0, imu_hz=80.0)

        self.assertEqual(
            errors,
            [
                "cloud rate 4.000 Hz is outside 10.0-30.0 Hz",
                "IMU rate 80.000 Hz is outside 200.0-350.0 Hz",
            ],
        )


if __name__ == "__main__":
    unittest.main()
