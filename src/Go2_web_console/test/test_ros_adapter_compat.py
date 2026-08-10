from types import SimpleNamespace

from go2_web_console.ros_adapter import _resolve_multi_navigation_action


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
