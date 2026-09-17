"""Launches rosbridge_server (WebSocket JSON bridge on port 9090) plus the
safety watchdog node. Included from controller_bringup/launch/bringup.launch.py
— don't launch this standalone in normal operation.
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{'port': 9090}],
        ),
        Node(
            package='universal_controller_bridge',
            executable='watchdog_node',
            name='controller_watchdog',
        ),
    ])
