#!/usr/bin/env python3
"""
rear_sensor.py - the TWO ultrasonic sensors on the BACK of the car.

Runs on:   the Raspberry Pi, from ~/robot-car
Test:      python3 hardware/rear_sensor.py              both sensors
           python3 hardware/rear_sensor.py --no-floor   BACK sensor only (no edge detection)
           python3 hardware/rear_sensor.py --no-back    DOWN sensor only (no obstacle detection)
           python3 hardware/rear_sensor.py --fake       no hardware: made-up readings
           python3 hardware/rear_sensor.py --log        one line per reading, to copy/paste
           python3 hardware/rear_sensor.py --selftest   checks the rules, no hardware
           The test prints the live distances and what the car WOULD do
           about them. No motors, no headset.
Used by:   drive_server.py (RearSensor, limit_reverse, describe_calibration),
           so the readings and the safety rules live in ONE place.
Hardware:  BACK sensor TRIG GPIO 20 / ECHO GPIO 21, DOWN sensor TRIG GPIO 5 /
           ECHO GPIO 6 (details under WIRING below)

Two sensors, one job each (since 2026-10-29; before, one sensor tilted down
at the floor tried to do both, and on smooth floors the slanted sound
bounced away and caused false edges):

    BACK sensor  the original one, pointing STRAIGHT BACK  -> obstacles
    DOWN sensor  the new one, pointing STRAIGHT DOWN on a   -> edges
                 bracket behind the rear wheels               (stairs, table edges)

=============================================================================
WHAT EACH SENSOR DETECTS
=============================================================================
An HC-SR04 sends a click of sound and times the echo. It reports whatever is
NEAREST inside its ~30 degree cone.

BACK sensor (obstacles). Pointing straight back, it sees up to ~2 m:
    farther than SLOW_CM (20 cm)  -> CLEAR, reverse at full (capped) speed
    between SLOW_CM and STOP_CM   -> SLOW: 5% less speed for every cm closer
                                     (19 cm = 95%, 10 cm = 50%, 4 cm = 20%)
    STOP_CM (3 cm) or closer      -> STOP, reverse blocked

DOWN sensor (edges). Pointing straight down, it normally reads the floor,
about its own height above the floor (e.g. 7 cm). At start-up it measures
that ("calibrates"), with the car on the floor. Then:
    reading about the floor            -> CLEAR
    reading EDGE_JUMP_CM longer than   -> EDGE, reverse blocked
    the floor, or no echo at all          (the floor dropped away)
Pointing straight down, the sound hits the floor head-on and comes straight
back, even on a smooth table - which the tilted sensor couldn't manage.

The catch: a straight-down sensor can't see an edge COMING, only notice it
once it's over it. So the bracket must stick out behind the wheels farther
than the car rolls while stopping (~8-10 cm), and reverse stays capped at
REVERSE_MAX_SPEED.

Either sensor can slow or block REVERSE. The stricter one wins. Forward and
turning away always work.

=============================================================================
THE TWO SENSORS TAKE TURNS
=============================================================================
If both pinged at the same moment, one could hear the other's echo and
report a wrong distance. gpiozero already prevents that: every
DistanceSensor shares one lock (DistanceSensor.ECHO_LOCK), so only one pings
at a time. Each ping takes a few milliseconds and each sensor waits ~60 ms
between pings anyway, so taking turns barely slows either one down.

=============================================================================
WHY gpiozero's DistanceSensor (and not hand-written timing code)
=============================================================================
* It's already installed (python3-gpiozero, SETUP.md step 3).
* It measures in a BACKGROUND THREAD, all the time, so reading .distance
  never makes the caller wait. drive_server.py's async loop stays smooth.
* It keeps the last few readings and returns their MEDIAN, which throws away
  the odd wild reading HC-SR04s are known for.
* It gives up after 0.1 s if no echo comes back. OSOYOO's sample code uses
  `while GPIO.input(ECHO) == 0: ...` loops with NO timeout, which freeze the
  whole program if one echo is missed.
* On this OS it runs on lgpio, which stamps each echo edge with the time the
  Linux kernel saw it, so the timing doesn't depend on Python being quick.
  (gpiozero still prints a warning suggesting "pigpio" for accuracy; that
  advice is from before lgpio. We hide it below.)

The ONE thing we add on top: a "last good reading" time. If the echo fails
(e.g. a loose wire), DistanceSensor quietly keeps reporting the OLD distance.
We treat "no fresh reading for STALE_AFTER seconds" as a FAULT and block
reversing, so a broken sensor can never look like a clear path.

=============================================================================
WIRING (BCM numbering; physical pin numbers in brackets)
=============================================================================
    BACK sensor (unchanged):  TRIG -> GPIO 20 [38]    ECHO -> GPIO 21 [40]
    DOWN sensor (new):        TRIG -> GPIO 5  [29]    ECHO -> GPIO 6  [31]
    (2026-11-03: moved from GPIO 16/26 [36/37] to leave room around [38/40])
    GND -> any GND pin, e.g. [39] and [34]
None of these are used by drive_server.py (GPIO 22/23/24/27 + I2C), the
line-tracking sensor (GPIO 25/9/11/8/7) or the camera.

VOLTAGE WARNING: a standard HC-SR04 powered from 5 V (OSOYOO's instructions:
the PWM board's V+) sends a 5 V echo signal, and the Pi's pins are 3.3 V.
Either power each sensor from a Pi 3.3 V pin ([1] and [17]), or keep 5 V
and put a voltage divider on each ECHO wire: 1 kOhm from ECHO to the GPIO
pin, and 2 kOhm from the GPIO pin to GND. (An "HC-SR04P" is a 3.3 V version
that needs neither.)
"""

import statistics
import sys
import time
import warnings


# =============================================================================
# SETTINGS - everything you'd tune lives here.
# =============================================================================

BACK_TRIGGER_PIN = 20      # physical pin 38 (the original sensor)
BACK_ECHO_PIN = 21         # physical pin 40
DOWN_TRIGGER_PIN = 5       # physical pin 29 (the new sensor)
DOWN_ECHO_PIN = 6          # physical pin 31

MAX_DISTANCE_M = 2.0
# ^ Readings are capped here (metres). Anything farther counts as "far".
#   Also how a missed echo shows up: the HC-SR04 gives up after ~38 ms,
#   which reads as "very far" - for the DOWN sensor, that's an edge.

QUEUE_LEN = 3
# ^ How many readings the median is taken over. gpiozero's default is 9,
#   which with one reading every ~60 ms means about half a second of lag:
#   too slow for stopping. 3 still removes single bad readings.

# --- BACK sensor: obstacles --------------------------------------------------
STOP_CM = 3
# ^ An obstacle this close or closer = STOP. (Team choice 2026-11-03; was 6,
#   then 1 for a few minutes.)
SLOW_CM = 20
# ^ Closer than this, reversing slows down (team choice 2026-11-03; was 40).
SLOW_PER_CM = 0.05
# ^ How much slower for every cm closer than SLOW_CM: 0.05 = 5% per cm.
#   So 19 cm = 95% of the reverse speed, 10 cm = 50%, 4 cm = 20%, 3 cm = STOP.
BLIND_CM = 3
BLIND_HOLD_S = 1.0
# ^ The HC-SR04 is only rated down to 2 cm. Closer than that it can report
#   nonsense - sometimes a FAR reading, which would look like a clear path
#   while the car is touching the wall. So: if the reading was under
#   BLIND_CM and then suddenly jumps to "clear", reverse stays STOPPED for
#   BLIND_HOLD_S. If the obstacle really went away, it's believed after that.

# --- DOWN sensor: edges ------------------------------------------------------
EDGE_JUMP_CM = 7.6
# ^ EDGE = the reading suddenly gets this much LONGER than the floor
#   baseline (7.6 cm = 3 in; team choice 2026-10-27). Pointing straight
#   down, any drop deeper than 3 in counts.

# The floor baseline follows the floor (team idea 2026-10-27). The start-up
# measurement is only the starting point. While the readings look like
# floor, the baseline slowly follows them, so ramps, rug-to-tile, a slightly
# bumped mount, etc. don't cause false edges. Three guards keep that from
# hiding a real edge:
BASE_FOLLOW_S = 1.0
# ^ How quickly the baseline follows (seconds, roughly). Slow, gradual
#   changes are learned; sudden jumps (edges) are not.
BASE_BAND_CM = 1.5
# ^ Guard 1: only readings within this much of the baseline are learned
#   from. An edge reading is NEVER learned, so an edge stays blocked until
#   the floor really comes back (not just after 1 second).
BASE_MAX_DRIFT_CM = 4
# ^ Guard 2: the baseline never moves more than this from the start-up
#   floor. Without it, creeping very slowly over an edge could be "learned".
EDGE_CONFIRM_S = 0.2
# ^ Guard 3: the edge reading must last this long (seconds) before reverse
#   is blocked, so a brief glitch - a missed echo, a bump - is ignored.
#   (~3 sensor readings in a row.)

# --- Both --------------------------------------------------------------------
REVERSE_MAX_SPEED = 0.6
# ^ Reversing is ALWAYS capped at this fraction of full speed, because the
#   DOWN sensor only notices an edge once it's over it. The car has to stop
#   within the distance the bracket sticks out behind the wheels. 1.0 = no cap.

STALE_AFTER = 0.5
# ^ Seconds without a fresh reading before a sensor counts as broken.

CALIBRATE_SECONDS = 2.0
# ^ How long to measure at start-up.
MAX_FLOOR_CM = 50
# ^ If the DOWN sensor's "floor" measures farther than this at start-up, it
#   isn't hearing the floor (not pointing down, or the car isn't on the
#   floor). Edge detection would silently not work, so it refuses to start.
MIN_FLOOR_CM = 1.5
# ^ Closer than this, the HC-SR04 can't measure: the bracket is too low, or
#   something is stuck under the sensor. Also refuses to start. (Was 3;
#   lowered 2026-11-03 because our bracket puts the sensor ~2.3 cm up.)
LOW_FLOOR_WARN_CM = 4
# ^ Below this the start-up check warns: the HC-SR04 is rated from 2 cm,
#   so this close it may miss echoes, and each missed echo looks like an edge.


# =============================================================================
# THE RULES - pure functions: numbers in, decision out. No hardware, so they
# can be tested anywhere (see the self-test at the bottom: --selftest).
#
# Each returns (state, reverse_limit):
#   state          "clear" | "slow" | "stop" | "edge" | "fault"
#   reverse_limit  0.0 .. 1.0 - how much of the requested REVERSE speed is
#                  allowed. 1.0 = full, 0.0 = none. Forward is never limited.
# =============================================================================

def assess_obstacle(cm, age_s):
    """BACK sensor. cm = latest (median) distance, age_s = seconds since
    the last good echo."""
    if age_s > STALE_AFTER:
        return "fault", 0.0                  # no fresh data -> don't trust it
    if cm <= STOP_CM:
        return "stop", 0.0
    if cm < SLOW_CM:
        # 5% (SLOW_PER_CM) less for every cm closer than SLOW_CM
        return "slow", round(max(0.0, 1.0 - SLOW_PER_CM * (SLOW_CM - cm)), 2)
    return "clear", 1.0


def assess_edge(cm, floor_cm, age_s):
    """DOWN sensor. floor_cm = the floor baseline (see RearSensor.read)."""
    if age_s > STALE_AFTER or floor_cm is None:
        return "fault", 0.0
    if cm > floor_cm + EDGE_JUMP_CM:
        return "edge", 0.0                   # floor vanished -> drop-off
    return "clear", 1.0
    # A reading SHORTER than the floor (a ramp up, a thick rug, a cable under
    # the bracket) is fine here: things in the way are the BACK sensor's job.


# When both sensors want to block reverse, which one the headset names.
_WORST_FIRST = ["edge", "stop", "fault", "slow", "clear"]


def combine(back, down):
    """
    Put the two sensors' answers together. back / down are (state, limit),
    or None for a sensor that's switched off.
    Returns (state, reverse_limit, source):
      reverse_limit  the STRICTER of the two (the smaller number)
      state, source  the more urgent of the two, and which sensor it came
                     from ("back" / "down"), so the headset can say
                     "EDGE BEHIND!" vs "REAR 4.5 in" vs which sensor is broken
    """
    results = [(r[0], r[1], name)
               for name, r in (("back", back), ("down", down)) if r is not None]
    if not results:
        return "clear", 1.0, None
    state, limit, source = min(results, key=lambda r: (r[1], _WORST_FIRST.index(r[0])))
    return state, limit, source


def limit_reverse(left, right, reverse_limit):
    """
    Apply the limit to a pair of wheel values (-1..1, negative = backward,
    the same as drive_server.py's mix()). Only BACKWARD motion is scaled, so
    the driver can always drive forward, or turn away by pivoting forward.
    REVERSE_MAX_SPEED caps reversing on top of the sensors' limit.
    """
    scale = reverse_limit * REVERSE_MAX_SPEED
    if left < 0:
        left *= scale
    if right < 0:
        right *= scale
    return left, right


# =============================================================================
# HARDWARE
# =============================================================================

def _make_distance_sensor(trigger_pin, echo_pin):
    """gpiozero's DistanceSensor, plus a record of when the last good echo
    arrived. Imported here so --fake and --selftest work on a laptop."""
    from gpiozero import DistanceSensor
    from gpiozero.exc import DistanceSensorNoEcho, PWMSoftwareFallback

    warnings.filterwarnings("ignore", category=PWMSoftwareFallback)
    # ^ The "use pigpio for accuracy" warning - not needed with lgpio.
    warnings.filterwarnings("ignore", category=DistanceSensorNoEcho)
    # ^ "no echo received" - would print up to 15 times a second when the
    #   floor drops away. The stale check below reports it instead.

    if not hasattr(DistanceSensor, "ECHO_LOCK"):
        print("  ! this gpiozero is too old to make the two sensors take turns;"
              " readings may interfere. Run: sudo apt install --only-upgrade python3-gpiozero")

    class TimedDistanceSensor(DistanceSensor):
        last_good = 0.0     # time.monotonic() of the last successful echo

        def _read(self):
            value = super()._read()     # gpiozero's own measurement (takes turns)
            if value is not None:       # None = no echo this time
                self.last_good = time.monotonic()
            return value

    return TimedDistanceSensor(
        echo=echo_pin, trigger=trigger_pin,
        queue_len=QUEUE_LEN, max_distance=MAX_DISTANCE_M,
        partial=True,
        # ^ partial=True: give a value from the first reading, instead of
        #   waiting for QUEUE_LEN readings.
    )


class _FakeSensor:
    """--fake: no hardware. Made-up readings on a 12-second loop.

    Looks like a gpiozero DistanceSensor to the rest of this file: a
    .distance (metres), a .last_good time and close().
    """

    def __init__(self, pattern):
        """pattern: a function of time-in-the-loop (s) that returns metres."""
        self.pattern = pattern
        self.started = time.monotonic()
        self.last_good = self.started

    @property
    def distance(self):
        """The made-up reading for right now, in metres (always counts as a good echo)."""
        self.last_good = time.monotonic()
        return self.pattern((self.last_good - self.started) % 12)

    def close(self):
        """Nothing to release."""
        pass


def _fake_back(t):
    """Nothing behind, then a wall closing in from 30 cm to 0.5 cm, a moment
    of blind-zone nonsense (reads far: must stay STOP), then away."""
    if 4 <= t < 8:
        return 0.30 - 0.295 * (t - 4) / 4
    if 8 <= t < 8.5:
        return 1.50                               # blind zone: bogus far reading
    if 8.5 <= t < 9:
        return 0.005
    return 1.50


def _fake_down(t):
    """Floor 2.3 cm away, a 0.1 s glitch (should be ignored), then a table edge."""
    if 3.0 <= t < 3.1:
        return 0.60
    if 9.5 <= t < 11:
        return 0.80
    return 0.023


class RearSensor:
    """Both rear sensors together: calibrate() once at start-up, then read().

    Either sensor can be switched off (use_floor / use_back), so the car
    can be tested with just one plugged in.
    """

    def __init__(self, use_floor=True, use_back=True, fake=False):
        """
        use_floor  use the DOWN sensor (edge detection). The name is kept from
                   the one-sensor version, so --no-floor still means
                   "no edge detection".
        use_back   use the BACK sensor (obstacle detection).
        fake       made-up readings, no hardware.
        """
        self.use_floor = use_floor
        self.back = self.down = None
        if use_back:
            self.back = (_FakeSensor(_fake_back) if fake else
                         _make_distance_sensor(BACK_TRIGGER_PIN, BACK_ECHO_PIN))
        if use_floor:
            try:
                self.down = (_FakeSensor(_fake_down) if fake else
                             _make_distance_sensor(DOWN_TRIGGER_PIN, DOWN_ECHO_PIN))
            except Exception:
                if self.back:
                    self.back.close()   # release GPIO 20/21 before giving up
                raise
        self.floor_cm = None        # start-up floor measurement (DOWN sensor)
        self.base_cm = None         # floor baseline that follows the floor (see read)
        self._edge_since = None     # when the current edge reading started
        self._last_read = None      # time of the previous read(), for the baseline
        self._close_at = None       # last time the BACK sensor read under BLIND_CM
        self._close_cm = None       # ...and what it read
        self.clock = time.monotonic # (replaced by the self-test)

    def calibrate(self, seconds=CALIBRATE_SECONDS):
        """
        Car ON THE FLOOR, nothing within about 2 ft behind it.
        Checks both sensors answer, and measures the floor under the DOWN
        sensor. Returns a dict for describe_calibration():
          back_cm      what the BACK sensor saw (should be far)
          floor_cm     the floor under the DOWN sensor
          spread_cm    how much the floor readings varied
          no_echo_pct  % of DOWN pings that got no echo
        """
        back_samples, down_samples = [], []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(0.07)
            now = time.monotonic()
            if self.back and now - self.back.last_good < STALE_AFTER:
                back_samples.append(self.back.distance * 100)
            if self.down and now - self.down.last_good < STALE_AFTER:
                down_samples.append(self.down.distance * 100)

        info = {}
        if self.back:
            if len(back_samples) < 5:
                raise RuntimeError(
                    "BACK sensor: no echoes - check its wiring (TRIG=GPIO%d pin 38, "
                    "ECHO=GPIO%d pin 40) and its power" % (BACK_TRIGGER_PIN, BACK_ECHO_PIN))
            info["back_cm"] = statistics.median(back_samples)

        if self.down:
            if len(down_samples) < 5:
                raise RuntimeError(
                    "DOWN sensor: no echoes - check its wiring (TRIG=GPIO%d pin 29, "
                    "ECHO=GPIO%d pin 31) and its power" % (DOWN_TRIGGER_PIN, DOWN_ECHO_PIN))
            # A reading at the maximum distance means "no echo came back".
            no_echo = sum(1 for v in down_samples if v >= MAX_DISTANCE_M * 100 * 0.98)
            no_echo_pct = round(100 * no_echo / len(down_samples))
            floor = statistics.median(down_samples)
            if floor > MAX_FLOOR_CM:
                raise RuntimeError(
                    f"DOWN sensor can't hear the floor: it reads {floor:.0f} cm and "
                    f"{no_echo_pct}% of pings got no echo. Is it pointing STRAIGHT DOWN, "
                    "and is the car on the floor? (On a block, use --no-floor.)")
            if floor < MIN_FLOOR_CM:
                raise RuntimeError(
                    f"DOWN sensor reads only {floor:.1f} cm - too close to measure. "
                    "Raise the bracket, or check nothing is stuck under the sensor.")
            self.floor_cm = self.base_cm = floor
            info.update(floor_cm=floor, no_echo_pct=no_echo_pct,
                        spread_cm=max(down_samples) - min(down_samples))
        return info

    def read(self):
        """The latest readings and what they mean, as a dict that can be sent
        to the headset as JSON unchanged:
          cm, back_state           BACK sensor (None if switched off)
          down_cm, floor_cm,       DOWN sensor reading, the floor baseline,
          down_state               and its state (None if switched off)
          state, reverse_limit,    the two combined - see combine()
          source
        """
        now = self.clock()
        dt = 0.0 if self._last_read is None else min(now - self._last_read, 0.5)
        self._last_read = now
        out = {"cm": None, "back_state": None,
               "down_cm": None, "floor_cm": None, "down_state": None}

        back = None
        if self.back:
            cm = self.back.distance * 100
            back = assess_obstacle(cm, now - self.back.last_good)
            # Blind-zone guard (see BLIND_CM): very close, then suddenly "clear"
            # = probably the sensor losing it, not the obstacle leaving.
            if back[0] != "fault":
                if cm < BLIND_CM:
                    self._close_at, self._close_cm = now, cm
                elif cm < SLOW_CM:
                    self._close_at = None       # tracking it normally again
                elif self._close_at is not None:
                    if now - self._close_at < BLIND_HOLD_S:
                        back, cm = ("stop", 0.0), self._close_cm
                    else:
                        self._close_at = None   # stayed clear: believe it
            out.update(cm=round(cm, 1), back_state=back[0])

        down = None
        if self.down:
            cm = self.down.distance * 100
            age = now - self.down.last_good

            # Let the baseline follow the floor - but only floor-like readings
            # (guard 1), and never further than BASE_MAX_DRIFT_CM (guard 2).
            if self.base_cm is not None and age <= STALE_AFTER \
                    and abs(cm - self.base_cm) <= BASE_BAND_CM:
                self.base_cm += (cm - self.base_cm) * min(1.0, dt / BASE_FOLLOW_S)
                self.base_cm = max(self.floor_cm - BASE_MAX_DRIFT_CM,
                                   min(self.floor_cm + BASE_MAX_DRIFT_CM, self.base_cm))

            down = assess_edge(cm, self.base_cm, age)

            # Guard 3: edge readings only count once they've lasted EDGE_CONFIRM_S.
            if down[0] == "edge":
                if self._edge_since is None:
                    self._edge_since = now
                if now - self._edge_since < EDGE_CONFIRM_S:
                    down = ("clear", 1.0)       # not confirmed yet - probably a glitch
            else:
                self._edge_since = None

            base = None if self.base_cm is None else round(self.base_cm, 1)
            out.update(down_cm=round(cm, 1), floor_cm=base, down_state=down[0])

        state, limit, source = combine(back, down)
        out.update(state=state, reverse_limit=limit, source=source)
        return out

    def close(self):
        """Release both sensors' GPIO pins."""
        for sensor in (self.back, self.down):
            if sensor:
                sensor.close()


def describe_calibration(info):
    """What calibrate() found, as lines to print, including warnings.
    Shared by this test and drive_server.py so both say the same thing."""
    lines = []
    if "back_cm" in info:
        back = info["back_cm"]
        far = back >= MAX_DISTANCE_M * 100 * 0.98
        lines.append("BACK sensor: " + ("nothing in range behind the car" if far else
                                        f"nearest thing behind is {back:.1f} cm away"))
        if back < SLOW_CM:
            lines.append("  ! something is within %d cm behind the car. If nothing is really "
                         "there, the BACK sensor is seeing the floor or part of the car: "
                         "tilt it up a few degrees, or move it to the very back edge." % SLOW_CM)
        lines.append(f"  slows reverse from {SLOW_CM} cm, stops at {STOP_CM} cm")
    else:
        lines.append("BACK sensor: off (no obstacle detection)")
    if "floor_cm" in info:
        floor = info["floor_cm"]
        lines.append(f"DOWN sensor: floor is {floor:.1f} cm below it "
                     f"(readings varied by {info['spread_cm']:.1f} cm)")
        if floor < LOW_FLOOR_WARN_CM:
            lines.append(f"  ! {floor:.1f} cm is very close: the HC-SR04 is rated from 2 cm, so "
                         "expect some missed echoes (each looks like an edge, but a 0.2 s "
                         "check filters short ones). Raising the bracket to 4-5 cm is steadier.")
        if info["spread_cm"] > 2:
            lines.append("  ! readings vary a lot: is the sensor pointing straight down, "
                         "and is the bracket solid?")
        if info["no_echo_pct"] > 10:
            lines.append(f"  ! {info['no_echo_pct']}% of pings got no echo - each one looks "
                         "like an edge. Point the sensor straight down.")
        lines.append(f"  edge when the reading jumps {EDGE_JUMP_CM:.1f} cm past the floor "
                     f"(held {EDGE_CONFIRM_S} s); the floor baseline follows gradual "
                     f"changes, up to +/-{BASE_MAX_DRIFT_CM} cm")
    else:
        lines.append("DOWN sensor: off (no edge detection)")
    return lines


# =============================================================================
# TEST MODE: python3 hardware/rear_sensor.py
# =============================================================================

def _bar(cm, width=20):
    """A text bar for the live test line: longer = farther away (full at 2 x SLOW_CM)."""
    filled = int(min(cm, SLOW_CM * 2) / (SLOW_CM * 2) * width)
    return "#" * filled + "-" * (width - filled)


def _selftest():
    """Checks the rules with made-up numbers. No hardware needed."""
    # BACK sensor: obstacles
    assert assess_obstacle(100, 0) == ("clear", 1.0)
    assert assess_obstacle(20, 0) == ("clear", 1.0)
    assert assess_obstacle(19, 0) == ("slow", 0.95)    # 5% less per cm under 20
    assert assess_obstacle(10, 0) == ("slow", 0.5)
    assert assess_obstacle(4, 0) == ("slow", 0.2)
    assert assess_obstacle(3, 0) == ("stop", 0.0)      # stop at 3 cm
    assert assess_obstacle(2, 0) == ("stop", 0.0)
    assert assess_obstacle(0.5, 0) == ("stop", 0.0)
    assert assess_obstacle(100, 1.0) == ("fault", 0.0)

    # Blind-zone guard: 0.5 cm, then a bogus far reading -> still STOP for 1 s
    class B:
        def __init__(self):
            self.distance, self.last_good = 0.005, 0.0
        def close(self):
            pass
    r = RearSensor.__new__(RearSensor)
    r.back, r.down, r._last_read, r._close_at, r._close_cm = B(), None, None, None, None
    r.t = 0.0
    r.clock = lambda: r.t
    def back_at(t, cm):
        r.t = r.back.last_good = t
        r.back.distance = cm / 100
        return r.read()
    assert back_at(0.1, 0.5)["state"] == "stop"
    assert back_at(0.2, 150)["state"] == "stop"        # bogus jump: held
    assert back_at(0.9, 150)["state"] == "stop"
    assert back_at(1.3, 150)["state"] == "clear"       # stayed clear > 1 s: believed
    assert back_at(1.4, 2)["state"] == "stop"
    assert back_at(1.5, 10)["state"] == "slow"         # moving away normally...
    assert back_at(1.6, 50)["state"] == "clear"        # ...is believed at once

    # DOWN sensor: edges, floor 7 cm away
    assert assess_edge(7, 7, 0) == ("clear", 1.0)      # floor
    assert assess_edge(14, 7, 0) == ("clear", 1.0)     # less than the edge jump
    assert assess_edge(15, 7, 0) == ("edge", 0.0)      # floor dropped away
    assert assess_edge(200, 7, 0) == ("edge", 0.0)     # no echo / max range
    assert assess_edge(3, 7, 0) == ("clear", 1.0)      # something under it: not its job
    assert assess_edge(7, 7, 1.0) == ("fault", 0.0)    # sensor stopped answering
    assert assess_edge(7, None, 0) == ("fault", 0.0)   # never calibrated

    # Combining: the stricter limit wins, the more urgent state is shown
    clear = ("clear", 1.0)
    assert combine(clear, clear) == ("clear", 1.0, "back")
    assert combine(("slow", 0.5), clear) == ("slow", 0.5, "back")
    assert combine(("slow", 0.5), ("edge", 0.0)) == ("edge", 0.0, "down")
    assert combine(("stop", 0.0), ("edge", 0.0)) == ("edge", 0.0, "down")
    assert combine(("stop", 0.0), ("fault", 0.0)) == ("stop", 0.0, "back")
    assert combine(clear, ("fault", 0.0)) == ("fault", 0.0, "down")
    assert combine(("fault", 0.0), clear) == ("fault", 0.0, "back")
    assert combine(None, ("edge", 0.0)) == ("edge", 0.0, "down")
    assert combine(("slow", 0.3), None) == ("slow", 0.3, "back")
    assert combine(None, None) == ("clear", 1.0, None)

    # The floor baseline + edge debounce, with a fake clock (no waiting).
    class Stub:
        def __init__(self, cm):
            self.distance, self.last_good = cm / 100, 0.0
        def close(self):
            pass

    def make(back_cm=None):
        r = RearSensor.__new__(RearSensor)
        r.use_floor = True
        r.back = Stub(back_cm) if back_cm is not None else None
        r.down = Stub(7.0)
        r.floor_cm = r.base_cm = 7.0            # floor 7 cm (sensor 7 cm up)
        r._edge_since = r._last_read = r._close_at = r._close_cm = None
        r.t = 0.0
        r.clock = lambda: r.t
        return r

    def run(r, readings_cm, seconds, step=0.05, key="state"):
        """Feed DOWN readings (a number, or a function of time) for `seconds`."""
        out = []
        t_end = r.t + seconds
        while r.t < t_end:
            r.t += step
            v = readings_cm(r.t) if callable(readings_cm) else readings_cm
            r.down.distance, r.down.last_good = v / 100, r.t
            if r.back:
                r.back.last_good = r.t
            out.append(r.read()[key])
        return out

    r = make()                                   # a 0.1 s glitch is ignored
    assert "edge" not in run(r, 60, 0.1) and run(r, 7, 0.5)[-1] == "clear"
    r = make()                                   # a real edge blocks...
    assert run(r, 60, 0.3)[-1] == "edge"
    assert set(run(r, 60, 5.0)) == {"edge"}      # ...and STAYS blocked (guard 1)
    assert run(r, 7, 0.2)[-1] == "clear"         # floor back: clear again
    r = make()                                   # a gentle ramp: 7 -> 10 cm over 10 s
    start = r.t
    assert "edge" not in run(r, lambda t: 7 + 0.3 * (t - start), 10.0)
    assert 9 < r.base_cm <= 11, r.base_cm        # baseline followed it
    r = make()                                   # creeping over an edge very slowly
    start = r.t
    st = run(r, lambda t: 7 + 1.0 * (t - start), 20.0)
    assert "edge" in st, "slow creep must still end in EDGE (guard 2)"
    assert r.base_cm <= 11.0 + 1e-9

    # Both sensors at once
    r = make(back_cm=10)                         # wall 10 cm behind, floor fine
    out = r.read()
    assert (out["state"], out["reverse_limit"], out["source"]) == ("slow", 0.5, "back"), out
    assert out["back_state"] == "slow" and out["down_state"] == "clear"
    assert run(r, 60, 0.3, key="source")[-1] == "down"   # now an edge too: edge wins
    assert r.read()["reverse_limit"] == 0.0
    r = make(back_cm=150)                        # BACK sensor stops answering
    r.t = 1.0
    r.down.last_good = 1.0
    assert (r.read()["state"], r.read()["source"]) == ("fault", "back")

    # start-up refuses a floor it can't hear (every ping at max distance)...
    class Deaf:
        distance, last_good = MAX_DISTANCE_M, time.monotonic()
    r = RearSensor.__new__(RearSensor)
    r.back, r.down = None, Deaf()
    try:
        r.calibrate(seconds=0.4)
        raise AssertionError("should have refused a floor at max distance")
    except RuntimeError as e:
        assert "can't hear the floor" in str(e)
    # ...and says which sensor isn't answering
    class Silent:
        distance, last_good = 0.5, 0.0
    r.back, r.down = Silent(), None
    try:
        r.calibrate(seconds=0.4)
        raise AssertionError("should have refused a silent BACK sensor")
    except RuntimeError as e:
        assert "BACK sensor: no echoes" in str(e)

    # only backward wheels are limited, and reverse is capped
    cap = REVERSE_MAX_SPEED
    assert limit_reverse(-1.0, -1.0, 0.0) == (0.0, 0.0)
    assert limit_reverse(1.0, 1.0, 0.0) == (1.0, 1.0)
    assert limit_reverse(-1.0, 1.0, 1.0) == (-cap, 1.0)
    print("selftest passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit()

    use_floor = "--no-floor" not in sys.argv
    use_back = "--no-back" not in sys.argv
    if not (use_floor or use_back):
        sys.exit("--no-floor and --no-back together leaves no sensors to test")
    rear = RearSensor(use_floor=use_floor, use_back=use_back, fake="--fake" in sys.argv)
    try:
        print("Checking the sensors: car on the floor, nothing behind it ...")
        for line in describe_calibration(rear.calibrate()):
            print(line)
        print("Ctrl+C to stop.\n")
        log = "--log" in sys.argv
        started = time.monotonic()
        if log:
            print("  time    back    down   floor   state         reverse")

        while True:
            r = rear.read()
            if log:          # one line per reading, so the whole run can be copied
                f = lambda v: f"{v:6.1f}" if v is not None else "   -  "
                who = f"({r['source']})" if r["state"] != "clear" else ""
                print(f"{time.monotonic() - started:6.1f}s {f(r['cm'])}  {f(r['down_cm'])}  "
                      f"{f(r['floor_cm'])}   {r['state'].upper():5} {who:7} "
                      f"{r['reverse_limit']:.0%}", flush=True)
                time.sleep(0.1)
                continue
            if r["reverse_limit"] == 1:
                limit = "reverse OK"
            elif r["reverse_limit"] == 0:
                limit = "reverse BLOCKED"
            else:
                limit = f"reverse limited to {r['reverse_limit']:.0%}"
            parts = []
            if r["back_state"]:
                parts.append(f"back {r['cm']:6.1f} cm [{_bar(r['cm'])}] {r['back_state'].upper():5}")
            if r["down_state"]:
                parts.append(f"down {r['down_cm']:5.1f} cm (floor {r['floor_cm']:4.1f}) "
                             f"{r['down_state'].upper():5}")
            print("\r" + " | ".join(parts) + f" | {limit:26}", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        rear.close()
        print("sensors released, bye")
