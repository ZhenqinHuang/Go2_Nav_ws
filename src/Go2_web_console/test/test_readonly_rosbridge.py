import json
from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))


def load_policy():
    from go2_web_console import readonly_rosbridge

    return readonly_rosbridge


def test_allows_and_normalizes_only_allowlisted_subscriptions():
    module = load_policy()
    raw = json.dumps(
        {
            "op": "subscribe",
            "id": "subscribe:/scan:123",
            "topic": "/scan",
            "type": "sensor_msgs/LaserScan",
            "compression": "cbor-raw",
            "throttle_rate": 999999,
            "queue_length": 999,
            "fragment_size": 4096,
            "unknown": "drop-me",
        }
    )

    result = module.filter_client_message(raw)

    assert result == {
        "op": "subscribe",
        "id": "subscribe:/scan:123",
        "topic": "/scan",
        "type": "sensor_msgs/LaserScan",
        "compression": "none",
        "throttle_rate": 10000,
        "queue_length": 100,
    }


def test_allows_normalized_unsubscribe():
    module = load_policy()

    result = module.filter_client_message(
        '{"op":"unsubscribe","id":"sub-1","topic":"/map","extra":true}'
    )

    assert result == {"op": "unsubscribe", "id": "sub-1", "topic": "/map"}


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"op":"publish","topic":"/cmd_vel","msg":{}}',
        '{"op":"advertise","topic":"/scan"}',
        '{"op":"call_service","service":"/rosapi/topics"}',
        '{"op":"send_action_goal","action":"/navigate_to_pose"}',
        '{"op":"fragment","id":"x"}',
        '{"op":"subscribe","topic":"/cmd_vel"}',
        '{"op":"subscribe","topic":"/initialpose"}',
        '{"op":"subscribe","topic":"/scan/../cmd_vel"}',
        '{"op":"subscribe","topic":"*"}',
        '{"op":"subscribe","topic":"/scan","id":""}',
    ],
)
def test_rejects_control_dynamic_and_malformed_messages(payload):
    module = load_policy()

    with pytest.raises(module.RosbridgePolicyError):
        module.filter_client_message(payload)


def test_default_allowlist_is_visualization_only():
    module = load_policy()

    assert {"/map", "/scan", "/tf", "/tf_static", "/plan", "/odom"} <= (
        module.DEFAULT_TOPIC_ALLOWLIST
    )
    assert "/cmd_vel" not in module.DEFAULT_TOPIC_ALLOWLIST
    assert "/goal_pose" not in module.DEFAULT_TOPIC_ALLOWLIST
    assert "/initialpose" not in module.DEFAULT_TOPIC_ALLOWLIST
