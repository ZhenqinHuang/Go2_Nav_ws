"""
odom_tf_bridge — Launch 文件

启动里程计转换节点：
  FAST-LIO2 /Odometry  →  NAV2 /odom  +  TF(odom→base_link)

用法：
  ros2 launch odom_tf_bridge odom_bridge.launch.py
  ros2 launch odom_tf_bridge odom_bridge.launch.py publish_tf:=false
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('odom_tf_bridge')

    # ── 可覆盖参数 ───────────────────────────────────────────────
    declare_pub_tf = DeclareLaunchArgument(
        'publish_tf', default_value='true',
        description='是否广播 odom→base_link TF（true/false）')

    declare_odom_frame = DeclareLaunchArgument(
        'odom_frame', default_value='odom',
        description='输出里程计的 header.frame_id')

    declare_base_frame = DeclareLaunchArgument(
        'base_frame', default_value='base_link',
        description='输出里程计的 child_frame_id')

    declare_in_topic = DeclareLaunchArgument(
        'fastlio_odom_topic', default_value='/Odometry',
        description='FAST-LIO2 里程计输入话题')

    declare_out_topic = DeclareLaunchArgument(
        'odom_topic', default_value='/odom',
        description='NAV2 里程计输出话题')

    # ── 节点 ─────────────────────────────────────────────────────
    bridge_node = Node(
        package='odom_tf_bridge',
        executable='odom_tf_bridge_node.py',
        name='odom_tf_bridge_node',
        output='screen',
        parameters=[
            os.path.join(pkg_share, 'config', 'odom_bridge_params.yaml'),
            {
                'publish_tf':          LaunchConfiguration('publish_tf'),
                'odom_frame':          LaunchConfiguration('odom_frame'),
                'base_frame':          LaunchConfiguration('base_frame'),
                'fastlio_odom_topic':  LaunchConfiguration('fastlio_odom_topic'),
                'odom_topic':          LaunchConfiguration('odom_topic'),
            }
        ],
    )

    return LaunchDescription([
        declare_pub_tf,
        declare_odom_frame,
        declare_base_frame,
        declare_in_topic,
        declare_out_topic,
        bridge_node,
    ])
