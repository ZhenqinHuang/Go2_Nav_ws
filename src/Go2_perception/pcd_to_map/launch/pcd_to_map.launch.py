import os
import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('pcd_to_map')
    config_file = os.path.join(pkg_share, 'config', 'pcd_to_map_params.yaml')
    with open(config_file, 'r', encoding='utf-8') as stream:
        defaults = yaml.safe_load(stream)['pcd_to_occupancy']['ros__parameters']

    pcd_file_arg = DeclareLaunchArgument(
        'pcd_file',
        default_value='/home/nvidia/Go2_Nav_ws/maps/MID360.pcd',
        description='输入 PCD 文件的绝对路径',
    )
    output_path_arg = DeclareLaunchArgument(
        'output_path',
        default_value='/home/nvidia/Go2_Nav_ws/maps/MID360_map',
        description='输出地图路径前缀（不含扩展名），留空则不保存文件',
    )

    pcd_to_map_node = Node(
        package='pcd_to_map',
        executable='pcd_to_occupancy',
        name='pcd_to_occupancy',
        output='screen',
        parameters=[
            dict(defaults, **{
                'pcd_file': LaunchConfiguration('pcd_file'),
                'output_path': LaunchConfiguration('output_path'),
            }),
        ],
    )

    return LaunchDescription([
        pcd_file_arg,
        output_path_arg,
        pcd_to_map_node,
    ])
