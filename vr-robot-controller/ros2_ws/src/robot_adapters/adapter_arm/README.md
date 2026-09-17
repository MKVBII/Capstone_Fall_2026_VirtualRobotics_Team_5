# adapter_arm (placeholder — future work)

Reserved for the second robot type this project adds after the OSOYOO car
is working end-to-end. Not started yet.

When this is built, it implements `adapter_base.RobotAdapter` the same way
`adapter_osoyoo_car` does, and uses the `GripperCommand` message from
`universal_controller_interface` that the OSOYOO car adapter leaves unused.
