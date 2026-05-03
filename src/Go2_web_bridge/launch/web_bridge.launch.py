from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    server_url_arg = DeclareLaunchArgument(
        'server_url',
        default_value='ws://121.40.212.85:30100/ws/source'
                      '?token=c7e4a9d2b5f1c8e3a6d4b7f2c9a1e5d8&source_id=dog_001',
        description='WebSocket server URL',
    )
    odom_topic_arg = DeclareLaunchArgument(
        'odom_topic', default_value='/odom',
        description='里程计话题',
    )
    localization_topic_arg = DeclareLaunchArgument(
        'localization_topic', default_value='/localization',
        description='定位/导航状态话题',
    )
    odom_hz_arg = DeclareLaunchArgument(
        'odom_publish_hz', default_value='2.0',
        description='里程计上报频率 (Hz)',
    )
    nav_hz_arg = DeclareLaunchArgument(
        'nav_status_publish_hz', default_value='1.0',
        description='导航状态上报频率 (Hz)',
    )
    reconnect_arg = DeclareLaunchArgument(
        'reconnect_delay_sec', default_value='5.0',
        description='WebSocket 断线重连等待时间 (s)',
    )

    web_bridge_node = Node(
        package='Go2_web_bridge',
        executable='web_bridge_node.py',
        name='web_bridge_node',
        output='screen',
        parameters=[{
            'server_url': LaunchConfiguration('server_url'),
            'odom_topic': LaunchConfiguration('odom_topic'),
            'localization_topic': LaunchConfiguration('localization_topic'),
            'odom_publish_hz': LaunchConfiguration('odom_publish_hz'),
            'nav_status_publish_hz': LaunchConfiguration('nav_status_publish_hz'),
            'reconnect_delay_sec': LaunchConfiguration('reconnect_delay_sec'),
        }],
    )

    return LaunchDescription([
        server_url_arg,
        odom_topic_arg,
        localization_topic_arg,
        odom_hz_arg,
        nav_hz_arg,
        reconnect_arg,
        web_bridge_node,
    ])
