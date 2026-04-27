import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

def generate_launch_description():
    pkg_dir = get_package_share_directory('hdl_localization')
    global_loc_pkg_dir = get_package_share_directory('hdl_global_localization')

    points_topic = LaunchConfiguration('points_topic', default='/cloud_registered_body')
    globalmap_pcd = LaunchConfiguration('globalmap_pcd', default='/home/unitree/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd')

    params_path = os.path.join(pkg_dir, 'config', 'hdl_go2_params.yaml')
    global_loc_config_dir = os.path.join(global_loc_pkg_dir, 'config')

    # hdl_global_localization 必须先于 HdlLocalizationNodelet 就绪（后者启动时会等待其服务）
    global_loc_container = ComposableNodeContainer(
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
                    os.path.join(global_loc_config_dir, 'general_config.yaml'),
                    os.path.join(global_loc_config_dir, 'bbs_config.yaml'),
                    os.path.join(global_loc_config_dir, 'fpfh_config.yaml'),
                    os.path.join(global_loc_config_dir, 'ransac_config.yaml'),
                ],
            )
        ],
        output='screen',
    )

    localization_container = ComposableNodeContainer(
        name='hdl_localization_nodelet_manager',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        composable_node_descriptions=[
            ComposableNode(
                package='hdl_localization',
                plugin='hdl_localization::GlobalmapServerNodelet',
                name='GlobalmapServerNodelet',
                parameters=[
                    {'globalmap_pcd': globalmap_pcd},
                    {'convert_utm_to_local': False},
                    {'downsample_resolution': 0.1},
                ],
            ),
            ComposableNode(
                package='hdl_localization',
                plugin='hdl_localization::HdlLocalizationNodelet',
                name='HdlLocalizationNodelet',
                remappings=[
                    ('/velodyne_points', points_topic),
                    ('/odom', '/hdl_pose'),
                ],
                parameters=[params_path],
            ),
        ],
        output='screen',
    )

    return LaunchDescription([
        DeclareLaunchArgument('points_topic', default_value='/cloud_registered_body'),
        DeclareLaunchArgument('globalmap_pcd', default_value='/home/unitree/Go2_Nav_ws/src/Go2_localization/PCD/MID360.pcd'),
        global_loc_container,
        localization_container,
    ])
