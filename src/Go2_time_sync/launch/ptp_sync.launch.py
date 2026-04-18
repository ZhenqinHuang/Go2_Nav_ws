from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = FindPackageShare('go2_time_sync')

    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value=PathJoinSubstitution([pkg_share, 'config', 'ptp_sync.yaml']),
        description='PTP 同步配置文件路径'
    )

    skip_ntp_arg = DeclareLaunchArgument(
        'skip_ntp',
        default_value='false',
        description='跳过 NTP 本机时间校准步骤，直接启动 PTP'
    )

    ntp_dry_run_arg = DeclareLaunchArgument(
        'ntp_dry_run',
        default_value='false',
        description='NTP 仅检测偏差，不实际修改系统时钟'
    )

    ptp_sync_node = Node(
        package='go2_time_sync',
        executable='ptp_sync_node',
        name='ptp_sync_node',
        output='screen',
        parameters=[{
            'config_file': LaunchConfiguration('config_file'),
            'skip_ntp': LaunchConfiguration('skip_ntp'),
            'ntp_dry_run': LaunchConfiguration('ntp_dry_run'),
        }],
        # ptp4l 需要 root 权限，建议通过 sudo 或 capabilities 运行
        # 或在 systemd 服务中配置
    )

    ptp_monitor_node = Node(
        package='go2_time_sync',
        executable='ptp_monitor_node',
        name='ptp_monitor_node',
        output='screen',
    )

    return LaunchDescription([
        config_file_arg,
        skip_ntp_arg,
        ntp_dry_run_arg,
        ptp_sync_node,
        ptp_monitor_node,
    ])
