"""Unit tests for pi-server/mapping.py — the pure-function control mapping
layer. No hardware or network needed to run these.

Run from pi-server/: python3 -m pytest ../tests/pi_server_tests/
(or add pi-server/ to PYTHONPATH)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "pi-server"))

from mapping import apply_deadzone, apply_curve, clamp, condition_axis, tank_mix, single_stick_mix, HeadYawSmoother


def test_deadzone_zeroes_small_values():
    assert apply_deadzone(0.02) == 0.0
    assert apply_deadzone(-0.02) == 0.0


def test_deadzone_rescales_beyond_threshold():
    # Just past the deadzone edge should be small but nonzero
    result = apply_deadzone(0.5)
    assert 0.0 < result < 0.5


def test_curve_preserves_sign():
    assert apply_curve(0.5) > 0
    assert apply_curve(-0.5) < 0


def test_curve_is_gentler_near_center():
    # With exponent > 1, half-deflection should map to less than half output
    assert apply_curve(0.5) < 0.5


def test_curve_reaches_full_power_at_edge():
    assert apply_curve(1.0) == 1.0
    assert apply_curve(-1.0) == -1.0


def test_clamp_bounds():
    assert clamp(2.0) == 1.0
    assert clamp(-2.0) == -1.0
    assert clamp(0.3) == 0.3


def test_condition_axis_combines_deadzone_curve_and_clamp():
    assert condition_axis(0.02) == 0.0          # inside deadzone -> zero
    assert condition_axis(1.5) == 1.0            # out of range -> clamped
    assert condition_axis(-1.5) == -1.0
    mid = condition_axis(0.5)
    assert 0.0 < mid < 0.5                       # deadzone-rescaled, then curved gentler


def test_single_stick_and_tank_mix_assume_already_conditioned_input():
    # mixing functions no longer apply their own deadzone/curve — a raw
    # small value should NOT be zeroed by single_stick_mix/tank_mix alone,
    # since server.py is responsible for calling condition_axis() first.
    wheels = single_stick_mix(forward=0.02, turn=0.0)
    assert wheels.left != 0.0


def test_single_stick_straight_forward_drives_both_wheels_equal():
    wheels = single_stick_mix(forward=0.8, turn=0.0)
    assert abs(wheels.left - wheels.right) < 1e-6
    assert wheels.left > 0


def test_single_stick_pure_turn_drives_wheels_opposite():
    wheels = single_stick_mix(forward=0.0, turn=0.8)
    assert wheels.left > 0
    assert wheels.right < 0


def test_tank_mix_independent_sides():
    wheels = tank_mix(left_stick=0.5, right_stick=-0.5)
    assert wheels.left > 0
    assert wheels.right < 0


def test_head_yaw_smoother_converges_toward_target():
    smoother = HeadYawSmoother(initial_deg=0.0)
    last = 0.0
    for _ in range(50):
        last = smoother.update(45.0)
    assert abs(last - 45.0) < 1.0  # should have converged close to target


def test_head_yaw_smoother_rate_limits_large_jumps():
    smoother = HeadYawSmoother(initial_deg=0.0)
    first_update = smoother.update(90.0)
    # Should not jump straight to 90 in one update
    assert abs(first_update) < 90.0
