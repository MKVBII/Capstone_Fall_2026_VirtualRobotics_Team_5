"""Brings up the full Pi-side stack in one command:

    ros2 launch controller_bringup bringup.launch.py

Includes rosbridge + the safety watchdog, the currently active robot
adapter (OSOYOO car by default), and video streaming.

TODO: parameterize which robot_adapter package/node to launch once a second
adapter exists (e.g. a `robot:=osoyoo_car` launch argument), instead of
hardcoding it below.
"""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    bridge_launch = os.path.join(
        get_package_share_directory('universal_controller_bridge'),
        'launch', 'rosbridge.launch.py')

    return LaunchDescription([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(bridge_launch)),
        Node(
            package='adapter_osoyoo_car',
            executable='osoyoo_car_adapter_node',
            name='adapter_osoyoo_car',
        ),
        Node(
            package='video_streaming',
            executable='camera_publisher_node',
            name='camera_publisher',
        ),
    ])
