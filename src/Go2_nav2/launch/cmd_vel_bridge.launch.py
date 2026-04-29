import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory("go2_nav2")
    config_file = os.path.join(pkg_share, "config", "cmd_vel_bridge_params.yaml")

    return LaunchDescription([
        DeclareLaunchArgument("cmd_vel_topic", default_value="/cmd_vel"),

        Node(
            package="go2_nav2",
            executable="go2_cmd_vel_bridge_node",
            name="go2_cmd_vel_bridge",
            output="screen",
            parameters=[
                config_file,
                {"cmd_vel_topic": LaunchConfiguration("cmd_vel_topic")},
            ],
        ),
    ])
