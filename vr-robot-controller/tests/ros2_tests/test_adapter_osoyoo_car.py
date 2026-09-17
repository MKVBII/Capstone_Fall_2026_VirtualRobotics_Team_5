"""Unit tests for adapter_osoyoo_car's differential-drive kinematics.

TODO: this only tests the pure-math kinematics (no rclpy/hardware needed).
Add integration tests (launch_testing) once the motor driver and RobotStatus
publishing are implemented.
"""
import pytest

# TODO: extract the kinematics math out of OsoyooCarAdapterNode.on_cmd_vel
# into a standalone function so it can be tested without constructing a
# full rclpy node (that's the more testable design — revisit
# osoyoo_car_adapter_node.py once this test is written).


def test_straight_forward_drives_both_wheels_equal():
    pytest.skip("TODO: implement once kinematics is extracted to a pure function")


def test_pure_rotation_drives_wheels_opposite():
    pytest.skip("TODO: implement once kinematics is extracted to a pure function")
