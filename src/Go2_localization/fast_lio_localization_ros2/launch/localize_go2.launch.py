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
            # Orin NX 16GB 8 核充裕；优先保证大堂等开阔场景能稳定锁回
            # fov_far 10m：覆盖整个店铺对角线，大堂里也能看到远墙作为约束
            # （之前为省 CPU 调到 8m，导致大堂偶发失锁）
            'map_voxel_size': 0.40,
            'scan_voxel_size': 0.25,
            'fov': 6.28,
            # ICP 单次约 250-380ms。提到 3.5Hz（周期 285ms）让漂移累积窗口缩小 30%
            # CPU 单核 37% → ~52%，总 CPU 占用 +2-3%（实测仍有余量）
            'freq_localization': 3.5,
            'fov_far': 10.0,
            # MSE 阈值 0.10：保留默认值
            # 大堂特征稀疏时正常 MSE 会高于 0.07，收紧会让有效匹配被持续拒绝
            'localization_th': 0.10,
            # 单次最大修正量限制：防止 ICP 误匹配引发瞬移
            # 实测 FastLIO 长时间运行后漂移可达 1.2-1.9m（log:
            # "Correction rejected (dt_xy=1.886m > 0.800)"），原 0.8 阈值
            # 把所有真正的修正都拒了 → 重定位"后期精度差"
            # 抬到 2.0m：足以覆盖正常漂移；MSE 0.029-0.041 << 0.10 阈值
            # 表明 ICP 匹配质量极佳，误匹配风险低
            # yaw 修正实测 < 0.05rad，1.05 阈值富余很大，保持
            # 偶发的大跳变由 transform_fusion 平滑常数吸收
            # 注意：初始定位走另一路径（initialpose），不受这两个限制
            'max_delta_xy': 2.0,
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
            # ICP 修正幅度回到 0.8m/1.05rad 后，单次修正可能较大
            # 平移 0.3s 快速响应；yaw 1.0s 平滑大幅修正避免机器狗被"拽着转"
            'correction_time_constant_xy': 0.3,
            'correction_time_constant_yaw': 1.0,
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
