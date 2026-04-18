import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('livox_ros_driver2')
    config_path = os.path.join(pkg_share, 'config', 'MID360_config.json')

    livox_ros2_params = [
        {"xfer_format": 1},
        {"multi_topic": 0},
        {"data_src": 0},
        {"publish_freq": 10.0},
        {"output_data_type": 0},
        {"frame_id": 'livox_frame'},
        {"user_config_path": config_path},
        {"cmdline_input_bd_code": 'livox0000000001'}
    ]

    livox_driver = Node(
        package='livox_ros_driver2',
        executable='livox_ros_driver2_node',
        name='livox_lidar_publisher',
        output='screen',
        parameters=livox_ros2_params
    )

    return LaunchDescription([
        livox_driver,
    ])
