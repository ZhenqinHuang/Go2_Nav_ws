from types import SimpleNamespace

from go2_web_console.ros_adapter import (
    _resolve_multi_navigation_action,
    _with_gateway_freshness,
)


class NavigateThroughPoses:
    pass


class FollowWaypoints:
    pass


def test_prefers_navigate_through_poses_when_nav2_provides_it():
    action, topic = _resolve_multi_navigation_action(
        SimpleNamespace(
            NavigateThroughPoses=NavigateThroughPoses,
            FollowWaypoints=FollowWaypoints,
        )
    )

    assert action is NavigateThroughPoses
    assert topic == "/navigate_through_poses"


def test_foxy_falls_back_to_follow_waypoints():
    action, topic = _resolve_multi_navigation_action(
        SimpleNamespace(FollowWaypoints=FollowWaypoints)
    )

    assert action is FollowWaypoints
    assert topic == "/follow_waypoints"


def test_stale_gateway_status_fails_closed_without_mutating_live_state():
    live = {
        "gateway_link": "online",
        "control_ready": True,
        "block_reason": None,
    }

    stale = _with_gateway_freshness(
        live, status_at=10.0, now=11.1, timeout_sec=1.0
    )

    assert stale == {
        "gateway_link": "offline",
        "control_ready": False,
        "block_reason": "gateway_status_stale",
    }
    assert live["gateway_link"] == "online"
