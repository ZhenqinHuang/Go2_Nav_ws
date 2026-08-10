import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("go2_nav2")
    config_dir = os.path.join(pkg_share, "config")

    map_file = LaunchConfiguration("map")
    use_sim_time = LaunchConfiguration("use_sim_time")
    use_rviz = LaunchConfiguration("use_rviz")
    rviz_config = LaunchConfiguration("rviz_config")
    controller = LaunchConfiguration("controller")
    controller_params_file = LaunchConfiguration("controller_params_file")
    sim_time_param = {"use_sim_time": use_sim_time}

    selected_controller = PythonExpression(
        [
            "'",
            os.path.join(config_dir, "controller_server_rpp.yaml"),
            "' if '",
            controller,
            "' == 'rpp' else '",
            os.path.join(config_dir, "controller_server.yaml"),
            "'",
        ]
    )

    lifecycle_nodes = [
        "map_server",
        "planner_server",
        "controller_server",
        "recoveries_server",
        "bt_navigator",
        "waypoint_follower",
    ]

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "map",
                default_value="/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml",
                description="Canonical occupancy map YAML",
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("use_rviz", default_value="false"),
            DeclareLaunchArgument(
                "controller",
                default_value="dwb",
                choices=["dwb", "rpp"],
                description="Verified DWB profile or optional RPP profile",
            ),
            DeclareLaunchArgument(
                "controller_params_file",
                default_value=selected_controller,
                description="Optional generated controller configuration",
            ),
            DeclareLaunchArgument(
                "rviz_config",
                default_value=os.path.join(pkg_share, "rviz", "nav2.rviz"),
            ),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                output="screen",
                parameters=[
                    os.path.join(config_dir, "map_server.yaml"),
                    sim_time_param,
                    {"yaml_filename": map_file},
                ],
            ),
            Node(
                package="nav2_planner",
                executable="planner_server",
                name="planner_server",
                output="screen",
                parameters=[
                    os.path.join(config_dir, "planner_server.yaml"),
                    sim_time_param,
                ],
            ),
            Node(
                package="nav2_controller",
                executable="controller_server",
                name="controller_server",
                output="screen",
                parameters=[controller_params_file, sim_time_param],
            ),
            Node(
                package="nav2_recoveries",
                executable="recoveries_server",
                name="recoveries_server",
                output="screen",
                parameters=[
                    os.path.join(config_dir, "behavior_server.yaml"),
                    sim_time_param,
                ],
            ),
            Node(
                package="nav2_bt_navigator",
                executable="bt_navigator",
                name="bt_navigator",
                output="screen",
                parameters=[
                    os.path.join(config_dir, "bt_navigator.yaml"),
                    sim_time_param,
                    {
                        "default_bt_xml_filename": os.path.join(
                            pkg_share,
                            "behavior_trees",
                            "navigate_slow_replan.xml",
                        )
                    },
                ],
            ),
            Node(
                package="nav2_waypoint_follower",
                executable="waypoint_follower",
                name="waypoint_follower",
                output="screen",
                parameters=[
                    os.path.join(config_dir, "waypoint_follower.yaml"),
                    sim_time_param,
                ],
            ),
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_navigation",
                output="screen",
                parameters=[
                    sim_time_param,
                    {"autostart": True, "node_names": lifecycle_nodes},
                ],
            ),
            Node(
                package="go2_nav2",
                executable="nav_tts_announcer.py",
                name="nav_tts_announcer",
                output="screen",
                parameters=[
                    sim_time_param,
                    {"success_text": "导航成功，已到达目标位置"},
                    {"tts_topic": "/tts_text"},
                ],
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                output="screen",
                condition=IfCondition(use_rviz),
                arguments=["-d", rviz_config],
                parameters=[sim_time_param],
            ),
        ]
    )
