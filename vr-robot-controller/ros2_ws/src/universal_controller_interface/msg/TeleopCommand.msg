# Extended teleop command beyond base velocity (which stays on
# geometry_msgs/Twist over /cmd_vel). Add fields here as the VR client grows
# more input modes (mode switches, speed multiplier, buttons, etc).
#
# TODO: define fields once the VR input mapping (vr-client/Assets/Scripts/Input)
# is settled. Keep this additive/backwards-compatible as robots are added.

std_msgs/Header header
