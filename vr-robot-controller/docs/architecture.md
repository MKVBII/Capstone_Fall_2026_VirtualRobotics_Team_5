# VR Universal Robot Controller — Architecture & Tech Stack

**Capstone project:** VR universal controller for robots operating on a Raspberry Pi
**Last updated:** 2026-09-15
**Headset:** Meta Quest 3 (via the Quest Browser's WebXR support — no Unity, no APK, no Developer Mode/sideloading)
**First test robot:** OSOYOO Robot Car Kit for Raspberry Pi, model **2020005500** ("Pi Car")
**Deadline:** December 11, 2026

## 0. Why this design, not the ROS 2 + Unity one

An earlier version of this doc specified Unity + ROS 2 + rosbridge. That's a legitimate design and worth knowing exists, but it was replaced because, given the Dec 11 deadline and no requirement from the program to use ROS 2 or Unity specifically, most of that stack's complexity buys nothing a single-robot demo needs: a Unity/Quest APK build-deploy loop that costs minutes per test instead of a browser refresh, a ROS 2 install/build on a Pi 3/4 that eats real time on its own, and rosbridge as an extra protocol layer on top of a WebSocket you'd need anyway. This version gets the same end result — a Quest headset driving a robot on a Pi, over Wi-Fi, with video and telemetry, PLUS a runtime driver-plugin system for adding new robots — in **1,188 lines** of actual application code (810 Python + 378 JS, measured directly from `pi-server/` and `quest-client/`) instead of ~3,000 for the ROS 2 version, with a far shorter iteration loop while tuning.

**"Universal" is preserved, just without ROS 2's machinery for it.** See section 3 — the seam is a plain Python interface (`RobotDriver`) plus a documented WebSocket JSON contract, not a message-passing framework.

## 1. Concept summary

A Quest 3, using its browser's built-in WebXR support, loads a page served from the Raspberry Pi. That page reads controller thumbstick axes and headset orientation each frame, throttles them to ~20–30 messages/second, and sends them over a WebSocket to a small Python server running on the Pi. The server runs those values through a mapping layer (deadzone, response curve, tank mixing) and hands the result to a robot-specific driver module, which is the only place that talks to actual motor/GPIO/I2C hardware. A separate video pipeline (camera → `rpicam-vid` → a streaming server → the browser's `<video>` element) is deliberately kept off the WebSocket, since JSON-over-WebSocket is fine for control values but wrong for video.

## 2. Tech stack

### VR client (Meta Quest 3, WebXR)
- **Runtime:** the Quest Browser's native WebXR API — no engine, no build step, no app install. Any other WebXR-capable browser/headset would also work; nothing here is Quest-specific beyond which controllers map to which `handedness`.
- **Rendering:** Three.js (via CDN) for the video panel quad and any future 3D UI — kept minimal, this is not a game engine project.
- **Networking:** a plain `WebSocket` — no rosbridge, no protocol framework, just JSON messages (see `docs/message_contract.md`).
- **Constraint:** WebXR requires a secure context (`https://`, or `localhost`). The page must be served over HTTPS from the Pi — see `docs/setup_guide.md`.

### Robot side (Raspberry Pi)
- **OS:** stock **Raspberry Pi OS (Bookworm, 64-bit)**. There's no ROS 2 in this design, so the earlier reason to prefer Ubuntu Server (official ROS 2 Jazzy packages) no longer applies — Raspberry Pi OS already has `rpicam-vid`/`picamera2` and GPIO tooling set up, and matches what OSOYOO's own tutorials assume.
- **Server:** a single Python 3 process (`pi-server/server.py`) using the `websockets` library — `asyncio`, no framework.
- **Motor/GPIO access:** `RPi.GPIO`. Confirmed correct: the model 2020005500 manual only lists support for Raspberry Pi 2, 3, 3A+, and 4 — no Pi 5, so there's no GPIO-library ambiguity.
- **Video streaming:** `rpicam-vid` (the kit's camera is CSI, not USB) publishing into **mediamtx**, a single-binary media server that serves HLS (simple, ~2–6s latency, what the client uses by default) and/or WebRTC/WHEP (lower latency, more setup) with zero custom streaming code.
- **Process management:** two systemd services — `pi-server.service` and `streaming.service` — so the Pi comes up ready on boot.
- **Safety:** a watchdog loop inside `server.py`, independent of the message-handling code path, that stops the robot if no control message arrives within 300ms.

### Dev/build tooling
- Git monorepo (see file structure below)
- No build step on either side — edit Python, restart the process; edit JS, refresh the browser
- `pytest` for the mapping-layer unit tests (pure functions, no hardware needed to test them)

## 3. The universal seam: a runtime driver-plugin system

This is the part that replaces ROS 2's adapter-plugin architecture, and it now supports what ROS 2's version didn't get built for either: dropping in a new robot's driver file and having it work with zero changes anywhere else, plus switching which robot is active at runtime instead of at deploy time. Full walkthrough for adding a robot: `docs/adding_a_robot.md`. The pieces:

- **`pi-server/robot_driver_base.py`** defines `RobotDriver`, an abstract interface generalized to cover both wheeled/tracked AND flying/boat-like robots (arm/legged robots are explicitly out of scope — they need per-joint/IK control, a different enough problem that forcing it through this shape would hurt the robots it's meant to cover): `set_axes(x, y, z, yaw)` for continuous control, `set_camera_yaw(deg)` for head-tracking-driven pan, `command(name, **kwargs)` + `supported_commands()` for anything discrete and robot-specific (arm, takeoff, land, ...), `stop()` for e-stop, `get_status()` for telemetry, and `shutdown()` for releasing hardware when swapped out. A wheeled robot only implements `set_axes` using `y`/`yaw` and returns `[]` from `supported_commands`; a flying robot uses all four axes and lists `["arm", "takeoff", "land"]` or similar.
- **`pi-server/driver_registry.py`** auto-discovers every `RobotDriver` subclass in `pi-server/drivers/*.py` at runtime — no manual registration list, no code to edit when adding a robot. A file starting with `_` is skipped (the convention `_template_driver.py` uses to stay off the menu). Each file is imported in its own `try/except`: a broken or half-finished driver is logged and skipped, never fatal to the server or to whichever robot is currently active — a safety property that matters specifically because this is meant to be safe to poke at live, mid-demo.
- **`pi-server/server.py`** holds at most one active driver instance, selected at runtime over the WebSocket (`selectRobot`), not chosen at startup or via a config file that needs a restart. Switching calls the old driver's `stop()` then `shutdown()` before instantiating the new one.
- **`quest-client/`'s robot-select menu** (`index.html`'s `#robot-menu`, driven by `main.js`) is the "menu screen on bootup": it queries the server for available drivers on connect, lets you pick one, and shows a "Rescan drivers/" button so a driver file uploaded after the page loaded shows up without restarting anything. Command buttons for whatever `supported_commands()` returns are generated automatically — no per-robot UI code.
- **`pi-server/mapping.py`**'s `condition_axis()` (deadzone + curve + clamp) is applied once, centrally, in `server.py` to all 4 incoming axes before any driver sees them — every robot benefits from the same tuning without needing to remember to apply it. `tank_mix`/`single_stick_mix` are wheeled-robot-specific mixing helpers a driver can call on top of that; a flying robot's driver typically skips them and passes conditioned axes close to directly into its flight-control SDK.
- **The WebSocket JSON message shape** (`docs/message_contract.md`) is the wire-level version of the same idea: generic `x`/`y`/`z`/`yaw` axes (not `leftStick`/`rightStick`, which only made sense for a 2-wheeled robot) plus `listRobots`/`selectRobot`/`command` for the plugin system.

What this still does *not* give you, compared to the ROS 2 version: a standard message format other ROS tooling could consume, or simulation via Gazebo. Neither is needed for this project's actual deliverable, so neither is worth building.

## 4. Architecture (layered view)

```
┌────────────────────── Meta Quest 3 Browser (WebXR page) ──────────────────────┐
│  #robot-menu: list/select robot, rescan drivers/, per-robot command buttons   │
│  input.js: read controller axes + head pose each frame                        │
│  network.js: throttle to ~25Hz, send over WebSocket; receive status/menu msgs │
│  video-panel.js: <video> (HLS from mediamtx) → Three.js quad in the scene      │
└───────────────────────────────────┬─────────────────────────────────────────────┘
                                     │ Wi‑Fi (same LAN)
                                     │  • control/status/menu: WebSocket :8765 (JSON)
                                     │  • video: HLS :8888 or WebRTC/WHEP :8889
┌────────────────────────────────────▼──────────────────────────────────────────┐
│                  Raspberry Pi — Raspberry Pi OS (Bookworm)                     │
│                                                                                  │
│  pi-server/driver_registry.py  ── auto-discovers drivers/*.py at runtime      │
│  pi-server/server.py                                                           │
│    ├── watchdog_loop()        ── independent e-stop on link loss              │
│    ├── status_push_loop()     ── periodic RobotStatus → client                │
│    ├── selectRobot handling   ── stop()+shutdown() old, instantiate new       │
│    └── on control → mapping.condition_axis() (all 4 axes) → driver.set_axes() │
│                                                                                  │
│  pi-server/drivers/osoyoo_car_driver.py   ── implements RobotDriver (wheeled) │
│  pi-server/drivers/_template_driver.py    ── copy this for a new robot        │
│    (only the ACTIVE driver touches GPIO/I2C/sockets at any given moment)      │
│                                                                                  │
│  mediamtx + rpicam-vid  ── separate process, camera → HLS/WebRTC              │
└──────────────────────────────────────────────────────────────────────────────┘
                                     │  GPIO (L298N direction) / I2C (PCA9685 PWM)
                                     ▼
                    OSOYOO Pi Car, model 2020005500 (2 driven wheels + caster,
                    ultrasonic + 5-ch line-tracking sensors, SG90 servo, CSI camera)
```

## 5. Repository / file structure

```
vr-robot-controller/
├── README.md                       # project bible + roadmap
├── docs/
│   ├── architecture.md             # this document
│   ├── message_contract.md         # the WebSocket JSON contract
│   ├── setup_guide.md              # Pi + Quest bring-up instructions
│   └── adding_a_robot.md           # the "upload a driver, it just works" walkthrough
├── pi-server/
│   ├── server.py                   # WebSocket server, watchdog, status push, robot switching
│   ├── driver_registry.py          # auto-discovers drivers/*.py at runtime
│   ├── mapping.py                  # condition_axis/tank-mix/single-stick-mix/head-smoothing
│   ├── robot_driver_base.py        # the universal RobotDriver interface (wheeled + flying)
│   ├── drivers/
│   │   ├── osoyoo_car_driver.py    # FIRST ROBOT: OSOYOO Pi Car (L298N + PCA9685)
│   │   └── _template_driver.py     # copy this to add a new robot (leading _ = not selectable)
│   ├── requirements.txt
│   └── config.example.json
├── quest-client/
│   ├── index.html                  # WebXR page + robot-select menu markup
│   └── js/
│       ├── main.js                 # session bootstrap, render loop, menu orchestration
│       ├── input.js                # controller/head input reading (Mode 2 axis layout)
│       ├── network.js              # WebSocket client (throttled, reconnecting, menu/command msgs)
│       └── video-panel.js          # video quad in the XR scene
├── streaming/
│   ├── mediamtx.yml                # HLS/WebRTC server config
│   └── start-stream.sh             # rpicam-vid → mediamtx
├── pi_setup/
│   ├── install.sh                  # Raspberry Pi OS provisioning
│   └── systemd/
│       ├── pi-server.service
│       └── streaming.service
└── tests/
    ├── pi_server_tests/
    │   ├── test_mapping.py         # unit tests for the mapping layer (passing)
    │   └── test_driver_registry.py # discovery, error isolation, template exclusion (passing)
    └── quest_client_tests/
        └── README.md
```

## 6. OSOYOO Pi Car (model 2020005500) — confirmed hardware

- **Compatible Pi boards:** Raspberry Pi 2, 3, 3A+, 4 — no Pi 5.
- **Drivetrain:** 2 independently driven gear motors + 1 passive universal wheel (differential drive).
- **Motor driver:** L298N-family board + OSOYOO PWM HAT v1.01 (PCA9685 over I2C). Exact IN1–IN4/ENA/ENB pin numbers aren't in the manual — read them off the physical board before wiring `osoyoo_car_driver.py`.
- **Sensors, with confirmed GPIO pins:** 5-channel line-tracking array on GPIO 25/9/11/8/7; ultrasonic on GPIO 20/21 (trigger/echo); onboard voltage meter for `RobotStatus.battery_voltage`.
- **Extra actuator:** SG90 micro servo, used here for camera pan via `set_camera_yaw`.
- **Camera:** CSI ribbon camera — confirms `rpicam-vid`, not a USB/v4l2 pipeline.

## 7. Roadmap to December 11

Matched to the ~12-week window from Sept 15, in the stated priority order: get the car solid first, then the driver-plugin/menu system (already built — see section 3), then add the drone on top of it. Each phase is meant to be validated in isolation before combining — see the note at the bottom.

| Weeks | Milestone |
|---|---|
| 1–2 | Hardware bring-up, done separately: drive the car from a keyboard script on the Pi (OSOYOO's own motor code); get `rpicam-vid` → mediamtx streaming to a plain browser tab, no VR yet |
| 3–4 | `pi-server/server.py` and the WebXR page, wired together with dummy values first, then real controller axes; watchdog tested by killing Wi-Fi mid-drive; wire `osoyoo_car_driver.py`'s TODOs to real GPIO/PCA9685 pins |
| 5–6 | Tune `mapping.py` by feel: deadzone, curve, single-stick mixing, head-yaw smoothing. Car should be solid and demo-ready by the end of week 6. |
| 7 | Driver-plugin system: already scaffolded (`driver_registry.py`, the robot-select menu, `docs/adding_a_robot.md`) — this week is verifying it end-to-end on hardware (reselecting the car driver, confirming `shutdown()`/GPIO cleanup actually releases pins) rather than building it from scratch |
| 8–9 | Add the drone driver (`drivers/<drone>.py` from the template) once hardware is chosen — see the open decision below. Integrate video panel + drive controls; buffer for first-time hardware/wireless debugging |
| 10–12 | Polish, write-up, demo rehearsal (practice switching robots live via the menu), buffer before the deadline |

**Don't skip the isolation step.** Get video working alone. Get motors working alone from a keyboard script on the Pi. Only then connect them. If everything is wired up at once and nothing moves, there's no way to tell which of headset, network, Python, or I2C is at fault.

## 8. Open decisions

- **HTTPS for the Quest page:** WebXR requires a secure context. Simplest options: a self-signed cert (browser shows a one-time warning to accept), or a tool like Caddy that provisions one automatically. Needs picking before week 3.
- **Video protocol:** HLS (current default, simple, ~2–6s latency) vs. WebRTC/WHEP (lower latency, more setup) — mediamtx supports both from the same source, so this can be revisited without re-architecting.
- **Motor driver exact pinout:** read IN1–IN4/ENA/ENB off the physical board.
- **SG90 servo / head tracking:** currently wired into the design (`set_camera_yaw`); drop it if it's not worth the tuning time.
- **Which drone:** an SDK-controllable drone (e.g. a DJI Tello EDU, which supports joining an existing Wi-Fi network via its `ap` command instead of hosting its own hotspot — the regular non-EDU Tello can't do this and would need a second Wi-Fi radio on the Pi to stay reachable) is strongly preferred over a custom-built drone with the Pi driving ESCs directly — the latter means building real flight stabilization, a materially bigger and riskier scope for this timeline. Not yet purchased as of this writing.
- **In-VR robot switching:** currently requires exiting the VR session back to the 2D menu (see `quest-client/js/main.js`'s `session.addEventListener("end", ...)`). An in-headset menu via the WebXR DOM Overlay feature is a possible future upgrade if switching robots without removing the headset turns out to matter for the demo.

## Sources
- [OSOYOO Robot Car V2.0 for Raspberry Pi — Introduction](https://osoyoo.com/2020/08/01/osoyoo-raspberry-pi-v2-0-car-introduction/)
- [OSOYOO Raspberry Pi Car V2.1 Lesson 1: GPIO/PCA9685 basic install](https://osoyoo.com/2022/07/21/osoyoo-raspberry-pi-car-v2-1-lesson-1-basic-install-and-coding-gpio-pca9685-python/)
- [OSOYOO Raspberry Pi Robot Car User Manual, model 2020005500 (PDF)](https://osoyoo.com/manual/2020005500.pdf)
- [mediamtx](https://github.com/bluenviron/mediamtx)
- [Three.js](https://threejs.org/)
