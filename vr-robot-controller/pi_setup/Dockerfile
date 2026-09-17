# Optional containerized deployment of the Pi-side ROS 2 stack.
# Not required to get started — pi_setup/install.sh + systemd is the
# simpler path for a first working demo on the OSOYOO car. Revisit this
# if/when reproducible deployment across multiple Pis becomes worth it.
#
# TODO: build from an official ros:jazzy base image, copy ros2_ws/src,
# colcon build, and figure out GPIO/I2C device passthrough (--device flags)
# since the motor driver needs direct hardware access.
FROM ros:jazzy

# TODO
