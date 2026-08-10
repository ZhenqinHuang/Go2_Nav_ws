from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
NAV2 = ROOT / "src/Go2_nav2"


def load(name: str):
    return yaml.safe_load((NAV2 / "config" / name).read_text(encoding="utf-8"))


def test_dwb_is_default_and_rpp_is_an_explicit_optional_profile():
    launch = (NAV2 / "launch/nav2_bringup.launch.py").read_text(encoding="utf-8")
    assert 'default_value="dwb"' in launch
    assert 'choices=["dwb", "rpp"]' in launch
    assert "controller_server.yaml" in launch
    assert "controller_server_rpp.yaml" in launch
    assert '"controller_params_file"' in launch
    assert "TimerAction" not in launch


def test_both_profiles_share_frames_topics_footprint_and_limits():
    dwb = load("controller_server.yaml")
    rpp = load("controller_server_rpp.yaml")
    planner = load("planner_server.yaml")
    sender = yaml.safe_load(
        (ROOT / "src/Go2_control_gateway/config/udp_sender.yaml").read_text(
            encoding="utf-8"
        )
    )["go2_cmd_vel_udp_sender"]["ros__parameters"]

    dwb_controller = dwb["controller_server"]["ros__parameters"]
    rpp_controller = rpp["controller_server"]["ros__parameters"]
    assert dwb_controller["FollowPath"]["plugin"] == "dwb_core::DWBLocalPlanner"
    assert rpp_controller["FollowPath"]["plugin"].endswith(
        "RegulatedPurePursuitController"
    )
    assert dwb_controller["odom_topic"] == rpp_controller["odom_topic"] == "/odom"
    assert dwb_controller["controller_frequency"] == rpp_controller["controller_frequency"] == 20.0
    assert dwb_controller["FollowPath"]["max_vel_x"] <= sender["max_vx"]
    assert rpp_controller["FollowPath"]["desired_linear_vel"] <= sender["max_vx"]

    dwb_local = dwb["local_costmap"]["local_costmap"]["ros__parameters"]
    rpp_local = rpp["local_costmap"]["local_costmap"]["ros__parameters"]
    global_costmap = planner["global_costmap"]["global_costmap"]["ros__parameters"]
    assert dwb_local["global_frame"] == rpp_local["global_frame"] == "odom"
    assert dwb_local["robot_base_frame"] == rpp_local["robot_base_frame"] == "base_link"
    assert dwb_local["footprint"] == rpp_local["footprint"] == global_costmap["footprint"]
    assert dwb_local["obstacle_layer"]["scan"]["topic"] == "/scan"
    assert rpp_local["obstacle_layer"]["scan"]["topic"] == "/scan"


def test_nav2_has_one_map_owner_and_complete_lifecycle_set():
    launch = (NAV2 / "launch/nav2_bringup.launch.py").read_text(encoding="utf-8")
    package = (NAV2 / "package.xml").read_text(encoding="utf-8")

    assert launch.count('executable="map_server"') == 1
    for node in (
        "map_server",
        "planner_server",
        "controller_server",
        "recoveries_server",
        "bt_navigator",
        "waypoint_follower",
    ):
        assert f'"{node}"' in launch
    assert "nav2_waypoint_follower" in package
    assert (NAV2 / "config/waypoint_follower.yaml").is_file()


def test_behavior_tree_and_costmap_contracts_are_consistent():
    bt = load("bt_navigator.yaml")["bt_navigator"]["ros__parameters"]
    behavior = load("behavior_server.yaml")["recoveries_server"]["ros__parameters"]
    planner = load("planner_server.yaml")

    assert bt["global_frame"] == "map"
    assert bt["robot_base_frame"] == "base_link"
    assert bt["odom_topic"] == "/odom"
    assert {"spin", "backup", "wait"} <= set(behavior["recovery_plugins"])
    global_costmap = planner["global_costmap"]["global_costmap"]["ros__parameters"]
    assert global_costmap["static_layer"]["map_topic"] == "/map"
    assert global_costmap["obstacle_layer"]["scan"]["topic"] == "/scan"
