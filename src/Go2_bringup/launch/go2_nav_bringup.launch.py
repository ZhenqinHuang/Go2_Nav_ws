"""
go2_nav_bringup.launch.py
─────────────────────────────────────────────────────────────────────
一键启动 Go2 导航感知链路：

  1. Livox MID360 驱动          → /livox/lidar, /livox/imu
  2. FAST-LIO2 建图/里程计      → /Odometry, /cloud_registered_body
  3. odom_tf_bridge             → /odom  +  TF(odom → base_link)
  4. go2_pc2scan (点云过滤)     → /cloud_filtered
  5. pointcloud_to_laserscan    → /scan

用法：
  ros2 launch go2_bringup go2_nav_bringup.launch.py
  ros2 launch go2_bringup go2_nav_bringup.launch.py rviz:=false
  ros2 launch go2_bringup go2_nav_bringup.launch.py z_min:=-0.30 z_max:=0.50
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # ── 包路径 ────────────────────────────────────────────────────
    livox_share    = get_package_share_directory('livox_ros_driver2')
    fastlio_share  = get_package_share_directory('fast_lio')
    odom_share     = get_package_share_directory('odom_tf_bridge')
    pc2scan_share  = get_package_share_directory('go2_pc2scan')

    # ── Launch 参数 ───────────────────────────────────────────────
    rviz_arg = DeclareLaunchArgument(
        'rviz', default_value='false',
        description='是否启动 RViz2 可视化')

    z_min_arg = DeclareLaunchArgument(
        'z_min', default_value='-0.25',
        description='点云高度切片下限 (m)，body坐标系')

    z_max_arg = DeclareLaunchArgument(
        'z_max', default_value='0.40',
        description='点云高度切片上限 (m)，body坐标系')

    range_min_arg = DeclareLaunchArgument(
        'range_min', default_value='0.25',
        description='最小水平检测距离 (m)')

    range_max_arg = DeclareLaunchArgument(
        'range_max', default_value='12.0',
        description='最大水平检测距离 (m)')

    publish_tf_arg = DeclareLaunchArgument(
        'publish_tf', default_value='true',
        description='是否广播 odom→base_link TF')

    # ── 1. Livox MID360 驱动（直接内联，避免依赖已删除的 nostatic launch 文件）──
    livox_config = os.path.join(livox_share, 'config', 'MID360_config.json')
    livox_node = Node(
        package='livox_ros_driver2',
        executable='livox_ros_driver2_node',
        name='livox_lidar_publisher',
        output='screen',
        parameters=[{
            'xfer_format': 1,
            'multi_topic': 0,
            'data_src': 0,
            'publish_freq': 10.0,
            'output_data_type': 0,
            'frame_id': 'livox_frame',
            'user_config_path': livox_config,
            'cmdline_input_bd_code': 'livox0000000001',
        }]
    )

    # ── 2. FAST-LIO2 ──────────────────────────────────────────────
    fastlio_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(fastlio_share, 'launch', 'mapping.launch.py')
        ),
        launch_arguments={
            'config_file': 'mid360.yaml',
            'rviz':        LaunchConfiguration('rviz'),
        }.items()
    )

    # ── 3. odom TF 桥接 ───────────────────────────────────────────
    odom_bridge_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(odom_share, 'launch', 'odom_bridge.launch.py')
        ),
        launch_arguments={
            'publish_tf': LaunchConfiguration('publish_tf'),
        }.items()
    )

    # ── 4+5. 点云过滤 + 转激光扫描 ───────────────────────────────
    pc2scan_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pc2scan_share, 'launch', 'pc2scan.launch.py')
        ),
        launch_arguments={
            'z_min':      LaunchConfiguration('z_min'),
            'z_max':      LaunchConfiguration('z_max'),
            'range_min':  LaunchConfiguration('range_min'),
            'range_max':  LaunchConfiguration('range_max'),
        }.items()
    )

    return LaunchDescription([
        # 参数声明
        rviz_arg,
        z_min_arg,
        z_max_arg,
        range_min_arg,
        range_max_arg,
        publish_tf_arg,
        # 启动顺序：驱动 → SLAM → 桥接 → 感知
        livox_node,
        fastlio_launch,
        odom_bridge_launch,
        pc2scan_launch,
    ])
