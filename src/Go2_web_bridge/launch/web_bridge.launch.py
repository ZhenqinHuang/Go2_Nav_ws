from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    tts_language_arg = DeclareLaunchArgument(
        'tts_language', default_value='zh',
        description='espeak-ng 语言代码，如 zh / en',
    )
    tts_speed_arg = DeclareLaunchArgument(
        'tts_speed', default_value='150',
        description='语速，单词/分钟',
    )
    tts_amplitude_arg = DeclareLaunchArgument(
        'tts_amplitude', default_value='100',
        description='音量 0~200',
    )
    tts_device_arg = DeclareLaunchArgument(
        'tts_alsa_device', default_value='default',
        description='ALSA 输出设备，如 default / plughw:1,0',
    )

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
    waypoints_file_arg = DeclareLaunchArgument(
        'waypoints_file',
        default_value=PathJoinSubstitution([
            FindPackageShare('Go2_web_bridge'), 'config', 'waypoints.yaml'
        ]),
        description='导航点位配置文件路径',
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
            'waypoints_file': LaunchConfiguration('waypoints_file'),
        }],
    )

    tts_node = Node(
        package='Go2_web_bridge',
        executable='tts_node.py',
        name='tts_node',
        output='screen',
        parameters=[{
            'tts_topic':   '/tts_text',
            'alsa_device': LaunchConfiguration('tts_alsa_device'),
            'language':    LaunchConfiguration('tts_language'),
            'speed':       LaunchConfiguration('tts_speed'),
            'amplitude':   LaunchConfiguration('tts_amplitude'),
        }],
    )

    return LaunchDescription([
        tts_language_arg,
        tts_speed_arg,
        tts_amplitude_arg,
        tts_device_arg,
        server_url_arg,
        odom_topic_arg,
        localization_topic_arg,
        odom_hz_arg,
        nav_hz_arg,
        reconnect_arg,
        waypoints_file_arg,
        web_bridge_node,
        tts_node,
    ])
