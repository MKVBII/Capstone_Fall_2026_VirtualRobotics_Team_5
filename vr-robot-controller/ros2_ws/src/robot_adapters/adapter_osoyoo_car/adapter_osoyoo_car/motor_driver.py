"""Low-level motor driver for the OSOYOO Pi Car's Model-Pi board (L298N).

Hardware, confirmed from OSOYOO's own documentation (see
docs/architecture.md section 5):
  * Direction: 4 GPIO pins (IN1, IN2, IN3, IN4) — one pair per motor
  * Speed: PWM through a PCA9685 module over I2C (ENA/ENB)

This module intentionally mirrors OSOYOO's own tutorial code
(RPi.GPIO + adafruit-circuitpython-pca9685) so their existing lessons stay
useful as a reference — it just gets called from a ROS 2 node instead of a
standalone script.

TODO:
  * Port real pin numbers from the OSOYOO wiring diagram / user manual.
  * Confirm Pi model in the kit — RPi.GPIO works on Pi 3/4; switch to
    rpi-lgpio or gpiozero (lgpio backend) if it's a Pi 5.
  * Implement set_left_speed / set_right_speed with PCA9685 PWM duty cycle.
"""


class OsoyooMotorDriver:
    """Wraps direct GPIO + PCA9685 calls. Speeds are floats in [-1.0, 1.0]."""

    def __init__(self):
        # TODO: initialize RPi.GPIO/rpi-lgpio pin modes and the PCA9685
        # I2C connection here. Keep this the ONLY place in the package that
        # touches hardware, so it stays swappable/testable.
        pass

    def set_left_speed(self, speed: float) -> None:
        """speed in [-1.0, 1.0]; sign sets direction via IN1/IN2, magnitude
        sets PWM duty cycle via the PCA9685 channel for ENA."""
        raise NotImplementedError

    def set_right_speed(self, speed: float) -> None:
        """Same as set_left_speed but for the IN3/IN4 + ENB pair."""
        raise NotImplementedError

    def stop(self) -> None:
        self.set_left_speed(0.0)
        self.set_right_speed(0.0)
