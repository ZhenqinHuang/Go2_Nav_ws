import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('go2_pc2scan')

    z_min_arg = DeclareLaunchArgument('z_min', default_value='-0.30')
    z_max_arg = DeclareLaunchArgument('z_max', default_value='0.40')
    range_min_arg = DeclareLaunchArgument('range_min', default_value='0.25')
    range_max_arg = DeclareLaunchArgument('range_max', default_value='12.0')
    output_frame_arg = DeclareLaunchArgument('output_frame', default_value='base_link')

    cloud_filter_node = Node(
        package='go2_pc2scan',
        executable='cloud_filter_node.py',
        name='cloud_filter_node',
        output='screen',
        parameters=[
            os.path.join(pkg_share, 'config', 'cloud_filter_params.yaml'),
            {
                'z_min': LaunchConfiguration('z_min'),
                'z_max': LaunchConfiguration('z_max'),
                'range_min': LaunchConfiguration('range_min'),
                'range_max': LaunchConfiguration('range_max'),
                'output_frame': LaunchConfiguration('output_frame'),
            },
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
            {'use_inf': True, 'inf_epsilon': 1.0},
        ],
    )

    return LaunchDescription([
        z_min_arg,
        z_max_arg,
        range_min_arg,
        range_max_arg,
        output_frame_arg,
        cloud_filter_node,
        pc2scan_node,
    ])
