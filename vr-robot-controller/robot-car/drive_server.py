#!/usr/bin/env python3
"""
drive_server.py - Test 4: drive the car from the Quest's thumbsticks.

--- This code goes on the Raspberry Pi ---

It replaces connection_test.py as the thing listening on wss://...:8765.
joystick_control.html (running in the Quest browser) sends this, 25 times
a second:

    {"lx": 0.0, "ly": -0.8, "rx": 0.3, "ry": 0.0}

Each value is already -1.0 .. 1.0 with the deadzone and curve applied on
the Quest side, so this file does NOT repeat that. Its job is:

    1. pick out the two numbers we drive with
         throttle = -ly   (left stick forward/back; the Quest reports
                           "forward" as NEGATIVE, so we flip it here)
         turn     =  rx   (right stick left/right)
    2. MIX them into a left-wheel and a right-wheel value ("arcade drive")
         left  = throttle + turn
         right = throttle - turn
    3. turn each wheel value (-1..1) into what the hardware wants:
         sign      -> which direction pin is on   (gpiozero, IN1-IN4)
         magnitude -> PWM duty cycle on the HAT   (PCA9685, ENA/ENB)
    4. SAFETY: if no message arrives for 0.3 s (Wi-Fi drop, headset off,
       browser crash), stop the motors. Also stop on disconnect and exit.

RUN IT (from the folder that has cert.pem and key.pem, same as connection_test.py):
    python3 drive_server.py            # real motors - put the car ON A BLOCK first
    python3 drive_server.py --dry-run  # no hardware: just prints left/right values

PANIC: Ctrl+C (motors stop on the way out), or take the headset off.
"""

import asyncio
import json
import ssl
import sys
import time

import websockets


# =============================================================================
# CONFIG - everything you'd tune lives here.
# =============================================================================

# --- Network (must match joystick_control.html) ---------------------------
PORT = 8765
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

# --- Pins: copied exactly from motor_test.py (Test 1 passed with these) -----
IN1_PIN = 23   # left motor, direction A
IN2_PIN = 24   # left motor, direction B
IN3_PIN = 27   # right motor, direction A
IN4_PIN = 22   # right motor, direction B
ENA_CHANNEL = 0   # left motor speed  (PCA9685 channel)
ENB_CHANNEL = 1   # right motor speed (PCA9685 channel)
PWM_FREQUENCY = 1000

# --- Direction fixes -------------------------------------------------------
# motor_test.py treats "IN1 on / IN2 off" as forward. If pushing the stick
# forward makes a wheel spin BACKWARD, set that wheel's flag to True.
# (Both wheels backward -> set both True. One wheel backward -> just that one.)
LEFT_REVERSED = True
RIGHT_REVERSED = True

# --- Speed shaping ------------------------------------------------------------
# MIN_SPEED: the smallest duty cycle that actually turns the wheels.
#   motor_test.py notes these motors just hum below ~0.25. So any non-zero
#   stick input starts at MIN_SPEED instead of 0, otherwise the first chunk
#   of stick travel would do nothing.
# MAX_SPEED: a cap on full stick. Start low (0.6) for the first tests on the
#   floor, raise toward 1.0 once it behaves.
MIN_SPEED = 0.25
MAX_SPEED = 1.00

# TURN_GAIN: how strongly the right stick steers (1.0 = full spin-in-place
# at full right stick). Lower = gentler, easier to drive straight.
TURN_GAIN = 1.0

# --- Safety -----------------------------------------------------------------
WATCHDOG_TIMEOUT = 0.3   # seconds without a message before we stop the car


# =============================================================================
# THE MATH - pure functions, no hardware, so they can be tested anywhere.
# =============================================================================

def clamp(value, low=-1.0, high=1.0):
    """Keep a number inside [low, high]. Never trust numbers off the network."""
    return max(low, min(high, value))


def mix(throttle, turn):
    """
    Arcade-drive mixing: one throttle + one turn value -> left/right wheels.

      stick forward, no turn   ->  left =  1, right =  1   (straight)
      no throttle, turn right  ->  left =  1, right = -1   (spin right)
      forward + a bit right    ->  left > right            (curve right)

    If throttle + turn goes past 1.0 (e.g. full forward AND full right),
    both wheels are scaled down together so the RATIO between them - which
    is what decides the curve - is kept.
    """
    left = throttle + turn
    right = throttle - turn

    biggest = max(abs(left), abs(right))
    if biggest > 1.0:
        left /= biggest
        right /= biggest

    return left, right


def to_duty(wheel):
    """
    Wheel value (-1..1) -> (forward?, duty cycle 0..1) for the hardware.

    0 stays 0 (motor off). Anything else is stretched into
    MIN_SPEED..MAX_SPEED, so a tiny push still moves the car and full
    push hits the speed cap.
    """
    magnitude = abs(wheel)
    if magnitude == 0:
        return True, 0.0
    duty = MIN_SPEED + (MAX_SPEED - MIN_SPEED) * magnitude
    return wheel > 0, duty


def message_to_wheels(msg_text):
    """
    Turn one JSON message from the Quest into (left, right) wheel values.
    Returns None if the message isn't a joystick message (ignored).
    """
    try:
        data = json.loads(msg_text)
        ly = float(data["ly"])
        rx = float(data["rx"])
    except (ValueError, KeyError, TypeError):
        return None

    throttle = clamp(-ly)            # flip: Quest reports forward as negative
    turn = clamp(rx) * TURN_GAIN
    return mix(throttle, turn)


# =============================================================================
# HARDWARE - the same calls motor_test.py makes, wrapped in a class.
# =============================================================================

class Motors:
    def __init__(self):
        from gpiozero import OutputDevice
        import board
        import busio
        from adafruit_pca9685 import PCA9685

        self.in1 = OutputDevice(IN1_PIN)
        self.in2 = OutputDevice(IN2_PIN)
        self.in3 = OutputDevice(IN3_PIN)
        self.in4 = OutputDevice(IN4_PIN)

        self.pca = PCA9685(busio.I2C(board.SCL, board.SDA))
        self.pca.frequency = PWM_FREQUENCY

        # remember what each side is doing, so we only touch the pins
        # when something actually changes
        self.state = {"left": None, "right": None}

    def _set_speed(self, channel, fraction):
        fraction = clamp(fraction, 0.0, 1.0)
        self.pca.channels[channel].duty_cycle = int(fraction * 65535)

    def _set_side(self, side, wheel):
        forward, duty = to_duty(wheel)
        if side == "left":
            pin_a, pin_b, channel, reversed_ = self.in1, self.in2, ENA_CHANNEL, LEFT_REVERSED
        else:
            pin_a, pin_b, channel, reversed_ = self.in3, self.in4, ENB_CHANNEL, RIGHT_REVERSED
        if reversed_:
            forward = not forward

        new_state = (forward, round(duty, 3)) if duty > 0 else None
        old_state = self.state[side]
        if new_state == old_state:
            return  # nothing changed, skip the I2C write

        if new_state is None:
            # stop this side: power off, then both direction pins off
            self._set_speed(channel, 0)
            pin_a.off()
            pin_b.off()
        else:
            if old_state is None or old_state[0] != forward:
                # direction is changing: cut power BEFORE flipping pins,
                # so the H-bridge never switches direction under power
                self._set_speed(channel, 0)
                if forward:
                    pin_a.on()
                    pin_b.off()
                else:
                    pin_a.off()
                    pin_b.on()
            self._set_speed(channel, duty)

        self.state[side] = new_state

    def drive(self, left, right):
        self._set_side("left", left)
        self._set_side("right", right)

    def stop(self):
        self.drive(0.0, 0.0)

    def close(self):
        self.stop()
        self.pca.deinit()


class FakeMotors:
    """--dry-run: prints what the motors WOULD do. Proves the network + math
    without the battery on, before trusting it with real wheels."""

    def __init__(self):
        self.last = None

    def drive(self, left, right):
        now = (round(left, 2), round(right, 2))
        if now != self.last:
            lf, ld = to_duty(left)
            rf, rd = to_duty(right)
            print(f"left {left:+.2f} -> {'fwd' if lf else 'rev'} {ld:.2f}   "
                  f"right {right:+.2f} -> {'fwd' if rf else 'rev'} {rd:.2f}")
            self.last = now

    def stop(self):
        self.drive(0.0, 0.0)

    def close(self):
        self.stop()


# =============================================================================
# SERVER
# =============================================================================

motors = None
last_message_time = 0.0


async def handler(ws):
    global last_message_time
    print("headset connected")
    try:
        async for msg in ws:
            wheels = message_to_wheels(msg)
            if wheels is None:
                continue
            last_message_time = time.monotonic()
            motors.drive(*wheels)
    finally:
        # connection closed for any reason -> stop
        motors.stop()
        print("headset disconnected, motors stopped")


async def watchdog():
    """Runs on its own, separate from handler(), so a stuck or dropped
    connection can't keep the car driving."""
    stopped = True
    while True:
        await asyncio.sleep(0.05)
        silent = time.monotonic() - last_message_time > WATCHDOG_TIMEOUT
        if silent and not stopped:
            motors.stop()
            print("watchdog: no input for 0.3 s, motors stopped")
            stopped = True
        elif not silent:
            stopped = False


async def main():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)

    asyncio.create_task(watchdog())
    async with websockets.serve(handler, "0.0.0.0", PORT, ssl=ssl_context):
        print(f"drive server listening on wss://0.0.0.0:{PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    motors = FakeMotors() if dry_run else Motors()
    print("DRY RUN - no motors will move" if dry_run else
          "LIVE - motors armed. Car on a block for the first run!")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        motors.close()
        print("motors stopped, bye")
