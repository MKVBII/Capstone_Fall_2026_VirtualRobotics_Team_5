"""The universal seam, generalized to cover wheeled/tracked robots AND
flying/boat-like robots with the same interface — this is what lets
someone drop in a driver for their own robot and have it work with the
existing server, mapping layer, and Quest page unchanged.

Design choice: rather than a car-shaped interface (`drive(left, right)`),
control is 4 generic continuous axes plus a named-command dispatch for
anything discrete and robot-specific (arm, takeoff, land, honk, whatever).
That's the same shape a game controller already provides (two 2-axis
sticks), and it covers both ends of the stated scope:

  * Wheeled/tracked robots only need 2 of the 4 axes (forward/back + turn)
    and no commands beyond the universal stop().
  * Flying/boat-like robots need all 4 axes (throttle/yaw/pitch/roll, or
    similar) plus discrete commands (arm/disarm, takeoff/land) that don't
    make sense to hardcode into this base class for a robot that doesn't
    have them — see command()/supported_commands() below.

Arm-type or legged robots are explicitly OUT of scope for this interface
(see docs/architecture.md) — they need per-joint/IK control, which is a
different enough problem that forcing it through this shape would make
the interface worse for the robots it's actually meant to cover.

See docs/adding_a_robot.md for the "implement this, drop the file in
drivers/, done" walkthrough, and drivers/_template_driver.py for a
fill-in-the-blanks starting point.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RobotStatus:
    """Robot -> headset telemetry. Mirrors docs/message_contract.md's
    `status` message. The well-known fields cover what the Quest HUD
    always shows; `extra` is for anything robot-specific (altitude,
    heading, flight mode, ...) that doesn't need a dedicated field to be
    useful — the client renders it generically (key: value) rather than
    needing per-robot UI code."""
    battery_voltage: float = 0.0
    obstacle_distance_m: float = -1.0          # -1 = not available
    line_tracking_sensors: list = field(default_factory=lambda: [False] * 5)
    connected: bool = True
    extra: dict = field(default_factory=dict)  # e.g. {"altitudeM": 1.2, "flightMode": "hover"}


class RobotDriver(ABC):
    """Implement this once per robot. Every method must be safe to call
    at any time, including immediately after construction and repeatedly
    from the watchdog's stop-on-timeout path.

    Two class attributes are required and are read WITHOUT instantiating
    the driver (see driver_registry.py) so the robot-select menu can list
    every available driver without touching any hardware until one is
    actually chosen:

        DISPLAY_NAME = "My Robot"
        DESCRIPTION = "One line shown in the menu."
    """

    DISPLAY_NAME: str = "Unnamed Robot"
    DESCRIPTION: str = ""

    @abstractmethod
    def set_axes(self, x: float, y: float, z: float, yaw: float) -> None:
        """4 generic continuous control axes, each already deadzone- and
        curve-applied by server.py — implementations should NOT apply
        their own deadzone/curve on top of this. Conventional meaning
        (follow it so manual control feels intuitive across robots):

          x    strafe / roll        (-1 left .. 1 right)
          y    forward-back / pitch (-1 back .. 1 forward)
          z    vertical / throttle  (-1 down .. 1 up; unused by ground robots)
          yaw  turn / yaw rate      (-1 left .. 1 right)

        A wheeled robot typically only reads y and yaw and mixes them
        into wheel speeds internally (see mapping.single_stick_mix for a
        ready-made helper); a drone typically reads all four and passes
        them close to directly into its flight-control SDK.
        """
        raise NotImplementedError

    @abstractmethod
    def set_camera_yaw(self, smoothed_deg: float) -> None:
        """smoothed_deg is already smoothed + rate-clamped by
        mapping.HeadYawSmoother, driven by the headset's head tracking
        (a separate continuous input from the controller axes above).
        Robots without a pan servo/gimbal can no-op."""
        raise NotImplementedError

    @abstractmethod
    def command(self, name: str, **kwargs) -> dict:
        """Execute a named, driver-specific discrete action — arm/disarm,
        takeoff/land, calibrate, honk, whatever this robot supports.
        Return a small JSON-serializable dict, e.g. {"ok": True} or
        {"ok": False, "error": "..."}"}. An unrecognized name should
        return {"ok": False, "error": "unsupported_command"} rather than
        raising — a bad command from the client should never crash the
        server or the driver."""
        raise NotImplementedError

    @abstractmethod
    def supported_commands(self) -> list:
        """List of command names this driver accepts, e.g.
        ["arm", "disarm", "takeoff", "land"]. Lets the Quest-side menu
        build command buttons dynamically per selected robot instead of
        hardcoding per-robot-type UI logic. Return [] if this robot has
        no discrete commands beyond the universal stop()."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Emergency stop / neutral position. Called by the watchdog on
        link loss, and whenever this driver is being swapped out for
        another one. Must never raise, and must be safe to call even if
        hardware init failed or was never completed."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> RobotStatus:
        """Read current sensors and return a RobotStatus snapshot."""
        raise NotImplementedError

    def shutdown(self) -> None:
        """Release hardware resources (GPIO.cleanup(), close sockets,
        disarm, etc.) before this driver instance is discarded — called
        when switching to a different robot at runtime, and on server
        shutdown. Default no-op; override if a driver claims any
        exclusive hardware (GPIO pins, a serial port, a UDP socket) that
        the NEXT driver might need. Must never raise. This is what makes
        "swap robots without restarting the server" safe rather than
        leaving the previous driver's pins/sockets held open."""
        pass
