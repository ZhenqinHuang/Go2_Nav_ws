from setuptools import setup
import os
from glob import glob

package_name = 'Go2_web_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='wangzheie',
    maintainer_email='wangzheie@example.com',
    description='WebSocket bridge for Go2 robot navigation',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'web_bridge_node = Go2_web_bridge.web_bridge_node:main',
            'tts_node = Go2_web_bridge.tts_node:main',
        ],
    },
)
