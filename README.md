# Virtual Robotics: VR Robot Car Controller

**Team 5, Capstone Fall 2026**: Wesley Burcham, Matthew Palmer, Michael Brown

Drive a Raspberry Pi robot car from a **Meta Quest 3** headset. The car's
camera shows live on a screen floating in VR, and the Quest's joysticks drive
the wheels.

---

## What this project is

Many small robots are controlled in very similar ways: a few motors and a
camera, run by a small computer. This project explores whether **one VR
controller** can drive robots like these. We're building it first for one
real robot, the **OSOYOO Pi Car**, and getting it fully working before
generalizing.

### Requirements (from our requirements document)

| Priority | Requirement |
|---|---|
| **Must** | The Meta Quest controls the motors attached to the Raspberry Pi: forward, backward, left and right. |
| **Must** | The Meta Quest displays the live camera feed from the car. |
| Should | Show data about the robot, such as orientation, speed and position. |

**Controls** (from the requirements document's usability section):
- **Left joystick = throttle.** Push forward to drive forward, pull back to reverse. The further you push, the faster it goes.
- **Right joystick = turning.** Push left or right to turn.

---

## Hardware

| Part | Role |
|---|---|
| **Meta Quest 3** (with controllers) | The driver's headset and joysticks. Runs the control page in its built-in web browser. |
| **Raspberry Pi 4** | The car's brain. Runs our Python programs. |
| **OSOYOO Pi Car** (model 2020005500) | The chassis: 2 driven wheels, battery pack, PWM HAT, motor driver, camera mount. |
| **PWM HAT** (PCA9685 chip) | Sits on the Pi. Generates the speed signals for the motors. |
| **Motor driver board** (L298N-style H-bridge) | Switches battery power to the motors, forward or backward. |
| **CSI camera** | Plugs into the Pi with a ribbon cable. |
| **TP-Link 5 GHz router** | An isolated Wi-Fi network just for the headset and the car, for a fast, uncrowded connection. |

---

## How it works

### Controls: joystick to wheels

```
Quest joystick
   │  read every frame by JavaScript in the Quest Browser (WebXR Gamepad API)
   ▼
Quest Browser ──── WebSocket over Wi-Fi ────►  Raspberry Pi: Python control server
                                                  │  turns stick positions into
                                                  │  left/right wheel speeds
                                    ┌─────────────┴─────────────┐
                                    ▼                           ▼
                          GPIO pins (gpiozero)        I2C bus → PWM HAT (PCA9685)
                          = wheel DIRECTION           = wheel SPEED
                                    └─────────────┬─────────────┘
                                                  ▼
                                   Motor driver board (H-bridge)
                                                  ▼
                                      Gear motors → wheels
```

- **Why the headset's browser and not a Unity app?** The Quest Browser
  supports VR web pages (WebXR) natively, so the "app" is just a web page
  served by the Pi. There's nothing to install or sideload on the headset,
  and a code change takes effect with a page refresh, not a rebuild.
- **Why a WebSocket?** It's a connection that stays open in both directions,
  so each stick update reaches the Pi immediately. That's the right fit for
  live control, unlike normal web requests, which reconnect every time.
- **Two signals per wheel:** direction comes from two on/off GPIO pins, and
  speed from a PWM signal produced by the HAT. `motor_test.py` explains this
  in detail.
- **Safety stop:** if the Pi stops receiving joystick messages for 0.3
  seconds, it stops the car. This covers Wi-Fi dropping, the headset being
  taken off, or the page closing. A car must never keep doing the last thing
  it was told.

### Video: camera to headset

```
CSI camera ── ribbon cable ──► Pi 4: picamera2 captures frames
                                  │  hardware-encoded to JPEG pictures
                                  ▼
                       Python web server (Flask): "MJPEG" stream
                       (a continuous series of JPEG pictures)
                                  │  Wi-Fi (5 GHz router)
                                  ▼
            Quest Browser draws each picture on a screen floating in VR
```

- **Why MJPEG first, not H.264?** Our requirements doc planned for H.264
  video. Browsers can't play a raw H.264 stream on their own; it needs an
  extra system such as WebRTC or HLS. Those either add significant setup
  (WebRTC) or 2–6 seconds of delay (HLS), which is too slow to steer by.
  MJPEG works in any browser with no extra software, typically arrives in
  well under half a second, and costs almost no CPU on the Pi 4. Its
  drawback is that it uses more Wi-Fi bandwidth (roughly 3–6 Mbps at
  640×480), which the dedicated 5 GHz router handles easily. **If bandwidth
  becomes a problem, H.264 over WebRTC is the planned upgrade.**
- **Video is a separate program from the controls.** A video slowdown or
  crash can never delay a steering command or the safety stop.
- **Only the newest frame is ever sent.** On a slow moment, frames are
  skipped instead of queued, so the picture stays live instead of falling
  behind.

### Programs on the Pi (when finished)

| Program | Port | Job |
|---|---|---|
| Camera server (`camera_server.py`) | 8000 | Camera → MJPEG video stream; also serves the VR web page |
| Control server (planned) | 8765 | Joystick messages → motors, plus the 0.3 s safety stop |

The Quest only allows VR on secure (`https://`) pages, so the headset step
adds a self-signed security certificate. Until then, everything runs over
plain `http://` for testing in a laptop browser.

---

## Repository layout

```
Capstone_Fall_2026_VirtualRobotics_Team_5/
├── README.md                     this file
├── Team 5 Requirements Doc (Final Draft).pdf
├── Team 5 Requirements Doc (Rough Draft).pdf
└── vr-robot-controller/
    └── robot-car/
        ├── SETUP.md              START HERE: Pi setup and each test, step by step
        ├── motor_test.py         Test 1: wheels move
        └── camera_server.py      Test 2: live camera in a laptop browser
```

**To get started, follow [`vr-robot-controller/robot-car/SETUP.md`](vr-robot-controller/robot-car/SETUP.md).**

---

## Build plan: one layer at a time

Each test adds exactly **one** new thing on top of what already works. If a
test fails, the problem must be in that one new thing. New files are added
only when the next test needs them.

| # | Test | What it proves | Status |
|---|---|---|---|
| 1 | `motor_test.py` | Motors, wiring, PWM HAT and battery all work | ✅ Passed |
| 2 | `camera_server.py` in a laptop browser | The camera works and video reaches another device over Wi-Fi | 🔜 Ready to run |
| 3 | Camera in the headset | The VR page loads on the Quest over https, and the video shows on a floating screen | Not built yet |
| 4 | Left stick throttle (forward/back) | Joystick → WebSocket → Pi → motors, plus the safety stop | Not built yet |
| 5 | Right stick turning | Turning, blended smoothly with throttle | Not built yet |
| 6 | Polish | Video comfort in the headset, speed limits, and optional sensor readouts (distance to obstacles from the car's ultrasonic sensor) | Not built yet |

This follows the order of our sprint plan. The camera is being tested
before the joysticks because it needs no motor code, which makes it the
quicker win.

---

## Safety

- **First run of any motor code: put the car on a block** with the wheels off the ground.
- **The 0.3-second safety stop** halts the car whenever joystick messages stop arriving.
- **Headset users:** clear the area and have a spotter. VR can cause
  disorientation or motion sickness, and the wearer can't see real
  obstacles. Take the headset off if you feel unwell.

---

## Beyond the car: the universal controller

The project's long-term idea is one controller for many kinds of robots.
An earlier version of this repo was built that way, with swappable robot
"drivers" and a robot-select menu. It was set aside so we could get the car
fully working first. It's saved in git under the tag **`universal-version`**.

To look at it or bring a piece back:

```powershell
git checkout universal-version -- vr-robot-controller/pi-server
```

Replace `pi-server` with whichever folder you need: `pi-server`,
`quest-client`, `docs` or `tests`.
