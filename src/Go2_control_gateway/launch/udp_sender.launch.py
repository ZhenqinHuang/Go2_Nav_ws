from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    package_share = get_package_share_directory("go2_control_gateway")
    parameters = os.path.join(package_share, "config", "udp_sender.yaml")
    return LaunchDescription(
        [
            Node(
                package="go2_control_gateway",
                executable="go2_cmd_vel_udp_sender",
                name="go2_cmd_vel_udp_sender",
                output="screen",
                parameters=[parameters],
            )
        ]
    )
