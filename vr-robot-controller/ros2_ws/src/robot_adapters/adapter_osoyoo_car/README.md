# adapter_osoyoo_car

Robot adapter for the **OSOYOO Robot Car Kit for Raspberry Pi** — the first
robot this project is built and tested against.

- `motor_driver.py` — low-level GPIO (L298N direction) + PCA9685 (PWM speed) control, mirroring OSOYOO's own tutorial code
- `osoyoo_car_adapter_node.py` — ROS 2 node: `/cmd_vel` in, differential-drive kinematics, motor driver out; publishes `RobotStatus`

See `docs/architecture.md` section 5 for the hardware confirmation this was built from, and `docs/message_contracts.md` for the topic contract.
