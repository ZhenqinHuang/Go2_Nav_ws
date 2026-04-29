#!/usr/bin/env python3
# coding: utf-8

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.conditions import IfCondition
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    rviz_arg = DeclareLaunchArgument('rviz', default_value='false')
    use_sim_time_arg = DeclareLaunchArgument('use_sim_time', default_value='false')

    # 使用 FindPackageShare 解析安装后的路径，colcon build（有无 --symlink-install）均正确
    default_pcd = PathJoinSubstitution(
        [FindPackageShare('fast_lio_localization_ros2'), 'PCD', 'MID360.pcd']
    )
    map_arg = DeclareLaunchArgument('map', default_value=default_pcd)

    # PCD 地图发布
    pcd_pub = Node(
        package='fast_lio_localization_ros2',
        executable='pcd_publisher.py',
        name='map_publisher',
        output='screen',
        parameters=[{
            'map': LaunchConfiguration('map'),
            'frame_id': 'map',
            'rate': 1.0,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }]
    )

    # 全局重定位（ICP，订阅 /cloud_registered world帧 和 /Odometry）
    # 注意：不得将 /cloud_registered 重映射到 /cloud_registered_body
    # ICP 需要 world 坐标系下的点云（frame_id="camera_init"），
    # /cloud_registered_body 是 body 坐标系，用于该目的会导致 T_map_to_odom 计算错误。
    global_loc = Node(
        package='fast_lio_localization_ros2',
        executable='global_localization_ros2.py',
        name='global_localization',
        output='screen',
        remappings=[
            ('/odom', '/Odometry'),
        ],
        parameters=[{
            'map2odom_completed': False,
            'region': 0,
            'map_frame': 'map',
            'odom_frame': 'odom',
            'base_link_frame': 'base_link',
            'map_voxel_size': 0.25,    # 稍大体素，减少地图点数，ICP更快
            'scan_voxel_size': 0.15,   # ICP扫描点降采样，减少法线估计计算量
            'fov': 6.28,
            # 每 3 秒矫正一次（CPU 与实时性的平衡点）
            'freq_localization': 0.33,
            # 稍微缩小 FOV 半径减少 submap 点数，加快 ICP
            'fov_far': 12.0,
            # MSE 阈值：与原始默认值保持一致，过小会导致有效匹配被拒绝
            'localization_th': 0.10,
            # 单次最大矫正量：超出则拒绝，防止异常跳变（初始定位不受限）
            'max_delta_xy': 1.5,
            'max_delta_yaw_rad': 1.05,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }]
    )

    # TF 融合：map->odom->base_link，发布 /localization，符合 Nav2 要求
    # 订阅 odom_tf_bridge 发布的 /odom（RELIABLE），不重映射到 /Odometry（BEST_EFFORT），
    # 否则 QoS 不兼容导致消息接收失败。
    transform_fusion = Node(
        package='fast_lio_localization_ros2',
        executable='transform_fusion_ros2.py',
        name='transform_fusion',
        output='screen',
        remappings=[],
        parameters=[{
            'map_frame': 'map',
            'odom_frame': 'odom',
            'base_link_frame': 'base_link',
            # ICP 矫正平滑时间常数：1.5s 内平滑过渡，避免 TF 阶跃跳变影响 Nav2
            'correction_time_constant': 1.5,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }]
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        condition=IfCondition(LaunchConfiguration('rviz'))
    )

    return LaunchDescription([
        rviz_arg,
        use_sim_time_arg,
        map_arg,
        pcd_pub,
        global_loc,
        transform_fusion,
        GroupAction([rviz_node], condition=IfCondition(LaunchConfiguration('rviz'))),
    ])
