# VR Robot Controller: OSOYOO Pi Car

Team 5 capstone (Fall 2026): drive a Raspberry Pi robot car from a Meta Quest 3
headset, with live video from the car's camera.

**Current focus:** the OSOYOO Pi Car (model 2020005500) only, built and tested
one step at a time.

## Folder

```
vr-robot-controller/
└── robot-car/
    ├── SETUP.md            start here: Pi setup + tests, step by step
    ├── motor_test.py       Test 1: wheels move
    └── camera_server.py    Test 2: live camera in a laptop browser
```

## Progress

| Test | What it proves | Status |
|---|---|---|
| 1. `motor_test.py` | Motors, wiring, PWM HAT, battery | Passed |
| 2. `camera_server.py` | Camera works and streams over Wi-Fi | Next |
| 3. Camera in the headset | Video reaches the Quest in VR | Not built yet |
| 4. Joystick driving | Quest thumbstick drives the car | Not built yet |

Each new test gets its own file(s), added only after the previous test passes.

## The earlier "universal controller" version

The first version of this repo was built to control many kinds of robots
(driver plugins, robot-select menu). It was set aside to focus on getting
the car working. It's saved in git under the tag **`universal-version`**. To
look at it or bring a piece back:

```powershell
git checkout universal-version -- vr-robot-controller/pi-server
```

(Replace `pi-server` with whichever folder you need.)
