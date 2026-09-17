"""TEMPLATE — copy this file to drivers/<your_robot_name>.py, fill in the
methods below, and it will show up in the robot-select menu next time the
server starts (or after a "reload drivers" without even restarting — see
docs/adding_a_robot.md). That's the whole process.

This file starts with "_" on purpose — driver_registry.py skips any
drivers/ file starting with "_", so this template itself never shows up
as a selectable (broken, unimplemented) robot. Your copy should NOT start
with "_".

You only need to:
  1. Rename the class to something specific (the name doesn't matter —
     the registry finds it by checking "does this subclass RobotDriver",
     not by name).
  2. Set DISPLAY_NAME and DESCRIPTION.
  3. Implement the methods below for your robot's actual hardware/SDK.
  4. Delete whichever of the two worked examples (wheeled vs flying)
     doesn't apply, and adapt the other.

You do NOT need to touch server.py, mapping.py, driver_registry.py, or
anything in quest-client/ — that's the point of this interface.
"""
from robot_driver_base import RobotDriver, RobotStatus

# If you need deadzone/curve helpers for a mix your robot needs that
# mapping.py doesn't already provide, add pure functions there rather
# than duplicating math here — see mapping.py's existing functions.
from mapping import single_stick_mix


class MyRobotDriver(RobotDriver):
    # Shown in the Quest-side robot-select menu. Required.
    DISPLAY_NAME = "My Robot"
    DESCRIPTION = "One line describing it — shown under the name in the menu."

    def __init__(self):
        """Set up whatever connection your robot needs: GPIO pins, a
        serial port, a UDP socket to an SDK, etc. This runs only when
        someone actually selects this robot from the menu — not at
        server startup, and not just because the file exists in
        drivers/. Keep this fast (a few seconds at most) since it's on
        the critical path of "pick a robot, drive it" during a demo.
        """
        # EXAMPLE (wheeled — see osoyoo_car_driver.py for the real version):
        #   import RPi.GPIO as GPIO
        #   GPIO.setmode(GPIO.BCM)
        #   GPIO.setup(YOUR_PINS, GPIO.OUT)
        #
        # EXAMPLE (flying, SDK-based — e.g. a Tello-style drone):
        #   from djitellopy import Tello
        #   self._drone = Tello()
        #   self._drone.connect()
        pass

    def set_axes(self, x: float, y: float, z: float, yaw: float) -> None:
        """Called on every control update (throttled to ~20-30/sec by the
        Quest page), with 4 values already in [-1.0, 1.0] and already
        deadzone/curve-applied — don't re-apply those here.

        x    strafe / roll        (-1 left .. 1 right)
        y    forward-back / pitch (-1 back .. 1 forward)
        z    vertical / throttle  (-1 down .. 1 up)
        yaw  turn / yaw rate      (-1 left .. 1 right)

        Use only the axes that make sense for your robot; ignore the rest.
        """
        # EXAMPLE (wheeled — 2 axes, mixed into left/right wheel speed):
        #   wheels = single_stick_mix(forward=y, turn=yaw)
        #   self._set_wheel_speeds(wheels.left, wheels.right)
        #
        # EXAMPLE (flying — all 4 axes, close to a direct SDK passthrough):
        #   self._drone.send_rc_control(
        #       left_right_velocity=int(x * 100),
        #       forward_backward_velocity=int(y * 100),
        #       up_down_velocity=int(z * 100),
        #       yaw_velocity=int(yaw * 100),
        #   )
        raise NotImplementedError("implement set_axes for your robot")

    def set_camera_yaw(self, smoothed_deg: float) -> None:
        """Driven by the headset's head tracking, not the controller
        sticks. No-op if your robot has no pan servo/gimbal — that's a
        completely valid implementation, don't force one."""
        pass

    def command(self, name: str, **kwargs) -> dict:
        """Handle discrete, named actions — see supported_commands()
        below for what to list here. Always return a dict; never raise.
        """
        # EXAMPLE (flying):
        #   if name == "takeoff":
        #       self._drone.takeoff()
        #       return {"ok": True}
        #   if name == "land":
        #       self._drone.land()
        #       return {"ok": True}
        return {"ok": False, "error": "unsupported_command"}

    def supported_commands(self) -> list:
        """Command names this robot accepts via command() above, e.g.
        ["takeoff", "land"]. Return [] if there are none beyond the
        universal stop() — that's normal for a simple wheeled robot."""
        return []

    def stop(self) -> None:
        """Emergency stop / neutral. Called by the watchdog on link loss
        and whenever this driver is swapped out for another one at
        runtime. MUST NOT RAISE, ever — wrap risky calls in try/except.
        This is the single most safety-critical method in the whole
        driver; get it right even if everything else is a rough draft.
        """
        # EXAMPLE (wheeled):
        #   self._set_wheel_speeds(0.0, 0.0)
        #
        # EXAMPLE (flying — don't try to land automatically here, that's
        # a much bigger action than "stop"; hover/zero out control instead):
        #   try:
        #       self._drone.send_rc_control(0, 0, 0, 0)
        #   except Exception:
        #       pass
        pass

    def get_status(self) -> RobotStatus:
        """Return current telemetry. Leave fields you don't support at
        their default (see robot_driver_base.RobotStatus) rather than
        guessing a value. Use `extra={}` for anything robot-specific
        that doesn't fit the standard fields (altitude, heading, ...) —
        the Quest HUD renders it generically."""
        return RobotStatus(
            battery_voltage=0.0,
            connected=True,
            extra={},
        )

    def shutdown(self) -> None:
        """Release anything __init__ acquired — GPIO pins, sockets,
        serial ports. Called before this driver is discarded (runtime
        robot swap, or server shutdown). Default is a no-op; override
        this if you claimed exclusive hardware, so the next selected
        robot doesn't fail to initialize because you're still holding
        a pin/port open. Must never raise."""
        pass
