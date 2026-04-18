"""
go2_pc2scan — 点云转激光扫描完整 Launch 文件

数据流：
  FAST-LIO2
    └─ /cloud_registered_body (PointCloud2, body 坐标系)
         └─ cloud_filter_node (高度+距离过滤 + 体素降采)
              └─ /cloud_filtered (PointCloud2, body 坐标系)
                   └─ pointcloud_to_laserscan (官方 ROS2 包)
                        └─ /scan (LaserScan, NAV2 输入)

用法：
  ros2 launch go2_pc2scan pc2scan.launch.py
  ros2 launch go2_pc2scan pc2scan.launch.py z_min:=-0.30 z_max:=0.50
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('go2_pc2scan')

    # ── Launch 参数（运行时可覆盖）──────────────────────────────
    z_min_arg = DeclareLaunchArgument(
        'z_min', default_value='-0.25',
        description='Body坐标系高度切片下限 (m)，z轴向上; z_min=-0.25→离地约0.10m')

    z_max_arg = DeclareLaunchArgument(
        'z_max', default_value='0.40',
        description='Body坐标系高度切片上限 (m)，z轴向上; z_max=0.40→离地约0.75m')

    range_min_arg = DeclareLaunchArgument(
        'range_min', default_value='0.25',
        description='最小水平检测距离 (m)，过滤机体自身反射')

    range_max_arg = DeclareLaunchArgument(
        'range_max', default_value='12.0',
        description='最大水平检测距离 (m)，店铺对角线约12m')

    voxel_arg = DeclareLaunchArgument(
        'downsample_voxel', default_value='0.05',
        description='体素降采样大小 (m)，0=禁用')

    cloud_in_arg = DeclareLaunchArgument(
        'cloud_in_topic', default_value='/cloud_registered_body',
        description='FAST-LIO2 输出的 body 坐标系点云话题')

    # ── 节点1: 点云过滤节点 ──────────────────────────────────────
    cloud_filter_node = Node(
        package='go2_pc2scan',
        executable='cloud_filter_node.py',
        name='cloud_filter_node',
        output='screen',
        parameters=[
            os.path.join(pkg_share, 'config', 'cloud_filter_params.yaml'),
            {
                'cloud_in_topic':   LaunchConfiguration('cloud_in_topic'),
                'z_min':            LaunchConfiguration('z_min'),
                'z_max':            LaunchConfiguration('z_max'),
                'range_min':        LaunchConfiguration('range_min'),
                'range_max':        LaunchConfiguration('range_max'),
                'downsample_voxel': LaunchConfiguration('downsample_voxel'),
            }
        ],
    )

    # ── 节点2: pointcloud_to_laserscan（官方包）──────────────────
    # 使用 ROS2 官方 pointcloud_to_laserscan 包的 pointcloud_to_laserscan 节点
    # 输入：/cloud_filtered → 输出：/scan
    pc2scan_node = Node(
        package='pointcloud_to_laserscan',
        executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan',
        output='screen',
        parameters=[
            os.path.join(pkg_share, 'config', 'pc2scan_params.yaml'),
            {
                # 动态参数也可从 launch 参数传入
                'range_min': LaunchConfiguration('range_min'),
                'range_max': LaunchConfiguration('range_max'),
            }
        ],
        remappings=[
            # 输入：过滤后的点云
            ('cloud_in',  '/cloud_filtered'),
            # 输出：供 NAV2 使用的激光扫描
            ('scan',      '/scan'),
        ],
    )

    return LaunchDescription([
        # 参数声明
        z_min_arg,
        z_max_arg,
        range_min_arg,
        range_max_arg,
        voxel_arg,
        cloud_in_arg,
        # 节点
        cloud_filter_node,
        pc2scan_node,
    ])
