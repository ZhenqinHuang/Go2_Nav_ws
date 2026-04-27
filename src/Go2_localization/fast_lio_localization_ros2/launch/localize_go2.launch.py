#!/usr/bin/env python3
# coding: utf-8

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition
from launch_ros.actions import Node


def generate_launch_description():
    rviz_arg = DeclareLaunchArgument('rviz', default_value='false')
    use_sim_time_arg = DeclareLaunchArgument('use_sim_time', default_value='false')

    default_pcd = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'PCD', 'MID360.pcd'
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
            'map_voxel_size': 0.2,
            'scan_voxel_size': 0.1,
            'fov': 6.28,
            'fov_far': 15.0,
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
