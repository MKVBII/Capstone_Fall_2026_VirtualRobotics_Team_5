"""Auto-discovers RobotDriver subclasses dropped into pi-server/drivers/.

This is the "upload a file and it runs" mechanism: drop a .py file that
defines a class subclassing RobotDriver into drivers/, restart the
server (or call refresh() — see server.py's `reloadDrivers` message for
doing it without a restart), and it shows up in the robot-select menu.
No manual registration step, no editing a list somewhere else.

Safety property that matters a lot for a live demo: a broken or
half-finished driver file must never take the whole server down. Every
file is imported in its own try/except; a file that fails to import (or
doesn't define a valid driver) is logged and skipped, not fatal.

Naming convention:
  * Files starting with "_" (e.g. _template_driver.py) are skipped —
    that's the convention for "not a real driver," used by the
    fill-in-the-blanks template.
  * Any class in a discovered file that subclasses RobotDriver is picked
    up — no required class name, no decorator, no registration call.
  * A file may define more than one driver class; all are registered.
  * The driver's id (used in selectRobot messages and CLI flags) is
    derived from the filename, e.g. drivers/osoyoo_car_driver.py ->
    "osoyoo_car_driver". If a file defines multiple classes, later ones
    get a numeric suffix.
"""
import importlib
import importlib.util
import inspect
import logging
from pathlib import Path

from robot_driver_base import RobotDriver

log = logging.getLogger("driver_registry")

DRIVERS_DIR = Path(__file__).parent / "drivers"


class DriverInfo:
    """Metadata about one discovered driver, without instantiating it."""

    def __init__(self, driver_id: str, driver_class: type):
        self.id = driver_id
        self.driver_class = driver_class
        self.display_name = getattr(driver_class, "DISPLAY_NAME", driver_id)
        self.description = getattr(driver_class, "DESCRIPTION", "")

    def instantiate(self) -> RobotDriver:
        """Only called once a driver is actually selected — this is the
        point hardware/sockets get touched, not at discovery time."""
        return self.driver_class()

    def to_dict(self) -> dict:
        return {"id": self.id, "displayName": self.display_name, "description": self.description}


def discover() -> dict:
    """Scan drivers/ and return {driver_id: DriverInfo}. Safe to call
    repeatedly (e.g. to pick up a newly-uploaded file without a full
    server restart) — each call re-scans from scratch."""
    found = {}

    if not DRIVERS_DIR.is_dir():
        log.warning("drivers/ directory not found at %s", DRIVERS_DIR)
        return found

    for path in sorted(DRIVERS_DIR.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue

        module_name = f"drivers.{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            log.error("Skipping drivers/%s — failed to import: %s", path.name, e)
            continue

        try:
            classes = [
                obj for _, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, RobotDriver) and obj is not RobotDriver
                and obj.__module__ == module_name
            ]
        except Exception as e:
            log.error("Skipping drivers/%s — error inspecting module: %s", path.name, e)
            continue

        if not classes:
            log.warning(
                "drivers/%s imported OK but defines no RobotDriver subclass — skipping",
                path.name,
            )
            continue

        base_id = path.stem
        for i, cls in enumerate(classes):
            driver_id = base_id if i == 0 else f"{base_id}_{i + 1}"
            found[driver_id] = DriverInfo(driver_id, cls)
            log.info("Discovered driver %r (%s) from drivers/%s", driver_id, cls.__name__, path.name)

    return found
