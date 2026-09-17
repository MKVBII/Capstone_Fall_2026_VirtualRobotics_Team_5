# Universal Controller — Message Contract Spec

This is the interface every robot adapter must implement. The VR client only
ever speaks these messages/topics — it never talks to a robot directly.

> TODO: keep this in sync with `ros2_ws/src/universal_controller_interface/msg/*.msg`
> as the definitions are filled in. Treat this file as the readable spec and
> the `.msg` files as the source of truth once they're implemented.

## Topics (planned)

| Topic | Type | Direction | Purpose |
|---|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | VR → Pi | Base locomotion: linear.x (forward/back), angular.z (turn) |
| `/controller/teleop_command` | `universal_controller_interface/TeleopCommand` | VR → Pi | Extended commands beyond base motion (mode switches, buttons) |
| `/controller/gripper_command` | `universal_controller_interface/GripperCommand` | VR → Pi | Gripper/servo control (not used by the OSOYOO car; reserved for future arm adapter) |
| `/robot/status` | `universal_controller_interface/RobotStatus` | Pi → VR | Battery, connection health, sensor summary (ultrasonic distance, line-tracking state) |
| `/robot/heartbeat` | `std_msgs/Header` or similar | VR ↔ Pi | Link-loss detection for the safety watchdog |

## Design rules

1. A robot adapter that can't fulfill part of the contract (e.g. no gripper)
   should still subscribe/no-op rather than requiring the VR client to know
   the robot doesn't have one.
2. All velocity commands are in SI units (m/s, rad/s) regardless of the
   underlying robot's native units — unit conversion happens inside the
   adapter, never in the VR client.
3. `RobotStatus` should degrade gracefully — fields the current robot doesn't
   support are left at a documented default rather than omitted, so the VR
   HUD doesn't need per-robot logic.
