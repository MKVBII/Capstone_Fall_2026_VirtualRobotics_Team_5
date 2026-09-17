# Adding a robot

Target: someone with a wheeled/tracked or flying/boat-like robot on a
Raspberry Pi can add support for it here in well under 5 minutes of
actual setup work (writing the driver logic itself takes as long as it
takes — this is about the *integration* overhead being near zero).

## The process

1. Copy `pi-server/drivers/_template_driver.py` to `pi-server/drivers/<your_robot_name>.py`. The filename becomes the driver's id.
2. Rename the class, set `DISPLAY_NAME` and `DESCRIPTION`.
3. Implement `set_axes`, `stop`, and `get_status` at minimum (the others have safe defaults or can return empty/no-op). The template has worked examples for both a wheeled and a flying robot.
4. Drop the file in `pi-server/drivers/` (scp it, git pull it, whatever gets it onto the Pi).
5. Restart `pi-server/server.py` — or, if it's already running, click "Rescan drivers/" on the Quest page's robot-select menu, which sends a `listRobots` message and re-runs discovery without a restart.
6. Your robot now appears in the menu.

That's the whole integration surface. You do **not** need to touch `server.py`, `mapping.py`, `driver_registry.py`, or anything under `quest-client/` — see `docs/architecture.md` section 3 for why that boundary holds.

## What "5 minutes" actually covers

It covers steps 1–6 above: file placement, naming, and getting it discovered and selectable. It does **not** cover writing correct motor/flight-control logic inside your driver — that's real engineering work specific to your hardware, and nothing here can shortcut it. What this system removes is everything *around* that work: no registration list to edit, no server code to modify, no risk that a mistake in your driver breaks anyone else's robot (see the safety property below), and no changes to the Quest-side page regardless of whether your robot is wheeled or flying.

## Safety property: a broken driver can't take the whole thing down

`driver_registry.py` imports each file in `drivers/` independently, in its own `try/except`. If your file has a syntax error, an import error, or doesn't define a `RobotDriver` subclass, it's logged and skipped — every other driver, including whichever one is currently active and flying/driving, is unaffected. This is deliberate: it means uploading a half-finished driver mid-demo to test it is safe to attempt, not something that risks the working robot.

The one thing to get right regardless of how rough the rest of your driver is: `stop()` must never raise, under any circumstances, including if `__init__` never finished setting up hardware. It's called by the watchdog on link loss and whenever your driver is swapped out for another one — see `robot_driver_base.py`'s docstring on it.

## The axis convention

`set_axes(x, y, z, yaw)` follows the standard "Mode 2" RC/drone stick layout (see `quest-client/js/input.js`):

| Axis | Meaning | Wheeled robots | Flying robots |
|---|---|---|---|
| `x` | strafe / roll | usually ignored | roll |
| `y` | forward-back / pitch | forward/back | pitch |
| `z` | vertical / throttle | usually ignored | throttle |
| `yaw` | turn / yaw rate | turn | yaw rate |

All four arrive already deadzone- and curve-conditioned (`mapping.condition_axis`, applied once in `server.py` — don't re-apply your own deadzone/curve on top of this). Use `mapping.single_stick_mix`/`tank_mix` if you need wheeled-robot mixing helpers; write your own pure-function helpers in `mapping.py` if your robot needs a mix those don't cover, rather than putting the math inside the driver class itself — keeps it testable the same way the existing mixing functions are (see `tests/pi_server_tests/test_mapping.py`).

## Discrete commands (arm, takeoff, land, ...)

Continuous axes cover steering/flying; anything else your robot needs — arming, taking off, landing, honking a horn — goes through `command(name, **kwargs)` and gets listed in `supported_commands()`. The Quest page reads `supported_commands()` after you're selected and renders a button per command automatically — you don't need to touch any UI code for this either.

## Runtime robot switching

`server.py` keeps at most one driver instance active. Selecting a new robot calls the old one's `stop()` then `shutdown()` before instantiating the new one — implement `shutdown()` if your driver holds exclusive hardware (GPIO pins, a serial port, a UDP socket) that the next-selected robot might need, so switching robots mid-demo doesn't leave your pins/ports held open.
