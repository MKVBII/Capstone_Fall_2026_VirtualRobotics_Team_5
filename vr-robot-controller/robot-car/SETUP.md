# Robot Car Setup Guide (OSOYOO Pi Car, model 2020005500)

This guide takes a fresh Raspberry Pi to a car whose **wheels move** and whose
**camera shows live video in a laptop browser**. The VR headset and joystick
driving come next, one file at a time, after these two tests pass.

**Rule for the whole project: test one layer at a time.** Each test below
adds exactly one new thing. If a test fails, the problem is in that one new
thing, not anywhere else.

---

## What's in this folder

```
robot-car/
├── SETUP.md            this guide
├── motor_test.py       Test 1: spins each wheel briefly
└── camera_server.py    Test 2: live camera in a browser
```

Nothing else is needed yet. More files are added only when the next test
needs them.

## What you need

- OSOYOO Pi Car, fully assembled, with the PWM HAT seated on the Pi's 40 pins
  and the camera ribbon cable connected.
- Raspberry Pi 2, 3, 3A+ or 4. This kit doesn't support the Pi 5.
- A microSD card (16 GB or more) and a way to plug it into your laptop.
- Charged batteries for the car. **The motors run off the car's battery, not
  the Pi**, so the Pi can be on while the motors have no power.
- A laptop on the **same Wi-Fi network** the Pi will join.

---

## Step 1: Flash Raspberry Pi OS

1. Install **Raspberry Pi Imager** on your laptop (raspberrypi.com/software).
2. Choose your Pi model, then **Raspberry Pi OS (64-bit)** (Bookworm), then
   your SD card.
3. When it asks to apply OS customisation, choose **Edit Settings**:
   - **Hostname:** `picar`. This lets you use `picar.local` instead of
     looking up the IP address.
   - **Username and password:** pick them and write them down. Everyone on
     the team uses the same ones.
   - **Wireless LAN:** your Wi-Fi name and password. Set the country.
   - **Services tab:** turn on **Enable SSH**, using password authentication.
4. Write the card, put it in the Pi, turn the Pi on and wait about 2 minutes.

## Step 2: Log in from your laptop (SSH)

In PowerShell on your laptop:

```powershell
ssh USERNAME@picar.local
```

- The first time, type `yes` to trust the Pi, then enter the password.
- If `picar.local` isn't found, use the Pi's IP address instead, from your
  router's device list: `ssh USERNAME@192.168.x.x`.

Every command from here until Step 5 runs **on the Pi**, in this SSH window.

Once you're logged in, `hostname -I` prints the Pi's IP address. Write it
down; the camera test uses it.

## Step 3: Install the software

Run these lines one at a time. Each is explained below it.

```bash
sudo apt update && sudo apt upgrade -y
```
Downloads the latest list of software, then updates everything already
installed. This can take 10 or more minutes on a fresh install.

```bash
sudo apt install -y git python3-pip python3-venv i2c-tools
```
- `git`: for downloading code straight from GitHub (optional; see Step 5).
- `python3-pip`: installs Python libraries that aren't packaged by Raspberry Pi OS.
- `python3-venv`: not used by our code, but harmless to have.
- `i2c-tools`: provides `i2cdetect`, which checks the PWM HAT (Step 4).

```bash
sudo apt install -y python3-smbus
```
A low-level library for talking to I2C devices. Our code doesn't use it
directly, but some I2C tools and OSOYOO examples do.

```bash
pip3 install adafruit-circuitpython-pca9685 adafruit-blinka --break-system-packages
```
- `adafruit-circuitpython-pca9685`: the driver for the PCA9685 chip on the
  PWM HAT, which sets **motor speed**.
- `adafruit-blinka`: lets Adafruit's libraries run on a Raspberry Pi. It
  provides the `board` and `busio` modules that open the I2C bus.
- `--break-system-packages`: Raspberry Pi OS normally blocks `pip` from
  installing into the system's Python, to protect it. This flag overrides
  that. It's acceptable here because this Pi's only job is running the car.

```bash
sudo apt install -y python3-gpiozero python3-lgpio
```
- `gpiozero`: switches the Pi's GPIO pins on and off, which sets **motor
  direction**. This is the GPIO library the Raspberry Pi Foundation recommends.
- `lgpio`: the low-level library gpiozero uses underneath on this OS version.

```bash
sudo apt install -y python3-picamera2 rpicam-apps
```
- `picamera2`: the Python camera library that `camera_server.py` uses.
- `rpicam-apps`: command-line camera tools, such as `rpicam-hello` (Step 4).

```bash
pip3 install flask websockets --break-system-packages
```
- `flask`: a small web server. `camera_server.py` uses it to send video to
  your browser.
- `websockets`: a live two-way connection. It isn't used yet; the joystick
  driving step will use it.

```bash
sudo apt install -y iperf3 htop
```
Troubleshooting tools:
- `htop`: a live view of CPU and memory. Press `q` to quit. Useful to check
  whether the Pi is overloaded while streaming video.
- `iperf3`: measures Wi-Fi speed between the Pi and a laptop, if video is choppy.

```bash
sudo apt install -y vim tmux
```
- `vim`: a text editor, for quick edits on the Pi. `nano` is also built in
  and is easier for beginners.
- `tmux`: keeps programs running if your SSH connection drops (see Tips).

## Step 4: Turn on I2C and check the hardware

**Turn on I2C**, which the PWM HAT needs:

```bash
sudo raspi-config
```
Use the arrow keys: **Interface Options → I2C → Yes → OK → Finish**. Then reboot:

```bash
sudo reboot
```
Wait about 30 seconds, then log back in (Step 2).

The camera does **not** need turning on in raspi-config: this OS version
detects it automatically. There is no "Legacy Camera" option to enable.

**Check that the Pi can see the PWM HAT:**

```bash
i2cdetect -y 1
```
You should see **40** somewhere in the grid. That's the PCA9685 chip's address.
- All dashes: the HAT isn't seated properly, or I2C isn't on. Re-seat the
  HAT with the power off, and recheck raspi-config.

**Check that the Pi can see the camera:**

```bash
rpicam-hello --list-cameras
```
You should see one camera listed, with a model name and resolutions.
- "No cameras available": with the Pi **powered off**, check the ribbon
  cable at both ends. The silver contacts must face the right way: on a
  Pi 4, toward the HDMI ports, with the blue strip facing the USB ports.
  Both latches must be pushed fully closed. Then power on and try again.

## Step 5: Copy the code to the Pi

In **PowerShell on your laptop** (not the SSH window), go to the folder
that contains `robot-car`, then copy it:

```powershell
cd "$HOME\Documents\School Projects\Capstone\Capstone_Fall_2026_VirtualRobotics_Team_5\vr-robot-controller"
scp -r robot-car USERNAME@picar.local:~/
```

This puts the folder at `~/robot-car` on the Pi. Whenever you change a file
on your laptop, run the same `scp` command again to update the Pi.

*(Alternative, once this folder is pushed to GitHub: on the Pi, run
`git clone https://github.com/MKVBII/Capstone_Fall_2026_VirtualRobotics_Team_5.git`,
then `git pull` to get updates.)*

---

## Test 1: Motors (wheels move)

1. **Turn on the car's battery switch.**
2. **Put the car on a block** so the wheels spin in the air.
3. On the Pi:
   ```bash
   cd ~/robot-car
   python3 motor_test.py
   ```
4. It prints `forward`, `backward`, `left`, `right`, `done`, with a short spin
   for each. **Ctrl+C** stops it at any time.

**Write down what happened on "forward":**
- [ ] The wheels really went forward.
- [ ] The wheels went backward.

The joystick driving code needs this answer to know which pin pattern means
forward.

| What you see | What it means |
|---|---|
| Prints, but nothing moves | The battery is off or flat. The Pi is fine. |
| Only one wheel moves | That motor's wires going into the driver board. |
| "left" spins the wrong wheel | Left and right are swapped. See the comment in `motor_test.py` under "ASSUMPTION WORTH CHECKING". |
| Error mentioning I2C or `busio` | Re-run `i2cdetect -y 1` (Step 4). |
| `No module named ...` | Re-run the install line from Step 3 that mentions that name. |

## Test 2: Camera in a laptop browser

1. On the Pi:
   ```bash
   cd ~/robot-car
   python3 camera_server.py
   ```
   It prints `Camera on: 640x480 at 15 fps`. Then, every 5 seconds, it prints
   `camera running: 15.0 frames/s, NN KB per frame`. That line means the camera
   is working, even before you open a browser.
   (A red "development server" warning also appears. It's normal; ignore it.)
2. On your laptop, open a browser and go to:
   ```
   http://picar.local:8000
   ```
   or `http://PI_IP:8000` using the IP from Step 2.
3. You should see live video. Wave a hand in front of the camera to judge
   the delay.
4. **Ctrl+C** in the SSH window stops it and releases the camera.

| What you see | What it means |
|---|---|
| Browser can't connect | Check that the laptop is on the same Wi-Fi, try the IP instead of `picar.local`, and check that `camera_server.py` is still running. |
| Page loads but the picture is blank | Look at the SSH window. If there are no "camera running" lines, the camera isn't delivering frames; re-check Step 4. |
| Picture is upside down | In `camera_server.py`, set `ROTATE_180 = True`, copy it over again (Step 5), and restart. |
| "Camera in use" / "Device busy" error | Another program has the camera. Stop it, or reboot. |
| Video is choppy or delayed | Check the Pi's CPU with `htop`, or move closer to the Wi-Fi router. Lowering `FRAMES_PER_SECOND` or `WIDTH, HEIGHT` in `camera_server.py` also helps. |

---

## Tips

- **Find the Pi's IP:** `hostname -I` on the Pi.
- **Shut down safely before switching the power off:** `sudo shutdown now`.
  Pulling the power while the Pi is running can corrupt the SD card.
- **Keep a program running even if SSH drops:** run `tmux` first, then
  start the program inside it. If you get disconnected, log back in and run
  `tmux attach` to get back to it.
- **See which Python libraries are installed:** `pip3 list`.

## What comes next (not built yet, on purpose)

Each step gets its own file(s) and its own test, after the previous one passes:

1. **Test 3: camera in the headset.** Serve the page over https (the Quest
   requires it for VR) and show the video on a floating screen in VR.
2. **Test 4: joystick driving.** Send the Quest thumbstick to the Pi over a
   WebSocket and drive the motors. It reuses `motor_test.py`'s exact pins,
   library (gpiozero) and 1000 Hz setting, plus the forward direction you
   recorded in Test 1.
