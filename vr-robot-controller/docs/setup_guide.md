# Setup Guide

> TODO: fill in as each step is actually verified on hardware. This is the
> skeleton to fill in, not a finished guide yet.

## 0. Dev machine (no Pi, no robot — for running tests / `docs/sprint1_demo.md`)

You don't need any of the Pi/Quest steps below just to run the test suite
or the hardware-free demo on your own laptop. You do need a real Python
install, which trips people up on Windows specifically:

**Windows:** `python3` is not a real command on Windows even after
installing Python — use `python` and `pip` instead everywhere these docs
say `python3`. If `python`, `python3`, and `pip` all fail with
"not recognized" or open the Microsoft Store, Python isn't actually
installed yet — that error is Windows' app-execution-alias stub, not a
real Python. Fix:

1. Install Python from [python.org/downloads](https://www.python.org/downloads/)
   (not the Microsoft Store listing) — on the first installer screen,
   check **"Add python.exe to PATH"** before clicking Install.
2. Close and reopen PowerShell (PATH changes don't apply to an
   already-open terminal).
3. Verify: `python --version` and `pip --version` should both print a
   version number.
4. If it still fails after that: Settings → Apps → Advanced app settings
   → App execution aliases → turn OFF the `python.exe`/`python3.exe`
   entries under "App Installer," then reopen PowerShell.
5. Alternative to steps 1-2 if you'd rather stay in PowerShell:
   `winget install Python.Python.3.12`, then reopen PowerShell.

**Mac/Linux:** `python3` and `pip3` (or `pip` inside a venv) should
already work if Python 3.9+ is installed; `brew install python3` (Mac) or
your distro's package manager if not.

Once `python`/`python3` + `pip` work, from `pi-server/`:
```
pip install -r requirements.txt
pip install pytest
python -m pytest ../tests/pi_server_tests -v    # Windows: python, not python3
```
See `docs/sprint1_demo.md` for the two-terminal live demo.

## 1. Raspberry Pi (OSOYOO car, model 2020005500)

0. **Physically assemble and seat the Pi first — this is a hardware step,
   not something any script does for you.** The OSOYOO PWM HAT is a real
   HAT (Hardware Attached on Top): it plugs directly onto the Raspberry
   Pi's 40-pin GPIO header, and the L298N motor driver, motors, line-
   tracking sensors, ultrasonic sensor, SG90 servo, and battery all wire
   into that assembly per OSOYOO's own build manual/video (linked in
   `docs/architecture.md`'s Sources). None of `pi-server/server.py` or
   `osoyoo_car_driver.py` can do anything until this physical assembly is
   done — the Python code only talks to GPIO/I2C pins that are already
   electrically wired to real hardware. Confirm the Pi boots and `i2cdetect
   -y 1` (after step 2 below) sees the PCA9685 before writing any driver
   code against it.
1. Flash **Raspberry Pi OS (Bookworm, 64-bit)** to the SD card. Must be a
   Pi 2, 3, 3A+, or 4 — this kit doesn't support the Pi 5.
2. Enable I2C (for the PWM HAT / PCA9685) and the camera interface via
   `raspi-config` (see `pi_setup/install.sh`).
3. Run `pi_setup/install.sh` to set up the `pi-server` Python virtualenv
   and install `websockets`.
4. Download `mediamtx` (arm64 build) into `streaming/` — see
   `streaming/mediamtx.yml` for how it's configured.
5. Wire the motor driver per the physical board (IN1-4/ENA/ENB pin numbers
   aren't in the manual — read them off the board and update
   `pi-server/drivers/osoyoo_car_driver.py`), and confirm the sensor GPIO
   pins already documented in `docs/architecture.md` section 6.
6. **Set up HTTPS for serving `quest-client/`.** WebXR requires a secure
   context — plain `http://` will make `navigator.xr` calls silently fail
   in the Quest Browser. Simplest path: generate a self-signed cert
   (`openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out
   cert.pem -days 365`) and serve `quest-client/` with a tool that can use
   it (e.g. Caddy, or Python's `http.server` wrapped with `ssl`). The
   browser will show a one-time "unsafe site" warning to click through.
7. Install the systemd services from `pi_setup/systemd/` so `pi-server`
   and the streaming pipeline start on boot.

## 2. Quest 3

1. No app install needed — this is a WebXR page, not a native app.
2. Open the Quest Browser and navigate to the Pi's HTTPS address
   (e.g. `https://192.168.1.X:8443/`). Accept the self-signed cert
   warning if prompted.
3. In `quest-client/js/main.js`, set `PI_HOST` to the Pi's actual IP
   before deploying (currently a placeholder).
4. Tap "Enter VR."

## 3. First end-to-end test

1. On the Pi: start `pi-server/server.py`, start `mediamtx` +
   `streaming/start-stream.sh` (or rely on the systemd services once
   installed).
2. On the Quest: load the page, tap "Enter VR," confirm the status
   overlay shows "Link: connected."
3. Drive with the thumbstick and confirm the car moves in the expected
   direction — if it doesn't move at all, check the Pi's server logs
   first (is a `control` message arriving?) before assuming it's a
   hardware wiring problem.
4. Confirm the watchdog works: disconnect Wi-Fi mid-drive and confirm the
   car stops within ~300ms.
5. Confirm the video panel shows a live feed, not a frozen frame.

## Debugging tip

Per `docs/architecture.md` section 7: get each piece working in isolation
before connecting them. If something's wrong once everything is wired
together, you're debugging across four boundaries at once (headset,
network, Python, I2C) — having already proven video works alone and
motors work alone from a keyboard script narrows down where to look a lot
faster than starting from "nothing moves."
