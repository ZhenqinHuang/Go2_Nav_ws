import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory("go2_nav2")
    config_dir = os.path.join(pkg_share, "config")

    map_file = LaunchConfiguration("map")
    use_sim_time = LaunchConfiguration("use_sim_time")
    use_rviz = LaunchConfiguration("use_rviz")
    rviz_config = LaunchConfiguration("rviz_config")
    controller = LaunchConfiguration("controller")

    sim_time_param = {"use_sim_time": use_sim_time}

    # 根据 controller launch arg 选择 controller_server.yaml (DWB) 或
    # controller_server_rpp.yaml (Regulated Pure Pursuit)
    controller_yaml = PythonExpression([
        "'", os.path.join(config_dir, "controller_server_rpp.yaml"), "' if '",
        controller, "' == 'rpp' else '",
        os.path.join(config_dir, "controller_server.yaml"), "'"
    ])

    return LaunchDescription([
        DeclareLaunchArgument(
            "map",
            description="Path to the occupancy map yaml file",
        ),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("use_rviz", default_value="false"),
        DeclareLaunchArgument(
            "controller",
            default_value="dwb",
            description="Local controller: 'dwb' (default, verified working) or 'rpp' (Regulated Pure Pursuit, experimental)",
        ),
        DeclareLaunchArgument(
            "rviz_config",
            default_value=os.path.join(pkg_share, "rviz", "nav2.rviz"),
        ),

        # map_server: 发布 /map，供 global_costmap static_layer 和 RViz 使用
        # FastLIO localization 负责发布 map->odom TF，此处不启动 AMCL
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
            parameters=[
                controller_yaml,
                sim_time_param,
            ],
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
                        "/opt/ros/foxy/share/nav2_bt_navigator/behavior_trees",
                        "navigate_w_replanning_and_recovery.xml"
                    ),
                },
            ],
        ),

        # lifecycle_manager_map: 先激活 map_server，等待 /map 稳定
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="lifecycle_manager_map",
            output="screen",
            parameters=[
                sim_time_param,
                {
                    "autostart": True,
                    "node_names": ["map_server"],
                },
            ],
        ),

        # lifecycle_manager_nav: 延迟 4s 后激活规划/控制栈
        # 等待 FastLIO localization 发布 map->odom TF 后再激活，避免 costmap 激活超时
        TimerAction(
            period=4.0,
            actions=[
                Node(
                    package="nav2_lifecycle_manager",
                    executable="lifecycle_manager",
                    name="lifecycle_manager_navigation",
                    output="screen",
                    parameters=[
                        sim_time_param,
                        {
                            "autostart": True,
                            "node_names": [
                                "planner_server",
                                "controller_server",
                                "recoveries_server",
                                "bt_navigator",
                            ],
                        },
                    ],
                ),
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
    ])
