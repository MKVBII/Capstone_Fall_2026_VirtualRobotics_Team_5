"""Concrete RobotDriver for the OSOYOO Robot Car Kit, model 2020005500 —
the first robot this project drives, and the reference implementation for
what a wheeled/tracked driver looks like (compare against
drivers/_template_driver.py's flying-robot notes).

Hardware, confirmed from the model 2020005500 manual (docs/architecture.md):
  * Motor driver: L298N-family board + OSOYOO PWM HAT v1.01 (PCA9685 over I2C)
  * Direction: 4 GPIO pins (IN1-IN4), speed: PCA9685 channels (ENA/ENB)
  * Line-tracking (5-ch IR array): GPIO 25, 9, 11, 8, 7
  * Ultrasonic (trigger/echo): GPIO 20, 21
  * Battery: onboard voltage meter
  * Confirmed Pi support: Pi 2, 3, 3A+, 4 only (no Pi 5) -> RPi.GPIO is
    the correct library, no rpi-lgpio fallback needed
  * SG90 servo included (camera pan — not wired up here yet, see
    set_camera_yaw)

Motor pins and wiring come straight from OSOYOO's own Lesson 1 sample,
picar-basic.py (https://osoyoo.com/2022/07/21/osoyoo-raspberry-pi-car-v2-1-lesson-1-basic-install-and-coding-gpio-pca9685-python/):
    IN1 = 23, IN2 = 24   left motor direction
    IN3 = 27, IN4 = 22   right motor direction
    ENA = PCA9685 ch 0   left motor speed
    ENB = PCA9685 ch 1   right motor speed
    PCA9685 frequency 60 Hz
    forward = IN2/IN4 HIGH, IN1/IN3 LOW
We're replacing their input source (a hardcoded test sequence) with
WebSocket commands, not writing motor control from scratch.

Hardware libraries are imported inside __init__ (not at module top) so
this file can still be discovered and unit tested on a laptop with no
RPi.GPIO installed. If they're missing on the Pi, selecting this robot
fails cleanly with the error shown in the Quest menu instead of crashing
the server.
"""
import logging

from robot_driver_base import RobotDriver, RobotStatus
from mapping import single_stick_mix

log = logging.getLogger("osoyoo_car_driver")

# ---- Pins, from OSOYOO's Lesson 1 picar-basic.py -------------------------
LEFT_MOTOR_IN_PINS = (23, 24)     # (IN1, IN2)
RIGHT_MOTOR_IN_PINS = (27, 22)    # (IN3, IN4)
PCA9685_LEFT_PWM_CHANNEL = 0      # ENA
PCA9685_RIGHT_PWM_CHANNEL = 1     # ENB
PCA9685_FREQUENCY_HZ = 60

LINE_TRACKING_GPIO_PINS = (25, 9, 11, 8, 7)   # confirmed from manual (not read yet)
ULTRASONIC_TRIGGER_PIN, ULTRASONIC_ECHO_PIN = (20, 21)  # confirmed from manual (not read yet)

# ---- Tuning ---------------------------------------------------------------
# Full stick = this fraction of full motor power. OSOYOO's sample drives at
# 0x7FFF (50%); 0.7 gives a bit more headroom. Lower it for the first test.
MAX_SPEED = 0.7
# Below this duty the motors just hum without turning; treat as stopped.
MIN_EFFECTIVE_SPEED = 0.05
# If one side drives backward when you push forward, flip its flag here
# rather than rewiring.
INVERT_LEFT = False
INVERT_RIGHT = False

_DUTY_MAX = 0xFFFF  # PCA9685 duty_cycle is 16-bit in the adafruit library


class OsoyooCarDriver(RobotDriver):
    DISPLAY_NAME = "OSOYOO Pi Car"
    DESCRIPTION = "2-wheel differential drive rover, model 2020005500"

    def __init__(self):
        self._hardware_ready = False
        self._camera_deg = 0.0
        self._left = 0.0
        self._right = 0.0

        # Raises (ImportError, OSError, ...) if libraries or the HAT are
        # missing — server.py catches that and reports it to the Quest menu.
        import RPi.GPIO as GPIO
        import busio
        from board import SCL, SDA
        from adafruit_pca9685 import PCA9685

        self._GPIO = GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(list(LEFT_MOTOR_IN_PINS + RIGHT_MOTOR_IN_PINS), GPIO.OUT, initial=GPIO.LOW)

        i2c = busio.I2C(SCL, SDA)
        self._pca = PCA9685(i2c)
        self._pca.frequency = PCA9685_FREQUENCY_HZ

        self._hardware_ready = True
        self.stop()
        log.info("OSOYOO car hardware initialized (IN1-4 = %s %s, ENA/ENB = ch %d/%d)",
                 LEFT_MOTOR_IN_PINS, RIGHT_MOTOR_IN_PINS,
                 PCA9685_LEFT_PWM_CHANNEL, PCA9685_RIGHT_PWM_CHANNEL)

    # ---- driving ------------------------------------------------------------

    def set_axes(self, x: float, y: float, z: float, yaw: float) -> None:
        # Ground vehicle: only forward/back (y) and turn (yaw) apply.
        # x (strafe) and z (vertical) are ignored — expected per the interface.
        wheels = single_stick_mix(forward=y, turn=yaw)
        try:
            self._drive_wheels(wheels.left, wheels.right)
        except Exception as e:
            # A hardware hiccup (e.g. an I2C glitch) must stop the car, not
            # kill the WebSocket connection.
            log.error("Motor write failed (%s) — stopping", e)
            self.stop()

    def _drive_wheels(self, left: float, right: float) -> None:
        if not self._hardware_ready:
            return
        if INVERT_LEFT:
            left = -left
        if INVERT_RIGHT:
            right = -right
        self._left, self._right = left, right
        self._set_motor(LEFT_MOTOR_IN_PINS, PCA9685_LEFT_PWM_CHANNEL, left)
        self._set_motor(RIGHT_MOTOR_IN_PINS, PCA9685_RIGHT_PWM_CHANNEL, right)

    def _set_motor(self, in_pins, pwm_channel: int, speed: float) -> None:
        """speed is -1..1. Direction on the IN pins, magnitude on the PCA9685
        channel — same pattern as OSOYOO's forward()/backward()/stopcar()."""
        GPIO = self._GPIO
        pin_a, pin_b = in_pins  # (IN1, IN2) or (IN3, IN4)
        magnitude = min(abs(speed), 1.0) * MAX_SPEED

        if magnitude < MIN_EFFECTIVE_SPEED:
            GPIO.output(pin_a, GPIO.LOW)
            GPIO.output(pin_b, GPIO.LOW)
            self._pca.channels[pwm_channel].duty_cycle = 0
            return

        if speed > 0:   # forward: IN2/IN4 HIGH, IN1/IN3 LOW (per OSOYOO forward())
            GPIO.output(pin_a, GPIO.LOW)
            GPIO.output(pin_b, GPIO.HIGH)
        else:           # backward: the reverse
            GPIO.output(pin_a, GPIO.HIGH)
            GPIO.output(pin_b, GPIO.LOW)
        self._pca.channels[pwm_channel].duty_cycle = int(magnitude * _DUTY_MAX)

    def set_camera_yaw(self, smoothed_deg: float) -> None:
        # No-op for now: Lesson 1 doesn't say which PCA9685 channel the
        # SG90 is on. Once that's confirmed, convert degrees to a ~500-2500us
        # pulse on that channel here. Must not raise — server.py calls this
        # on every control message.
        self._camera_deg = smoothed_deg

    # ---- commands / safety ------------------------------------------------------

    def command(self, name: str, **kwargs) -> dict:
        # This robot has no discrete commands beyond the universal stop().
        return {"ok": False, "error": "unsupported_command"}

    def supported_commands(self) -> list:
        return []

    def stop(self) -> None:
        # Must never raise, even if hardware was never initialized —
        # this is the watchdog's e-stop path. Mirrors OSOYOO's stopcar().
        self._left = self._right = 0.0
        if not self._hardware_ready:
            return
        try:
            for pin in LEFT_MOTOR_IN_PINS + RIGHT_MOTOR_IN_PINS:
                self._GPIO.output(pin, self._GPIO.LOW)
        except Exception as e:
            log.error("stop(): GPIO write failed: %s", e)
        try:
            self._pca.channels[PCA9685_LEFT_PWM_CHANNEL].duty_cycle = 0
            self._pca.channels[PCA9685_RIGHT_PWM_CHANNEL].duty_cycle = 0
        except Exception as e:
            log.error("stop(): PCA9685 write failed: %s", e)

    def get_status(self) -> RobotStatus:
        # TODO: read ultrasonic (trigger pulse + measure echo pulse width),
        # read the 5 line-tracking GPIO pins, read battery voltage.
        return RobotStatus(
            battery_voltage=0.0,
            obstacle_distance_m=-1.0,
            line_tracking_sensors=[False] * 5,
            connected=self._hardware_ready,
            extra={"leftMotor": round(self._left, 2), "rightMotor": round(self._right, 2)},
        )

    def shutdown(self) -> None:
        # Release the pins so a different driver selected next can use them.
        self.stop()
        if not self._hardware_ready:
            return
        try:
            self._pca.deinit()
        except Exception as e:
            log.error("shutdown(): PCA9685 deinit failed: %s", e)
        try:
            self._GPIO.cleanup(list(LEFT_MOTOR_IN_PINS + RIGHT_MOTOR_IN_PINS))
        except Exception as e:
            log.error("shutdown(): GPIO cleanup failed: %s", e)
        self._hardware_ready = False
