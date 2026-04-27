import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode


def generate_launch_description():
    pkg_dir = get_package_share_directory('hdl_global_localization')
    config_dir = os.path.join(pkg_dir, 'config')

    container = ComposableNodeContainer(
        name='hdl_global_localization_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        composable_node_descriptions=[
            ComposableNode(
                package='hdl_global_localization',
                plugin='hdl_global_localization::GlobalLocalizationNode',
                name='hdl_global_localization',
                namespace='hdl_global_localization',
                parameters=[
                    os.path.join(config_dir, 'general_config.yaml'),
                    os.path.join(config_dir, 'bbs_config.yaml'),
                    os.path.join(config_dir, 'fpfh_config.yaml'),
                    os.path.join(config_dir, 'ransac_config.yaml'),
                ],
            )
        ],
        output='screen',
    )

    return LaunchDescription([container])
