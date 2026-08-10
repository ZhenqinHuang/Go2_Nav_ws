"""Fail-closed rosbridge message policy for visualization subscriptions."""

from __future__ import annotations

import json
import re
from typing import Iterable


DEFAULT_TOPIC_ALLOWLIST = frozenset(
    {
        "/map",
        "/scan",
        "/tf",
        "/tf_static",
        "/plan",
        "/local_plan",
        "/global_costmap/costmap",
        "/local_costmap/costmap",
        "/global_costmap/published_footprint",
        "/local_costmap/published_footprint",
        "/cloud_registered",
        "/odom",
        "/rosout",
        "/map/topology",
        "/navigate_to_pose/_action/status",
        "/navigate_through_poses/_action/status",
        "/follow_waypoints/_action/status",
    }
)

_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*/(?:msg/)?[A-Za-z][A-Za-z0-9_]*$")


class RosbridgePolicyError(ValueError):
    """Raised when a browser frame is outside the visualization policy."""


def _bounded_int(value, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise RosbridgePolicyError("boolean is not a valid integer option")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RosbridgePolicyError("invalid integer option") from exc
    return max(minimum, min(maximum, parsed))


def _safe_identifier(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise RosbridgePolicyError("a bounded subscription id is required")
    if any(ord(character) < 32 for character in value):
        raise RosbridgePolicyError("subscription id contains control characters")
    return value


def filter_client_message(
    raw: str,
    *,
    allowlist: Iterable[str] = DEFAULT_TOPIC_ALLOWLIST,
) -> dict:
    """Parse and normalize a browser rosbridge frame.

    Only subscribe and unsubscribe operations for an exact topic allowlist are
    returned. All publisher, service, action and protocol-extension operations
    fail closed.
    """

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RosbridgePolicyError("message must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise RosbridgePolicyError("message must be a JSON object")

    operation = payload.get("op")
    if operation not in {"subscribe", "unsubscribe"}:
        raise RosbridgePolicyError("only subscribe and unsubscribe are allowed")

    topic = payload.get("topic")
    if not isinstance(topic, str) or topic not in frozenset(allowlist):
        raise RosbridgePolicyError("topic is not allowlisted")
    identifier = _safe_identifier(payload.get("id"))

    if operation == "unsubscribe":
        return {"op": operation, "id": identifier, "topic": topic}

    normalized = {
        "op": operation,
        "id": identifier,
        "topic": topic,
    }
    message_type = payload.get("type")
    if message_type is not None:
        if not isinstance(message_type, str) or not _TYPE_PATTERN.fullmatch(
            message_type
        ):
            raise RosbridgePolicyError("invalid ROS message type")
        normalized["type"] = message_type
    normalized["compression"] = "none"
    normalized["throttle_rate"] = _bounded_int(
        payload.get("throttle_rate"), default=0, minimum=0, maximum=10000
    )
    normalized["queue_length"] = _bounded_int(
        payload.get("queue_length"), default=1, minimum=1, maximum=100
    )
    return normalized
