"""Safety watchdog for the VR universal controller.

Independent of any robot adapter (see docs/architecture.md, section 3):
if heartbeat messages from the VR client stop arriving or the rosbridge
WebSocket connection drops, this node publishes a zero-velocity /cmd_vel
(and any other e-stop signal robot adapters should watch for) so a hung or
buggy adapter can never suppress an emergency stop.

TODO: implement heartbeat subscription + timeout logic, and decide the
e-stop signal shape (a dedicated topic vs. a zero Twist is the simplest
starting point for the OSOYOO car).
"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class WatchdogNode(Node):
    def __init__(self):
        super().__init__('controller_watchdog')
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        # TODO: subscribe to /robot/heartbeat, start a timeout timer,
        # publish Twist() (all zeros) on timeout.
        self.get_logger().info('Watchdog node started (stub — see TODOs).')


def main(args=None):
    rclpy.init(args=args)
    node = WatchdogNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
