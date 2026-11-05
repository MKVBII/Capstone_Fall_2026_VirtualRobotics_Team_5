#!/usr/bin/env python3
"""
camera_pan.py - the SG90 servo that turns the front camera left and right.

Runs on:   the Raspberry Pi, from ~/robot-car
Test:      python3 hardware/camera_pan.py            centre, look left, centre, look right, centre
           python3 hardware/camera_pan.py --center   just centre it, then go limp
           Run --center BEFORE fixing the servo arm and camera on: with the
           servo centred, attach the arm so the camera points straight ahead.
Used by:   drive_server.py (class CameraPan). The headset sends a "pan" angle
           from head tracking, and drive_server.py passes it on.
Hardware:  PWM HAT channel 15 (OSOYOO's Lesson 3 uses 15)
Install:   pip3 install adafruit-circuitpython-motor --break-system-packages

=============================================================================
HOW IT WORKS
=============================================================================
The servo plugs into the PWM HAT, the same PCA9685 chip that sets motor
speed. Adafruit's servo library turns an angle into the right pulse width.

ONE CATCH (see the PWM-frequency note in tests/motor_test.py): the PCA9685
has a single frequency for all 16 channels. Servos need ~50-60 Hz; the
motors used to run at 1000 Hz. So with the servo fitted, EVERYTHING runs at
60 Hz - the same setting OSOYOO's own code uses for this car. The motors
still work at 60 Hz but may hum a little and start moving at a slightly
different stick position (see MIN_SPEED in drive_server.py).

ANGLES: 0 = straight ahead, negative = LEFT, positive = RIGHT, in degrees.
If "left" turns the camera right, set PAN_REVERSED the other way.
"""

import sys
import time


# =============================================================================
# SETTINGS
# =============================================================================

PAN_CHANNEL = 15
# ^ Which PWM HAT channel the servo is plugged into (OSOYOO uses 15).

PWM_FREQUENCY = 60
# ^ Must match drive_server.py's PWM_FREQUENCY (one setting for the chip).

PAN_LIMIT = 70
# ^ Never turn further than this either way (degrees). Keeps the camera's
#   ribbon cable from being twisted, and the SG90 away from its end stops
#   (it buzzes and heats up if pushed against them).

PAN_REVERSED = True
# ^ True if the camera turns the wrong way. (Set True 2026-10-22: the
#   test showed left and right swapped on our car.)

CENTER_TRIM = 0
# ^ Degrees added to every angle. If "straight ahead" is a little off
#   (servo arms only fit in steps of ~10 degrees), nudge it with this.

MIN_PULSE_US, MAX_PULSE_US = 500, 2400
# ^ Pulse widths for the servo's two ends (microseconds). These are typical
#   for an SG90's ~180 degrees. Adafruit's defaults (750-2250) give a
#   narrower swing. If the servo buzzes at its ends, narrow these a bit.

MIN_STEP = 1.0
# ^ Ignore changes smaller than this (degrees). The headset sends 25 angles
#   a second; tiny changes would just make the servo twitch.


# =============================================================================
# THE SERVO
# =============================================================================

def clamp(value, low, high):
    """Keep value inside [low, high]."""
    return max(low, min(high, value))


class CameraPan:
    """The camera servo: point it with set(degrees), let go with release().

    Attributes:
        angle: the last angle set (degrees, + = right), or None when limp.
            drive_server.py sends it to the headset's info panel.
    """

    def __init__(self, pca=None):
        """Connect to the servo and centre it.

        Args:
            pca: the PCA9685 object drive_server.py already made, with its
                frequency ALREADY set to PWM_FREQUENCY (the servo library
                reads the frequency once, here, to work out its pulse timing).
                None = no hardware: set() just prints (for --dry-run).
        Raises:
            RuntimeError: if the PWM HAT isn't at PWM_FREQUENCY.
        """
        self.angle = None
        if pca is None:
            self.servo = None
        else:
            from adafruit_motor import servo
            # ^ Imported here, so --dry-run works without the library.
            if abs(pca.frequency - PWM_FREQUENCY) > 5:
                raise RuntimeError(f"PWM HAT is at {pca.frequency:.0f} Hz; the servo "
                                   f"needs {PWM_FREQUENCY} Hz (set PWM_FREQUENCY)")
            self.servo = servo.Servo(pca.channels[PAN_CHANNEL], actuation_range=180,
                                     min_pulse=MIN_PULSE_US, max_pulse=MAX_PULSE_US)
        self.set(0)

    def set(self, degrees):
        """Point the camera.

        Args:
            degrees: 0 = ahead, negative = left, positive = right. Clamped to
                +/-PAN_LIMIT; changes under MIN_STEP and non-numbers (junk off
                the network) are ignored.
        """
        try:
            degrees = clamp(float(degrees), -PAN_LIMIT, PAN_LIMIT)
        except (TypeError, ValueError):
            return                                   # junk off the network
        if self.angle is not None and abs(degrees - self.angle) < MIN_STEP:
            return
        self.angle = degrees
        servo_angle = 90 + (-degrees if PAN_REVERSED else degrees) + CENTER_TRIM
        # ^ The servo library counts 0..180 with 90 in the middle.
        servo_angle = clamp(servo_angle, 0, 180)
        if self.servo is None:
            print(f"camera pan {degrees:+.0f} deg")
        else:
            self.servo.angle = servo_angle

    def release(self):
        """Stop sending pulses: the servo goes limp (no buzzing, no power)."""
        if self.servo is not None:
            self.servo.angle = None
        self.angle = None


# =============================================================================
# TEST MODE: python3 hardware/camera_pan.py
# =============================================================================

if __name__ == "__main__":
    import board
    import busio
    from adafruit_pca9685 import PCA9685

    pca = PCA9685(busio.I2C(board.SCL, board.SDA))
    pca.frequency = PWM_FREQUENCY
    cam = CameraPan(pca)
    try:
        if "--center" in sys.argv:
            print("centred - attach the arm so the camera points straight ahead")
            time.sleep(1.5)
        else:
            for angle, label in [(0, "centre"), (-PAN_LIMIT, "LEFT"), (0, "centre"),
                                 (PAN_LIMIT, "RIGHT"), (0, "centre")]:
                print(f"{label:6} ({angle:+d} deg)")
                cam.set(angle)
                time.sleep(1.5)
            print("If LEFT/RIGHT were backwards, flip PAN_REVERSED.")
    except KeyboardInterrupt:
        pass
    finally:
        cam.release()
        pca.deinit()
        print("servo released, bye")
