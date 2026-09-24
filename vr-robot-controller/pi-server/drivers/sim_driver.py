"""A simulated robot with no hardware dependencies at all — no GPIO, no
serial, no SDK, no Pi required. Runs anywhere Python runs (your laptop).

Why this exists: it lets you demo the entire control loop — robot-select
menu, axis conditioning, the WebSocket protocol, discrete commands,
runtime robot switching, live status telemetry — before you have physical
access to the OSOYOO car or its Pi. It's also the fastest way to sanity
check quest-client/ or server.py changes without walking over to the
robot. It is a normal driver in every way the registry cares about: it
was auto-discovered from this file exactly like osoyoo_car_driver.py.
"""
import time

from robot_driver_base import RobotDriver, RobotStatus
from mapping import single_stick_mix


class SimDriver(RobotDriver):
    DISPLAY_NAME = "Simulated Rover (no hardware)"
    DESCRIPTION = "Fake wheeled robot for demos/dev — logs what it would do, needs no Pi or robot."

    def __init__(self):
        self._left = 0.0
        self._right = 0.0
        self._camera_deg = 0.0
        self._horn_count = 0
        self._start_time = time.monotonic()
        print("[sim_driver] initialized (no hardware touched)")

    def set_axes(self, x: float, y: float, z: float, yaw: float) -> None:
        # Same mixing a real wheeled robot would use — see mapping.py.
        wheels = single_stick_mix(forward=y, turn=yaw)
        self._left, self._right = wheels.left, wheels.right
        print(f"[sim_driver] wheels: left={self._left:+.2f} right={self._right:+.2f}")

    def set_camera_yaw(self, smoothed_deg: float) -> None:
        self._camera_deg = smoothed_deg

    def command(self, name: str, **kwargs) -> dict:
        if name == "honk":
            self._horn_count += 1
            print(f"[sim_driver] HONK! (#{self._horn_count})")
            return {"ok": True}
        return {"ok": False, "error": "unsupported_command"}

    def supported_commands(self) -> list:
        return ["honk"]

    def stop(self) -> None:
        self._left = 0.0
        self._right = 0.0
        print("[sim_driver] stop()")

    def get_status(self) -> RobotStatus:
        # Fake-but-plausible telemetry so the status HUD has something to
        # show. Battery drains slowly over the demo so it visibly moves.
        elapsed = time.monotonic() - self._start_time
        fake_battery = max(6.0, 8.4 - elapsed * 0.01)
        return RobotStatus(
            battery_voltage=fake_battery,
            obstacle_distance_m=1.5,
            line_tracking_sensors=[False, False, True, False, False],
            connected=True,
            extra={"simulated": True, "hornCount": self._horn_count, "cameraDeg": round(self._camera_deg, 1)},
        )

    def shutdown(self) -> None:
        print("[sim_driver] shutdown()")
