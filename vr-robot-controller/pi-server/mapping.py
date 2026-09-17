"""Pure-function control mapping: raw stick/head values -> conditioned
axes -> (optionally) motor commands for wheeled robots.

This is "the part that's genuinely yours" (the engineering-judgment layer):
deadzone, response curve, tank/single-stick mixing, and smoothing/clamping
for the head-to-servo mapping. Deliberately kept as plain functions with
no I/O and no hardware dependency, so it can be unit tested (see
tests/pi_server_tests) and tuned by feel without touching networking or
GPIO code.

Two layers, used at two different points:
  1. condition_axis() — deadzone + curve + clamp. Applied ONCE, centrally,
     by server.py to each of the 4 incoming control axes before any
     driver sees them. Every robot benefits from the same tuning.
  2. tank_mix() / single_stick_mix() — robot-specific mixing math that
     drivers call themselves, on already-conditioned inputs, to turn
     generic axes into (for example) two wheel speeds. A flying robot's
     driver typically skips this layer entirely and passes conditioned
     axes close to directly into its flight-control SDK.

This module has no OSOYOO-specific or robot-specific code in it — any
driver can reuse it as-is, or a new driver can add its own pure-function
helpers here following the same pattern.
"""
from dataclasses import dataclass

DEADZONE = 0.08          # ignore stick movement smaller than this
CURVE_EXPONENT = 2.0     # >1 = gentler near center, full power still reachable at the edge
HEAD_SMOOTHING_ALPHA = 0.2   # low-pass filter factor for head yaw (0=no update, 1=no smoothing)
MAX_HEAD_RATE_DEG_PER_UPDATE = 8.0  # clamp so a fast head turn doesn't slam the servo


def apply_deadzone(value: float, deadzone: float = DEADZONE) -> float:
    """Rescale so |value| < deadzone -> 0, and the deadzone edge -> full range."""
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - deadzone) / (1.0 - deadzone)


def apply_curve(value: float, exponent: float = CURVE_EXPONENT) -> float:
    """Non-linear response so small stick movements near center are gentler,
    while full deflection still reaches full power. Sign-preserving."""
    sign = 1.0 if value >= 0 else -1.0
    return sign * (abs(value) ** exponent)


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def condition_axis(value: float) -> float:
    """Deadzone + curve + clamp, in one call. server.py applies this to
    all 4 incoming control axes BEFORE handing them to a driver's
    set_axes() — signal conditioning is universal across every robot, so
    it happens once, centrally, rather than every driver needing to
    remember to do it. Drivers (see tank_mix/single_stick_mix below, and
    drivers/_template_driver.py) can assume their inputs are already
    conditioned and just handle robot-specific mixing/passthrough.
    """
    return clamp(apply_curve(apply_deadzone(value)))


@dataclass
class WheelSpeeds:
    left: float   # -1.0..1.0
    right: float  # -1.0..1.0


def tank_mix(left_stick: float, right_stick: float) -> WheelSpeeds:
    """Two independent, ALREADY-CONDITIONED axes -> two wheel speeds.
    This is "tank drive": left stick controls the left wheel, right
    stick controls the right wheel, straight forward needs both sticks
    pushed together.

    If you'd rather drive with a single stick (forward/back + turn), see
    single_stick_mix() below instead.
    """
    return WheelSpeeds(left=clamp(left_stick), right=clamp(right_stick))


def single_stick_mix(forward: float, turn: float) -> WheelSpeeds:
    """Alternative to tank_mix: one ALREADY-CONDITIONED forward/back axis
    + one turn axis -> differential wheel speeds. Simpler for most people
    to drive with. This is what osoyoo_car_driver.py uses.
    """
    left = clamp(forward + turn)
    right = clamp(forward - turn)
    return WheelSpeeds(left=left, right=right)


class HeadYawSmoother:
    """Smooths + clamps raw head yaw (degrees) into a servo-safe angle.
    Raw WebXR head pose data is jittery frame to frame; without smoothing
    and rate-limiting, the camera servo will twitch and can be commanded
    to slew faster than the hardware likes.
    """

    def __init__(self, initial_deg: float = 0.0):
        self._smoothed_deg = initial_deg

    def update(self, raw_deg: float) -> float:
        target = self._smoothed_deg + HEAD_SMOOTHING_ALPHA * (raw_deg - self._smoothed_deg)
        delta = clamp(
            target - self._smoothed_deg,
            -MAX_HEAD_RATE_DEG_PER_UPDATE,
            MAX_HEAD_RATE_DEG_PER_UPDATE,
        )
        self._smoothed_deg += delta
        return self._smoothed_deg
