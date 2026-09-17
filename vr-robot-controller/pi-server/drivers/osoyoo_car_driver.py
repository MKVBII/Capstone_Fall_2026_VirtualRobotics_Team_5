"""Concrete RobotDriver for the OSOYOO Robot Car Kit, model 2020005500 —
the first robot this project drives, and the reference implementation for
what a wheeled/tracked driver looks like (compare against
drivers/_template_driver.py's flying-robot notes).

Hardware, confirmed from the model 2020005500 manual (docs/architecture.md):
  * Motor driver: L298N-family board + OSOYOO PWM HAT v1.01 (PCA9685 over I2C)
  * Direction: 4 GPIO pins (IN1-IN4) — exact numbers TODO, read off the
    physical board/wiring diagram, the manual doesn't list them
  * Speed: PWM duty cycle via PCA9685 channels (ENA/ENB)
  * Line-tracking (5-ch IR array): GPIO 25, 9, 11, 8, 7
  * Ultrasonic (trigger/echo): GPIO 20, 21
  * Battery: onboard voltage meter
  * Confirmed Pi support: Pi 2, 3, 3A+, 4 only (no Pi 5) -> RPi.GPIO is
    the correct library, no rpi-lgpio fallback needed
  * SG90 servo included, used here for camera pan (set_camera_yaw)

This intentionally mirrors OSOYOO's own tutorial code (RPi.GPIO +
adafruit-circuitpython-pca9685) — see the OSOYOO Lesson 1 GPIO/PCA9685
links in docs/architecture.md Sources. You're replacing their input
source (a hardcoded test sequence) with WebSocket commands, not writing
motor control from scratch.
"""
from robot_driver_base import RobotDriver, RobotStatus
from mapping import single_stick_mix

# TODO: confirm against the physical board before wiring up real hardware.
LEFT_MOTOR_IN_PINS = (17, 18)     # (IN1, IN2) -- placeholder, verify
RIGHT_MOTOR_IN_PINS = (22, 23)    # (IN3, IN4) -- placeholder, verify
PCA9685_LEFT_PWM_CHANNEL = 0      # ENA
PCA9685_RIGHT_PWM_CHANNEL = 1     # ENB
PCA9685_SERVO_CHANNEL = 2         # SG90 camera pan servo

LINE_TRACKING_GPIO_PINS = (25, 9, 11, 8, 7)   # confirmed from manual
ULTRASONIC_TRIGGER_PIN, ULTRASONIC_ECHO_PIN = (20, 21)  # confirmed from manual


class OsoyooCarDriver(RobotDriver):
    DISPLAY_NAME = "OSOYOO Pi Car"
    DESCRIPTION = "2-wheel differential drive rover, model 2020005500"

    def __init__(self):
        self._hardware_ready = False
        # TODO: import RPi.GPIO and the PCA9685 library here (kept as a
        # local/deferred import so this module can be imported and unit
        # tested on a dev machine without RPi.GPIO installed):
        #
        #   import RPi.GPIO as GPIO
        #   from adafruit_pca9685 import PCA9685
        #   import board, busio
        #
        #   GPIO.setmode(GPIO.BCM)
        #   GPIO.setup(LEFT_MOTOR_IN_PINS + RIGHT_MOTOR_IN_PINS, GPIO.OUT)
        #   GPIO.setup(LINE_TRACKING_GPIO_PINS, GPIO.IN)
        #   GPIO.setup(ULTRASONIC_TRIGGER_PIN, GPIO.OUT)
        #   GPIO.setup(ULTRASONIC_ECHO_PIN, GPIO.IN)
        #   i2c = busio.I2C(board.SCL, board.SDA)
        #   self._pca = PCA9685(i2c)
        #   self._pca.frequency = 50
        #
        # self._hardware_ready = True
        pass

    def set_axes(self, x: float, y: float, z: float, yaw: float) -> None:
        # Ground vehicle: only forward/back (y) and turn (yaw) apply.
        # x (strafe) and z (vertical) are meaningless for this chassis
        # and are ignored — that's expected and fine per the interface.
        wheels = single_stick_mix(forward=y, turn=yaw)
        self._drive_wheels(wheels.left, wheels.right)

    def _drive_wheels(self, left: float, right: float) -> None:
        # TODO: set IN pins for direction (sign of left/right), then set
        # the PCA9685 duty cycle for magnitude on the matching channel.
        # e.g. GPIO.output(LEFT_MOTOR_IN_PINS[0], left >= 0)
        #      GPIO.output(LEFT_MOTOR_IN_PINS[1], left < 0)
        #      self._pca.channels[PCA9685_LEFT_PWM_CHANNEL].duty_cycle = int(abs(left) * 0xFFFF)
        raise NotImplementedError("wire up GPIO/PCA9685 calls once pins are confirmed")

    def set_camera_yaw(self, smoothed_deg: float) -> None:
        # TODO: convert degrees to a PCA9685 servo pulse width on
        # PCA9685_SERVO_CHANNEL. SG90 servos typically expect ~500-2500us
        # pulses for 0-180 degrees.
        raise NotImplementedError("wire up servo PWM once channel is confirmed")

    def command(self, name: str, **kwargs) -> dict:
        # This robot has no discrete commands beyond the universal stop().
        return {"ok": False, "error": "unsupported_command"}

    def supported_commands(self) -> list:
        return []

    def stop(self) -> None:
        # Must never raise, even if hardware was never initialized —
        # this is the watchdog's e-stop path.
        try:
            self._drive_wheels(0.0, 0.0)
        except Exception:
            pass

    def get_status(self) -> RobotStatus:
        # TODO: read ultrasonic (trigger pulse + measure echo pulse width),
        # read the 5 line-tracking GPIO pins, read battery voltage.
        return RobotStatus(
            battery_voltage=0.0,
            obstacle_distance_m=-1.0,
            line_tracking_sensors=[False] * 5,
            connected=self._hardware_ready,
        )

    def shutdown(self) -> None:
        # TODO: GPIO.cleanup() once real hardware init exists above —
        # important once a second driver (e.g. a drone) can be selected
        # at runtime, so it doesn't inherit GPIO pins this driver claimed.
        pass
