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
            # 2.0m 实测过于宽松：ICP 局部极小值的错误匹配也被接受，
            # 叠加 xy 时间常数 0.3s，错误修正几乎瞬时生效 → 漂移级联
            # 0.8m 实测过于保守：长时间运行后真漂移 1.2-1.9m 全被拒
            # 折中 1.0m：配合 3.5Hz 高频，漂移来不及累积超过 1.0m
            # yaw 收紧到 0.5rad（~28°）：正常 yaw 漂移 <0.05rad，
            # 大于 0.5 的几乎都是误匹配
            'max_delta_xy': 1.0,
            'max_delta_yaw_rad': 0.5,
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
            # ICP 修正幅度限制到 1.0m 后，单次修正已受控
            # 平移 0.5s：比之前 0.3s 稍慢，给错误修正留缓冲窗口
            # yaw 2.0s：介于之前的 3.0（太慢修不回来）和 1.0（太快摆头）之间
            'correction_time_constant_xy': 0.5,
            'correction_time_constant_yaw': 2.0,
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
