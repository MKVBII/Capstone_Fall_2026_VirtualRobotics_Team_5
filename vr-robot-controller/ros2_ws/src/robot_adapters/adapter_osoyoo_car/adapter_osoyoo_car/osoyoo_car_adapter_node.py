"""ROS 2 adapter node for the OSOYOO Pi Car.

Subscribes to /cmd_vel (geometry_msgs/Twist), converts linear.x/angular.z
into left/right wheel speeds using standard differential-drive kinematics,
and drives the motors via OsoyooMotorDriver. Publishes RobotStatus with the
ultrasonic + line-tracking readings.

This is the concrete implementation of adapter_base.RobotAdapter for the
first robot this project targets — see docs/architecture.md section 5 for
the hardware this maps to.

TODO:
  * Tune WHEEL_SEPARATION_M and MAX_LINEAR_SPEED_MPS for the actual chassis.
  * Wire up the ultrasonic + line-tracking sensor reads into RobotStatus.
  * Hook stop() into rclpy shutdown so the car doesn't run away if the node
    crashes or is killed.
"""
import rclpy
from geometry_msgs.msg import Twist

from adapter_base.adapter_interface import RobotAdapter
from adapter_osoyoo_car.motor_driver import OsoyooMotorDriver

WHEEL_SEPARATION_M = 0.15   # TODO: measure on the actual chassis
MAX_LINEAR_SPEED_MPS = 0.5  # TODO: calibrate


class OsoyooCarAdapterNode(RobotAdapter):
    def __init__(self):
        super().__init__('adapter_osoyoo_car')
        self.motor_driver = OsoyooMotorDriver()
        self.create_subscription(Twist, '/cmd_vel', self._on_cmd_vel_msg, 10)
        # TODO: create the RobotStatus publisher and a timer to publish it
        # at a steady rate, reading ultrasonic + line-tracking sensors.
        self.get_logger().info('OSOYOO car adapter started (stub — see TODOs).')

    def _on_cmd_vel_msg(self, msg: Twist) -> None:
        self.on_cmd_vel(msg.linear.x, msg.angular.z)

    def on_cmd_vel(self, linear_x: float, angular_z: float) -> None:
        # Standard differential-drive kinematics.
        left = linear_x - (angular_z * WHEEL_SEPARATION_M / 2.0)
        right = linear_x + (angular_z * WHEEL_SEPARATION_M / 2.0)
        # Normalize into [-1.0, 1.0] against the car's max speed.
        left_norm = max(-1.0, min(1.0, left / MAX_LINEAR_SPEED_MPS))
        right_norm = max(-1.0, min(1.0, right / MAX_LINEAR_SPEED_MPS))
        self.motor_driver.set_left_speed(left_norm)
        self.motor_driver.set_right_speed(right_norm)

    def stop(self) -> None:
        self.motor_driver.stop()


def main(args=None):
    rclpy.init(args=args)
    node = OsoyooCarAdapterNode()
    try:
        rclpy.spin(node)
    finally:
        node.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
