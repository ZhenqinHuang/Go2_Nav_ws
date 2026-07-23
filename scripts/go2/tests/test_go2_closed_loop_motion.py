import math
import unittest

from scripts.go2.go2_closed_loop_motion_test import (
    ControlLimits,
    evaluate_motion,
    project_displacement,
)


class ClosedLoopControlTest(unittest.TestCase):
    def setUp(self):
        self.limits = ControlLimits(
            target_m=0.40,
            stop_trigger_m=0.38,
            max_motion_s=1.80,
            max_state_age_s=0.15,
            max_lateral_m=0.15,
        )

    def test_projects_displacement_into_initial_heading(self):
        forward, lateral, distance = project_displacement(
            start_x=1.0,
            start_y=2.0,
            current_x=1.3,
            current_y=2.4,
            initial_yaw=math.atan2(4.0, 3.0),
        )
        self.assertAlmostEqual(forward, 0.5, places=6)
        self.assertAlmostEqual(lateral, 0.0, places=6)
        self.assertAlmostEqual(distance, 0.5, places=6)

    def test_stops_at_braking_trigger(self):
        decision = evaluate_motion(
            forward_m=0.381,
            lateral_m=0.01,
            distance_m=0.381,
            elapsed_s=1.2,
            state_age_s=0.01,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "target_trigger")

    def test_stops_on_stale_state_before_timeout(self):
        decision = evaluate_motion(
            forward_m=0.10,
            lateral_m=0.0,
            distance_m=0.10,
            elapsed_s=0.8,
            state_age_s=0.16,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "state_stale")

    def test_stops_on_external_sport_request(self):
        decision = evaluate_motion(
            forward_m=0.10,
            lateral_m=0.0,
            distance_m=0.10,
            elapsed_s=0.4,
            state_age_s=0.01,
            external_request_seen=True,
            limits=self.limits,
        )
        self.assertEqual(decision, "external_request")

    def test_stops_on_hard_timeout(self):
        decision = evaluate_motion(
            forward_m=0.20,
            lateral_m=0.0,
            distance_m=0.20,
            elapsed_s=1.81,
            state_age_s=0.01,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "hard_timeout")

    def test_stops_on_excessive_lateral_motion(self):
        decision = evaluate_motion(
            forward_m=0.10,
            lateral_m=0.16,
            distance_m=0.19,
            elapsed_s=0.5,
            state_age_s=0.01,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "lateral_limit")

    def test_stops_on_reverse_motion(self):
        decision = evaluate_motion(
            forward_m=-0.031,
            lateral_m=0.0,
            distance_m=0.031,
            elapsed_s=0.2,
            state_age_s=0.01,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "reverse_limit")

    def test_stops_on_total_distance_limit(self):
        decision = evaluate_motion(
            forward_m=0.30,
            lateral_m=0.10,
            distance_m=0.451,
            elapsed_s=1.2,
            state_age_s=0.01,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "distance_limit")

    def test_continues_inside_all_limits(self):
        decision = evaluate_motion(
            forward_m=0.20,
            lateral_m=0.01,
            distance_m=0.20,
            elapsed_s=0.9,
            state_age_s=0.01,
            external_request_seen=False,
            limits=self.limits,
        )
        self.assertEqual(decision, "continue")


if __name__ == "__main__":
    unittest.main()
