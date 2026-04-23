import os
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('go2_pc2scan')

    cloud_filter_node = Node(
        package='go2_pc2scan',
        executable='cloud_filter_node.py',
        name='cloud_filter_node',
        output='screen',
        parameters=[
            os.path.join(pkg_share, 'config', 'cloud_filter_params.yaml'),
        ],
    )

    pc2scan_node = Node(
        package='pointcloud_to_laserscan',
        executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan',
        output='screen',
        remappings=[
            ('cloud_in', '/cloud_filtered'),
            ('scan',     '/scan'),
        ],
        parameters=[
            os.path.join(pkg_share, 'config', 'pc2scan_params.yaml'),
            # pointcloud_to_laserscan 默认用 RELIABLE，需改为 BEST_EFFORT 匹配上游
            {'use_inf': True, 'inf_epsilon': 1.0},
        ],
    )

    return LaunchDescription([
        cloud_filter_node,
        pc2scan_node,
    ])
