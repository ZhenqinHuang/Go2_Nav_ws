from setuptools import setup

package_name = 'go2_time_sync'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    entry_points={
        'console_scripts': [
            'ptp_sync_node = go2_time_sync.ptp_sync_node:main',
            'ptp_monitor_node = go2_time_sync.ptp_monitor_node:main',
        ],
    },
)
