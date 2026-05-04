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
        executable='pcd_publisher',
        name='map_publisher',
        output='screen',
        parameters=[{
            'map': LaunchConfiguration('map'),
            'frame_id': 'map',
            'rate': 1.0,
            'publish_once': True,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }]
    )

    # 全局重定位（ICP，订阅 /cloud_registered world帧 和 /Odometry）
    # 注意：不得将 /cloud_registered 重映射到 /cloud_registered_body
    # ICP 需要 world 坐标系下的点云（frame_id="camera_init"），
    # /cloud_registered_body 是 body 坐标系，用于该目的会导致 T_map_to_odom 计算错误。
    global_loc = Node(
        package='fast_lio_localization_ros2',
        # Use the C++ node here. It uses MSE semantics for localization_th and
        # enforces max_delta_xy/max_delta_yaw_rad after the initial alignment.
        executable='global_localization',
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
            # Orin NX 16GB：CPU 核心弱，ICP 耗时是瓶颈
            # map_voxel_size 0.40：地图点数再减 ~30%，法线估计和 submap 裁剪都更快
            # scan_voxel_size 0.25：扫描点降采样同步加大，保持 scan/map 点密度比例一致
            # fov_far 10.0：从 12m 缩到 10m，submap 点数减少约 30%，是最直接的提速手段
            # freq_localization 1.5：Orin NX 跑完一次两阶段 ICP 约需 400~600ms，
            # 设 2.0 Hz 时 sleep 几乎为 0，实际频率反而不稳定；1.5 Hz 留出余量更可靠
            'map_voxel_size': 0.40,
            'scan_voxel_size': 0.25,
            'fov': 6.28,
            'freq_localization': 2.0,
            'fov_far': 10.0,
            # MSE 阈值：与原始默认值保持一致，过小会导致有效匹配被拒绝
            'localization_th': 0.10,
            # 单次最大矫正量：超出则拒绝，防止异常跳变（初始定位不受限）
            # 放宽 yaw 限制：0.52rad(30°) 太小，机器狗走歪后 ICP 结果会被持续拒绝导致无法收敛
            'max_delta_xy': 0.8,
            'max_delta_yaw_rad': 1.05,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }]
    )

    # TF 融合：map->odom->base_link，发布 /localization，符合 Nav2 要求
    # 订阅 odom_tf_bridge 发布的 /odom（RELIABLE），不重映射到 /Odometry（BEST_EFFORT），
    # 否则 QoS 不兼容导致消息接收失败。
    transform_fusion = Node(
        package='fast_lio_localization_ros2',
        # Use the C++ node here. The Python script publishes each /map_to_odom
        # jump immediately and ignores correction_time_constant_* parameters.
        executable='transform_fusion',
        name='transform_fusion',
        output='screen',
        remappings=[],
        parameters=[{
            'map_frame': 'map',
            'odom_frame': 'odom',
            'base_link_frame': 'base_link',
            # 平移矫正 0.3s 快速响应，yaw 矫正延长至 1.2s（约2个ICP周期）
            # 避免 yaw 还未收敛下一次 ICP 就到来导致持续抖动
            'correction_time_constant_xy': 0.3,
            'correction_time_constant_yaw': 1.2,
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
