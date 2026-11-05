#!/usr/bin/env python3
"""
drive_server.py - drive the car from the Quest's thumbsticks.

Runs on:   the Raspberry Pi, from ~/robot-car (the folder with cert.pem and
           key.pem, which camera_server.py creates on its first run)
Run:       python3 drive_server.py              real motors - car ON A BLOCK for the first run
           python3 drive_server.py --dry-run    no motors: prints the wheel values instead
Flags:     --no-floor     no DOWN sensor: no edge detection (use with the car on a block)
           --no-back      no BACK sensor: no obstacle detection
           --fake-sensor  made-up rear readings (testing without the sensors)
Listens:   wss://PI_IP:8765 - the headset page (web/js/drive.js) connects here
Uses:      hardware/rear_sensor.py   the two rear ultrasonic sensors
           hardware/camera_pan.py    the front camera servo
           hardware/pi_status.py     Pi temperature, load, Wi-Fi, power

PANIC: Ctrl+C (the motors stop on the way out), or take the headset off.

=============================================================================
WHAT IT DOES
=============================================================================
The headset sends this 25 times a second:

    {"lx": 0.0, "ly": -0.8, "rx": 0.3, "ry": 0.0, "pan": 12}

Each stick value is already -1.0 .. 1.0 with the deadzone and curve applied
on the Quest side, so this file does NOT repeat that. For each message:

    1. Pick out the two numbers we drive with:
         throttle = -ly   (left stick forward/back; the Quest reports
                           "forward" as NEGATIVE, so we flip it here)
         turn     =  rx   (right stick left/right)
    2. MIX them into a left-wheel and a right-wheel value ("arcade drive"):
         left  = throttle + turn
         right = throttle - turn
    3. Limit REVERSE using the rear sensors (something behind the car, or
       the floor dropping away). Forward is never limited.
    4. Turn each wheel value (-1..1) into what the hardware wants:
         sign      -> which direction pin is on   (gpiozero, IN1-IN4)
         magnitude -> PWM duty cycle on the HAT   (PCA9685, ENA/ENB)
    5. Point the camera servo at "pan" degrees (+ = right), if it was sent.

SAFETY: if no message arrives for 0.3 s (Wi-Fi drop, headset off, browser
crash), the motors stop. They also stop when the headset disconnects and
when this program exits.

MESSAGES BACK TO THE HEADSET (on the same WebSocket):
    {"type": "rear", ...}     rear sensors + wheel power, 10x a second
    {"type": "status", ...}   Pi health + camera angle, once a second
    {"type": "pong", "t"}     reply to the headset's {"type": "ping", "t"},
                              so it can show the control-link delay
"""

import asyncio
import json
import ssl
import sys
import time

import websockets

from hardware import pi_status                       # Pi health, for the info panel
from hardware.camera_pan import CameraPan            # front camera servo
from hardware.rear_sensor import RearSensor, limit_reverse, describe_calibration   # rear sensors


# =============================================================================
# SETTINGS - everything you'd tune lives here.
# =============================================================================

# --- Network (must match DRIVE_PORT in camera_server.py) ---------------------
PORT = 8765
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

# --- Pins: copied exactly from tests/motor_test.py (Test 1 passed with these) -
IN1_PIN = 23   # left motor, direction A
IN2_PIN = 24   # left motor, direction B
IN3_PIN = 27   # right motor, direction A
IN4_PIN = 22   # right motor, direction B
ENA_CHANNEL = 0   # left motor speed  (PCA9685 channel)
ENB_CHANNEL = 1   # right motor speed (PCA9685 channel)
PWM_FREQUENCY = 60
# ^ The camera servo shares the PWM HAT, and the HAT has ONE frequency for
#   all channels; servos need 50-60 Hz. 60 Hz is what OSOYOO's own code uses
#   for this car. (Was 1000 before the servo; MIN_SPEED below was re-checked.)

# --- Direction fixes ---------------------------------------------------------
# motor_test.py treats "IN1 on / IN2 off" as forward. If pushing the stick
# forward makes a wheel spin BACKWARD, set that wheel's flag to True.
# (Both wheels backward -> set both True. One wheel backward -> just that one.)
LEFT_REVERSED = True
RIGHT_REVERSED = True

# --- Speed shaping -----------------------------------------------------------
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

# --- Safety ------------------------------------------------------------------
WATCHDOG_TIMEOUT = 0.3   # seconds without a message before we stop the car


# =============================================================================
# THE MATH - pure functions, no hardware, so they can be tested anywhere.
# =============================================================================

def clamp(value, low=-1.0, high=1.0):
    """Keep a number inside [low, high]. Never trust numbers off the network.

    Args:
        value: the number to limit.
        low, high: the allowed range (default -1.0 .. 1.0).
    Returns:
        value, moved to the nearest end of the range if it was outside it.
    """
    return max(low, min(high, value))


def mix(throttle, turn):
    """Arcade-drive mixing: one throttle + one turn value -> left/right wheels.

      stick forward, no turn   ->  left =  1, right =  1   (straight)
      no throttle, turn right  ->  left =  1, right = -1   (spin right)
      forward + a bit right    ->  left > right            (curve right)

    If throttle + turn goes past 1.0 (e.g. full forward AND full right),
    both wheels are scaled down together so the RATIO between them - which
    is what decides the curve - is kept.

    Args:
        throttle: -1 (full back) .. 1 (full forward).
        turn: -1 (full left) .. 1 (full right).
    Returns:
        (left, right) wheel values, each -1 .. 1 (negative = backward).
    """
    left = throttle + turn
    right = throttle - turn

    biggest = max(abs(left), abs(right))
    if biggest > 1.0:
        left /= biggest
        right /= biggest

    return left, right


def to_duty(wheel):
    """Wheel value -> (forward?, duty cycle) for the hardware.

    0 stays 0 (motor off). Anything else is stretched into
    MIN_SPEED..MAX_SPEED, so a tiny push still moves the car and a full
    push hits the speed cap.

    Args:
        wheel: -1 .. 1 (negative = backward).
    Returns:
        (forward, duty): forward is True/False, duty is 0..1.
    """
    magnitude = abs(wheel)
    if magnitude == 0:
        return True, 0.0
    duty = MIN_SPEED + (MAX_SPEED - MIN_SPEED) * magnitude
    return wheel > 0, duty


def message_to_wheels(msg_text):
    """Turn one JSON message from the Quest into wheel values.

    Args:
        msg_text: the message as received, e.g. '{"lx":0,"ly":-0.8,"rx":0.3,"ry":0}'.
    Returns:
        (left, right) wheel values, or None if it isn't a joystick message
        (it's then ignored).
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
    """The two drive motors (and the camera servo, which shares the PWM HAT).

    Direction comes from four gpiozero pins (IN1-IN4); speed from two PWM
    channels on the PCA9685 HAT (ENA/ENB). Pin writes only happen when
    something actually changes.
    """

    def __init__(self):
        """Claim the direction pins, open the PWM HAT, set its frequency."""
        from gpiozero import OutputDevice
        import board
        import busio
        from adafruit_pca9685 import PCA9685
        # ^ Imported here, not at the top, so --dry-run works on a laptop.

        self.in1 = OutputDevice(IN1_PIN)
        self.in2 = OutputDevice(IN2_PIN)
        self.in3 = OutputDevice(IN3_PIN)
        self.in4 = OutputDevice(IN4_PIN)

        self.pca = PCA9685(busio.I2C(board.SCL, board.SDA))
        self.pca.frequency = PWM_FREQUENCY
        self.camera = CameraPan(self.pca)   # after the frequency is set

        # What each side is doing now: None (stopped) or (forward, duty).
        # Used to skip pin writes when nothing changed.
        self.state = {"left": None, "right": None}

    def _set_speed(self, channel, fraction):
        """Set one PWM channel's duty cycle (0..1 of the time "on")."""
        fraction = clamp(fraction, 0.0, 1.0)
        self.pca.channels[channel].duty_cycle = int(fraction * 65535)
        # ^ The PCA9685 counts "on" time in 16-bit steps: 0 .. 65535.

    def _set_side(self, side, wheel):
        """Drive one side ("left" or "right") at a wheel value (-1..1)."""
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
        """Set both wheels. left/right: -1 .. 1 (negative = backward)."""
        self._set_side("left", left)
        self._set_side("right", right)

    def stop(self):
        """Both motors off."""
        self.drive(0.0, 0.0)

    def close(self):
        """Stop, let the camera servo go limp, and release the PWM HAT."""
        self.stop()
        self.camera.release()
        self.pca.deinit()


class FakeMotors:
    """--dry-run: prints what the motors WOULD do. Proves the network + math
    without the battery on, before trusting it with real wheels."""

    def __init__(self):
        self.last = None                    # last (left, right) printed
        self.camera = CameraPan(None)       # prints the pan angle instead

    def drive(self, left, right):
        """Print the wheel values and duty cycles, only when they change."""
        now = (round(left, 2), round(right, 2))
        if now != self.last:
            lf, ld = to_duty(left)
            rf, rd = to_duty(right)
            print(f"left {left:+.2f} -> {'fwd' if lf else 'rev'} {ld:.2f}   "
                  f"right {right:+.2f} -> {'fwd' if rf else 'rev'} {rd:.2f}")
            self.last = now

    def stop(self):
        """Both motors "off"."""
        self.drive(0.0, 0.0)

    def close(self):
        """Same as stop()."""
        self.stop()


# =============================================================================
# SERVER
# =============================================================================

motors = None             # Motors or FakeMotors, set up at start
rear = None               # RearSensor, set up at start
clients = set()           # open headset connections, to send readings back
last_wheels = (0.0, 0.0)  # what the wheels were last told, for the info panel
last_message_time = 0.0   # when the last stick message arrived (time.monotonic)


async def handler(ws):
    """Serve one headset connection until it closes.

    For each stick message: limit reverse by the rear sensors, drive the
    motors, and move the camera servo. Ping messages are answered at once.
    When the connection closes for any reason, the car stops and the camera
    re-centres.

    Args:
        ws: the WebSocket connection (from the websockets library).
    """
    global last_message_time, last_wheels
    print("headset connected")
    clients.add(ws)
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("type") == "ping":
                # answer at once, so the headset can time the round trip
                await ws.send(json.dumps({"type": "pong", "t": data.get("t")}))
                continue

            wheels = message_to_wheels(msg)
            if wheels is None:
                continue
            last_message_time = time.monotonic()
            limit = rear.read()["reverse_limit"]
            last_wheels = limit_reverse(*wheels, limit)
            motors.drive(*last_wheels)
            if "pan" in data:
                motors.camera.set(data["pan"])
    finally:
        clients.discard(ws)
        # connection closed for any reason -> stop
        motors.stop()
        last_wheels = (0.0, 0.0)
        motors.camera.set(0)                                 # camera back to centre
        print("headset disconnected, motors stopped")


async def watchdog():
    """Stop the car if no stick message arrives for WATCHDOG_TIMEOUT seconds.

    Runs on its own, separate from handler(), so a stuck or dropped
    connection can't keep the car driving.
    """
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


async def rear_push():
    """Send the rear sensors (and the wheel power) to every open headset page, 10x a second."""
    while True:
        await asyncio.sleep(0.1)
        websockets.broadcast(clients, json.dumps({
            "type": "rear", **rear.read(),
            "left_pct": round(last_wheels[0] * 100),     # what the wheels are
            "right_pct": round(last_wheels[1] * 100),    # actually being told
        }))


async def status_push():
    """Send the info-panel readings (Pi health + camera angle) once a second."""
    while True:
        await asyncio.sleep(1.0)
        if not clients:
            continue
        status = await asyncio.to_thread(pi_status.read_status)
        # ^ in a thread: vcgencmd takes a few ms, and the stick messages
        #   shouldn't wait for it
        status.update({"type": "status", "pan_deg": motors.camera.angle})
        # A robot with more sensors adds more keys here, e.g. "speed_mps",
        # "altitude_m", "heading_deg", "battery_v": the headset's info panel
        # shows any of those it receives and leaves out the rest.
        websockets.broadcast(clients, json.dumps(status))


async def main():
    """Start the background tasks and the secure WebSocket server, then run forever."""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)
    # ^ wss:// (secure) is required: the headset page is https, and browsers
    #   don't let an https page open a plain ws:// connection.

    asyncio.create_task(watchdog())
    asyncio.create_task(rear_push())
    asyncio.create_task(status_push())
    async with websockets.serve(handler, "0.0.0.0", PORT, ssl=ssl_context):
        print(f"drive server listening on wss://0.0.0.0:{PORT}")
        await asyncio.Future()       # run until Ctrl+C


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    motors = FakeMotors() if dry_run else Motors()
    # Rear sensors. The car must be ON THE FLOOR with nothing behind it,
    # because the DOWN sensor measures the floor at start-up (unless --no-floor).
    rear = RearSensor(use_floor="--no-floor" not in sys.argv,
                      use_back="--no-back" not in sys.argv,
                      fake="--fake-sensor" in sys.argv)
    try:
        for line in describe_calibration(rear.calibrate()):
            print("rear: " + line)
    except RuntimeError:
        motors.close()       # release the motor pins before stopping
        rear.close()
        raise
    print("DRY RUN - no motors will move" if dry_run else
          "LIVE - motors armed. Car on a block for the first run!")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        motors.close()
        rear.close()
        print("motors stopped, bye")
