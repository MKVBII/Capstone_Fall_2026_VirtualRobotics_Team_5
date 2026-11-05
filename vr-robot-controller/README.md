# VR Robot Controller: OSOYOO Pi Car

Team 5 capstone (Fall 2026): drive a Raspberry Pi robot car from a Meta Quest 3
headset, with live video from the car's camera.

**Current focus:** the OSOYOO Pi Car (model 2020005500), built and tested
one step at a time.

## Folder

```
vr-robot-controller/
└── robot-car/              everything that runs on the car's Pi
    ├── SETUP.md            start here: Pi setup + tests, step by step
    ├── camera_server.py    camera + website (http 8000, https 8443)
    ├── drive_server.py     driving from the headset (wss 8765)
    ├── hardware/           camera_pan.py, rear_sensor.py, pi_status.py
    ├── tests/              motor_test.py + README.md (every test command)
    └── web/                pages/, css/, js/, lib/ (the website)
```

Run everything from `~/robot-car` on the Pi, e.g.
`python3 camera_server.py`, `python3 drive_server.py`,
`python3 hardware/rear_sensor.py --selftest`.

## Progress

| Test | What it proves | Status |
|---|---|---|
| 1. `tests/motor_test.py` | Motors, wiring, PWM HAT, battery | Passed |
| 2. `camera_server.py` | Camera works and streams over Wi-Fi | Working |
| 3. Camera in the headset | Video reaches the Quest in mixed reality | Working |
| 4. Joystick driving | Quest thumbsticks drive the car | Working |
| 5. Polish | Head-look camera, dashboard, rear sensors | In progress |

## The earlier "universal controller" version

The first version of this repo was built to control many kinds of robots
(driver plugins, robot-select menu). It was set aside to focus on getting
the car working. It's saved in git under the tag **`universal-version`**. To
look at it or bring a piece back:

```powershell
git checkout universal-version -- vr-robot-controller/pi-server
```

(Replace `pi-server` with whichever folder you need.)
