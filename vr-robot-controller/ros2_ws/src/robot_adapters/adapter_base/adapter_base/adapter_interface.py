"""Abstract base every robot adapter implements.

This is the boundary that makes the controller "universal" (see
docs/architecture.md section 3): the VR client, rosbridge, and safety
watchdog only ever talk to this interface's topics. A new robot means a new
subclass here, not changes anywhere upstream.

TODO: flesh out once adapter_osoyoo_car's concrete implementation settles
the exact shape of this interface.
"""
from abc import ABC, abstractmethod

from rclpy.node import Node


class RobotAdapter(Node, ABC):
    """Base class for a robot adapter node.

    Subclasses are expected to:
      * subscribe to /cmd_vel (geometry_msgs/Twist) and convert it to the
        robot's native drive calls
      * subscribe to universal_controller_interface/TeleopCommand and
        GripperCommand where applicable (no-op if the robot doesn't support
        a given command type)
      * publish universal_controller_interface/RobotStatus at a steady rate
      * stop all motion immediately on destroy/shutdown
    """

    @abstractmethod
    def on_cmd_vel(self, linear_x: float, angular_z: float) -> None:
        """Convert a velocity command into robot-specific motor output."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop all motion. Must be safe to call at any time,
        including from the safety watchdog's e-stop path."""
        raise NotImplementedError
