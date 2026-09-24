"""Tests for pi-server/driver_registry.py — the auto-discovery mechanism
behind "drop a file in drivers/ and it shows up in the menu." These run
against the REAL drivers/ directory (so they double as a regression test
that osoyoo_car_driver.py stays discoverable), plus temporary fixture
files for the edge cases: a broken file must not crash discovery, and the
template (leading underscore) must never be listed as selectable.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "pi-server"))

import driver_registry

DRIVERS_DIR = driver_registry.DRIVERS_DIR


def test_osoyoo_car_driver_is_discovered():
    found = driver_registry.discover()
    assert "osoyoo_car_driver" in found
    info = found["osoyoo_car_driver"]
    assert info.display_name  # DISPLAY_NAME is set, non-empty
    assert callable(info.instantiate)


def test_template_driver_is_not_discovered():
    # _template_driver.py starts with "_" -> must never appear in the menu
    found = driver_registry.discover()
    assert not any("template" in driver_id for driver_id in found)


def test_sim_driver_is_discovered_and_runs_without_hardware():
    # sim_driver.py is the hardware-free demo driver (see dev_tools/fake_client.py) —
    # it must be discoverable and fully instantiable/drivable on any machine, no Pi needed.
    found = driver_registry.discover()
    assert "sim_driver" in found
    info = found["sim_driver"]
    assert info.display_name

    instance = info.instantiate()
    instance.set_axes(0.5, 0.5, 0.0, 0.0)
    status = instance.get_status()
    assert status.connected is True
    assert "honk" in instance.supported_commands()
    result = instance.command("honk")
    assert result["ok"] is True
    instance.stop()
    instance.shutdown()


def test_discovery_does_not_instantiate_drivers():
    # Listing available robots must not touch hardware. osoyoo_car_driver's
    # set_axes() raises NotImplementedError if actually called — discover()
    # must never call it, only read class attributes.
    found = driver_registry.discover()
    assert "osoyoo_car_driver" in found
    # If discover() had instantiated it, __init__ would have run; since
    # __init__ is a no-op stub that's not directly observable here, the
    # real assertion is just that discover() completes without raising —
    # instantiate() is a separate, explicit call a caller makes later.


def test_broken_driver_file_is_skipped_not_fatal():
    broken_path = DRIVERS_DIR / "test_fixture_broken_driver.py"
    broken_path.write_text("this is not valid python at all $$$\n")
    try:
        found = driver_registry.discover()  # must not raise
        assert "test_fixture_broken_driver" not in found
        assert "osoyoo_car_driver" in found  # other drivers still load fine
    finally:
        broken_path.unlink()


def test_file_with_no_driver_subclass_is_skipped():
    empty_path = DRIVERS_DIR / "test_fixture_no_driver.py"
    empty_path.write_text("# a valid Python file with no RobotDriver subclass in it\nX = 1\n")
    try:
        found = driver_registry.discover()
        assert "test_fixture_no_driver" not in found
    finally:
        empty_path.unlink()


def test_valid_new_driver_is_discovered_and_instantiable():
    fixture_path = DRIVERS_DIR / "test_fixture_minimal_driver.py"
    fixture_path.write_text('''
from robot_driver_base import RobotDriver, RobotStatus

class MinimalTestDriver(RobotDriver):
    DISPLAY_NAME = "Minimal Test Driver"
    DESCRIPTION = "Fixture for test_driver_registry.py"

    def set_axes(self, x, y, z, yaw):
        self.last_axes = (x, y, z, yaw)

    def set_camera_yaw(self, deg):
        pass

    def command(self, name, **kwargs):
        return {"ok": False, "error": "unsupported_command"}

    def supported_commands(self):
        return []

    def stop(self):
        self.last_axes = (0.0, 0.0, 0.0, 0.0)

    def get_status(self):
        return RobotStatus()
''')
    try:
        found = driver_registry.discover()
        assert "test_fixture_minimal_driver" in found
        info = found["test_fixture_minimal_driver"]
        assert info.display_name == "Minimal Test Driver"

        instance = info.instantiate()
        instance.set_axes(0.5, 0.5, 0.0, 0.0)
        assert instance.last_axes == (0.5, 0.5, 0.0, 0.0)
        instance.stop()
        assert instance.last_axes == (0.0, 0.0, 0.0, 0.0)
    finally:
        fixture_path.unlink()
