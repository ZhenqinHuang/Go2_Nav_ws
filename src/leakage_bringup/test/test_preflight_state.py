import unittest

from leakage_bringup.preflight_state import PreflightState


class PreflightStateTest(unittest.TestCase):
    def test_ready_only_after_every_required_stream_is_seen(self):
        state = PreflightState({"odom", "rgb", "depth"})
        state.mark_seen("odom")
        state.mark_seen("rgb")
        self.assertFalse(state.ready)
        state.mark_seen("depth")
        self.assertTrue(state.ready)


if __name__ == "__main__":
    unittest.main()
