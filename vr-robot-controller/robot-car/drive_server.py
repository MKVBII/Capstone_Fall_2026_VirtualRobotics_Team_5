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

MESSAGES FROM THE PAGES (any page on the website can connect):
    {"type": "hello", "role": "driver" | "viewer"}
                              sent first. A "viewer" (start screen, spectator
                              view) only watches: its sticks are ignored and
                              its leaving doesn't stop the car. A page that
                              never says hello counts as a driver.
    {"lx", "ly", "rx", "ry", "pan"}   the sticks (drivers only), 25x a second
    {"type": "ping", "t"}     answered with {"type": "pong", "t"}, so the
                              page can show the control-link delay
    {"type": "log", "on": true | false}   start / stop the session log

MESSAGES BACK TO THE PAGES (on the same WebSocket):
    {"type": "robot", ...}    once, on connecting: the robot's name, its
                              controls and its sensor list (see robot_info)
    {"type": "readings", ...} rear sensors + wheel power, 10x a second
    {"type": "status", ...}   Pi health, camera angle, session log, once a second
    {"type": "pong", "t"}     reply to a ping

SESSION LOG: while it's on, 10 rows a second go into logs/session-*.csv
(time, sticks, wheel power, every sensor reading and state, Pi health).
camera_server.py lists and downloads them from the start screen.
"""

import asyncio
import csv
import json
import os
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
VIEWER_PORT = 8766
# ^ A second, VIEW-ONLY door without encryption (ws://PI_IP:8766), for laptop
#   pages opened over plain http (e.g. http://PI_IP:8000/spectator). Those
#   pages can't use wss:// until the browser has accepted the Pi's self-made
#   certificate, so their readings would never show. Nothing sent here can
#   move the car: every connection on this port is treated as a viewer.
#   Must match VIEWER_PORT in camera_server.py.
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

# --- What the website shows about this robot ----------------------------------
ROBOT_NAME = "OSOYOO Pi Car"
CONTROLS = [
    {"input": "left_stick", "label": "Forward / back"},
    {"input": "right_stick", "label": "Turn"},
]
# ^ The robot's own controls, for the Begin screen's controller drawing and
#   the in-headset help card. The headset page adds its own (grip, trigger,
#   Meta button). Inputs: left_stick, right_stick, a, b, x, y.
DEFAULT_SHORTCUTS = {"x": "headlook", "a": "dashboard"}
# ^ Quest buttons this robot leaves free, given to headset shortcuts by
#   default (team decision 2026-11-04: X = head-look, A = dashboard, for the
#   car only). Choices: headlook, dashboard, recenter, help, settings. A
#   robot that needs a button for itself leaves it out of this list.

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
# ^ Where session logs are saved (robot-car/logs/). .gitignore keeps them out
#   of GitHub; download them from the start screen.


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
clients = set()           # open page connections (drivers and viewers), to send readings to
last_wheels = (0.0, 0.0)  # what the wheels were last told, for the info panel
last_sticks = {}          # the last stick message from a driver, for the session log
last_status = {}          # the last status message, for the session log
last_message_time = 0.0   # when the last stick message arrived (time.monotonic)
NO_DRIVER_UI = {"type": "ui", "driver": False}
last_ui = NO_DRIVER_UI    # what the headset is showing, relayed to the spectator view

# The "ui" keys the headset may send, and the type each must be. Anything
# else is dropped, so a page can't stuff other data into the relay.
UI_KEYS = {"in_mr": bool, "head_look": bool, "info_mode": int, "settings_open": bool,
           "help_open": bool, "settings_tab": str, "settings_page": int, "card_page": int,
           "video_fps": (int, float), "video_live": bool, "link_ms": (int, float, type(None)),
           "pan": (int, float), "pressed": list, "sticks": dict}


def clean_ui(data):
    """Keep only the known "ui" keys, with the right types (see UI_KEYS).

    Args:
        data: the message from the headset (a dict).
    Returns:
        dict: {"type": "ui", "driver": True, ...the allowed keys}
    """
    out = {"type": "ui", "driver": True}
    for key, kind in UI_KEYS.items():
        value = data.get(key)
        if isinstance(value, kind) and not (kind is int and isinstance(value, bool)):
            out[key] = value
    out["pressed"] = [p for p in out.get("pressed", []) if isinstance(p, str)][:16]
    if len(json.dumps(out)) > 2000:          # far more than a real message needs
        return {"type": "ui", "driver": True}
    return out


class SessionLog:
    """Records the drive to a CSV file while it's switched on.

    One row per readings message (10 a second): everything needed to graph
    a run or work out afterwards why the car slowed or stopped.
    """

    FIELDS = ["time_s", "lx", "ly", "rx", "ry", "pan", "left_pct", "right_pct",
              "state", "reverse_limit", "source", "rear_cm", "rear_state",
              "floor_reading_cm", "floor_baseline_cm", "floor_state",
              "cpu_temp_c", "cpu_load_pct", "wifi_dbm", "power_ok"]

    def __init__(self):
        self.file = None          # the open CSV file, or None when off
        self.writer = None
        self.name = None          # file name, e.g. session-20261105-131500.csv
        self.started = 0.0        # time.monotonic() when it was switched on

    def start(self):
        """Open a new log file (does nothing if one is already open)."""
        if self.file:
            return
        os.makedirs(LOG_DIR, exist_ok=True)
        self.name = time.strftime("session-%Y%m%d-%H%M%S.csv")
        self.file = open(os.path.join(LOG_DIR, self.name), "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(self.FIELDS)
        self.started = time.monotonic()
        print(f"session log on: logs/{self.name}")

    def stop(self):
        """Close the log file (does nothing if none is open)."""
        if not self.file:
            return
        self.file.close()
        print(f"session log off: logs/{self.name}")
        self.file = self.writer = self.name = None

    def write(self, readings, sticks, wheels, status):
        """Add one row, if the log is on.

        Args:
            readings: rear.read(); sticks: the last stick message;
            wheels: (left, right) actually sent to the motors;
            status: the last status message.
        """
        if not self.writer:
            return
        self.writer.writerow([
            round(time.monotonic() - self.started, 2),
            sticks.get("lx"), sticks.get("ly"), sticks.get("rx"), sticks.get("ry"),
            sticks.get("pan"), round(wheels[0] * 100), round(wheels[1] * 100),
            readings["state"], readings["reverse_limit"], readings["source"],
            readings["cm"], readings["back_state"],
            readings["down_cm"], readings["floor_cm"], readings["down_state"],
            status.get("cpu_temp_c"), status.get("cpu_load_pct"),
            status.get("wifi_dbm"), status.get("power_ok"),
        ])


session_log = SessionLog()


def robot_info():
    """The "robot" message: what the website needs to know about this robot.

    Sent to every page when it connects. The Begin screen draws the controls
    from it; the dashboard, alerts and checklist are built from "sensors".
    """
    return {"type": "robot", "name": ROBOT_NAME, "controls": CONTROLS,
            "shortcuts": DEFAULT_SHORTCUTS, "sensors": rear.describe()}


async def handler(ws, view_only=False):
    """Serve one page connection until it closes.

    Drivers: for each stick message, limit reverse by the rear sensors,
    drive the motors and move the camera servo; when a driver's connection
    closes for any reason, the car stops and the camera re-centres.
    Viewers only receive readings. Pings and log switches work for both.
    A driver also sends "ui" messages (what the headset is showing); they're
    passed on to every page, so the spectator view can mirror the headset.

    Args:
        ws: the WebSocket connection (from the websockets library).
        view_only: True on VIEWER_PORT: always a viewer, whatever it says.
    """
    global last_message_time, last_wheels, last_sticks, last_ui
    role = "viewer" if view_only else "driver"   # until the page says otherwise (see "hello")
    clients.add(ws)
    print("page connected")
    try:
        await ws.send(json.dumps(robot_info()))
        await ws.send(json.dumps(last_ui))
        async for msg in ws:
            try:
                data = json.loads(msg)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            if kind == "hello":
                role = "viewer" if view_only or data.get("role") == "viewer" else "driver"
                print(f"  ...as a {role}")
                continue
            if kind == "ping":
                # answer at once, so the page can time the round trip
                await ws.send(json.dumps({"type": "pong", "t": data.get("t")}))
                continue
            if kind == "log":
                session_log.start() if data.get("on") else session_log.stop()
                continue
            if role != "driver":
                continue                                     # viewers can't drive
            if kind == "ui":
                last_ui = clean_ui(data)                     # mirror it to the spectator view
                websockets.broadcast(clients, json.dumps(last_ui))
                continue

            wheels = message_to_wheels(msg)
            if wheels is None:
                continue
            last_message_time = time.monotonic()
            last_sticks = data
            limit = rear.read()["reverse_limit"]
            last_wheels = limit_reverse(*wheels, limit)
            motors.drive(*last_wheels)
            if "pan" in data:
                motors.camera.set(data["pan"])
    finally:
        clients.discard(ws)
        if role == "driver":
            # a driver's connection closed for any reason -> stop
            motors.stop()
            last_wheels = (0.0, 0.0)
            motors.camera.set(0)                             # camera back to centre
            last_ui = NO_DRIVER_UI
            websockets.broadcast(clients, json.dumps(last_ui))
            print("driver disconnected, motors stopped")
        else:
            print("viewer disconnected")


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


async def readings_push():
    """10x a second: send the sensor readings (and wheel power) to every page,
    and add a row to the session log if it's on."""
    while True:
        await asyncio.sleep(0.1)
        readings = rear.read()
        session_log.write(readings, last_sticks, last_wheels, last_status)
        websockets.broadcast(clients, json.dumps({
            "type": "readings", **readings,
            "left_pct": round(last_wheels[0] * 100),     # what the wheels are
            "right_pct": round(last_wheels[1] * 100),    # actually being told
        }))


async def status_push():
    """Once a second: send the info-panel readings (Pi health, camera angle,
    session log) to every page."""
    global last_status
    while True:
        await asyncio.sleep(1.0)
        if not clients and not session_log.file:
            continue
        status = await asyncio.to_thread(pi_status.read_status)
        # ^ in a thread: vcgencmd takes a few ms, and the stick messages
        #   shouldn't wait for it
        status.update({"type": "status", "pan_deg": motors.camera.angle,
                       "logging": session_log.name})
        # A robot with more sensors adds more keys here, e.g. "speed_mps",
        # "altitude_m", "heading_deg", "battery_v": the headset's info panel
        # shows any of those it receives and leaves out the rest.
        last_status = status
        websockets.broadcast(clients, json.dumps(status))


async def main():
    """Start the background tasks and the secure WebSocket server, then run forever."""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)
    # ^ wss:// (secure) is required: the headset page is https, and browsers
    #   don't let an https page open a plain ws:// connection.

    asyncio.create_task(watchdog())
    asyncio.create_task(readings_push())
    asyncio.create_task(status_push())
    async def view_only_handler(ws):
        await handler(ws, view_only=True)

    async with websockets.serve(handler, "0.0.0.0", PORT, ssl=ssl_context), \
               websockets.serve(view_only_handler, "0.0.0.0", VIEWER_PORT):
        print(f"drive server listening on wss://0.0.0.0:{PORT}")
        print(f"view-only readings for http pages on ws://0.0.0.0:{VIEWER_PORT}")
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
        session_log.stop()
        print("motors stopped, bye")
