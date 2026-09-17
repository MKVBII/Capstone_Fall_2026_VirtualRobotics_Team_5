# VR Universal Robot Controller

Capstone project: a **Meta Quest 3** WebXR page (no Unity, no APK, no
Developer Mode) that drives robots running on a Raspberry Pi, through a
runtime driver-plugin system and a small WebSocket JSON contract. Drop a
driver file for a new robot into `pi-server/drivers/`, pick it from the
in-headset menu, and it runs — no other code changes. The first physical
robot this is being built and tested against is the **OSOYOO Robot Car
Kit for Raspberry Pi, model 2020005500** (2-wheel differential drive,
L298N + PCA9685/PWM HAT motor driver, CSI camera, ultrasonic +
line-tracking sensors, SG90 servo). This kit supports Raspberry Pi
2/3/3A+/4 only — no Pi 5. A drone is next, once the car is solid — see
the roadmap.

**Deadline: December 11, 2026.**

This repo is the project "bible" — the structure below is the agreed
architecture and every new piece of work should land in the folder that
already exists for it rather than inventing a new top-level location.

Full architecture writeup, including why this design was chosen over an
earlier ROS 2 + Unity version, the driver-plugin system, and the
week-by-week roadmap to Dec 11: [`docs/architecture.md`](docs/architecture.md)

**Adding a robot? Start here:** [`docs/adding_a_robot.md`](docs/adding_a_robot.md)

## How it fits together

```
Meta Quest 3 Browser (WebXR, quest-client/)
  #robot-menu: pick a robot, rescan drivers/, per-robot command buttons
        │  WebSocket :8765, JSON        (control + robot menu + status)
        │  HLS :8888 / WebRTC :8889     (video, via mediamtx)
        ▼
Raspberry Pi — Raspberry Pi OS Bookworm (pi-server/)
  driver_registry.py → auto-discovers drivers/*.py at runtime
  server.py → mapping.condition_axis() (universal signal conditioning)
            → whichever driver is currently selected (drivers/osoyoo_car_driver.py, ...)
  streaming/ → rpicam-vid → mediamtx (CSI camera → HLS/WebRTC)
        │  GPIO (L298N direction) / I2C (PCA9685 PWM) / whatever the active driver needs
        ▼
OSOYOO Pi Car hardware, model 2020005500 (first robot; more via drivers/)
```

## Repo layout

| Path | What lives here |
|---|---|
| `quest-client/` | WebXR page — robot-select menu, controller/head input, WebSocket networking, video panel |
| `pi-server/server.py` | WebSocket server: control messages, watchdog, status push, robot switching |
| `pi-server/driver_registry.py` | Auto-discovers `drivers/*.py` at runtime — the "upload a file, it runs" mechanism |
| `pi-server/mapping.py` | `condition_axis` (deadzone/curve/clamp) + wheeled-robot mixing helpers — pure functions, unit tested |
| `pi-server/robot_driver_base.py` | The universal `RobotDriver` interface (wheeled + flying/boat-like) every robot implements |
| `pi-server/drivers/osoyoo_car_driver.py` | **First robot.** |
| `pi-server/drivers/_template_driver.py` | Copy this to add a new robot — see `docs/adding_a_robot.md` |
| `streaming/` | mediamtx config + the `rpicam-vid` capture script |
| `pi_setup/` | Raspberry Pi provisioning: install script, systemd services |
| `docs/` | Architecture doc (with the roadmap), message contract, setup guide, adding-a-robot guide |
| `tests/` | `pi-server` unit tests: mapping layer + driver registry (passing) |

## Getting started

1. Read `docs/architecture.md` first — it's the source of truth for design decisions, including why ROS 2/Unity were dropped and how the driver-plugin system works.
2. Pi side: follow `docs/setup_guide.md`, then `pi_setup/install.sh`.
3. Start `pi-server/server.py` and the streaming pipeline (`streaming/start-stream.sh` + mediamtx).
4. Quest side: serve `quest-client/` over HTTPS from the Pi (see setup guide — WebXR requires a secure context), open it in the Quest Browser.
5. Pick a robot from the menu, tap "Enter VR."
6. First integration milestone: drive the OSOYOO car's base end-to-end from the headset before adding video/sensors — see the roadmap for the full build order.
7. Adding the drone (or any other robot) later: `docs/adding_a_robot.md`.

## Status

- [x] `pi-server/mapping.py` implemented and unit tested
- [x] `pi-server/server.py` WebSocket server + watchdog implemented
- [x] `pi-server/robot_driver_base.py` generalized for wheeled + flying robots
- [x] `pi-server/driver_registry.py` auto-discovery + error isolation, unit tested
- [x] `quest-client/` robot-select menu + WebXR page implemented (input, networking, video panel)
- [x] `docs/adding_a_robot.md` written
- [x] Full test suite passing (19/19 — `pytest tests/pi_server_tests/`)
- [ ] Motor driver wired to real OSOYOO hardware (`osoyoo_car_driver.py` — pin numbers TODO)
- [ ] HTTPS serving set up for the Quest page
- [ ] Video streaming verified end-to-end (mediamtx + rpicam-vid)
- [ ] First real drive test on hardware
- [ ] Ultrasonic + line-tracking sensors wired into `get_status()`
- [ ] Camera pan servo (`set_camera_yaw`) wired to real hardware
- [ ] Driver-plugin system verified end-to-end on real hardware (runtime robot switching + GPIO cleanup on `shutdown()`)
- [ ] Drone hardware chosen (see `docs/architecture.md` open decisions — leaning SDK-controllable, e.g. Tello EDU)
- [ ] Drone driver written from `_template_driver.py`
