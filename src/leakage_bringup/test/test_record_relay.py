import unittest

from leakage_bringup.record_relay import relay_topics


class RecordRelayTest(unittest.TestCase):
    def test_uses_dedicated_recording_topics(self):
        self.assertEqual(
            relay_topics(),
            {
                "/Odometry": "/record/odometry",
                "/cloud_registered": "/record/cloud_registered",
            },
        )


if __name__ == "__main__":
    unittest.main()
