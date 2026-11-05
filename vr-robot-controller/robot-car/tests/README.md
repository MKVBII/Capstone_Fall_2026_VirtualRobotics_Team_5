# tests/

Hardware and self-tests for the robot car. Run everything from `~/robot-car` on the Pi.

| Command | Checks | Needs |
|---|---|---|
| `python3 tests/motor_test.py` | Each wheel spins forward, backward, left, right | Car **on a block**, battery on |
| `python3 hardware/rear_sensor.py --selftest` | The rear-sensor rules (slow/stop/edge/fault) with made-up numbers | Nothing (runs on a laptop too) |
| `python3 hardware/rear_sensor.py --fake --log` | The live test loop with made-up readings | Nothing |
| `python3 hardware/rear_sensor.py` | Both rear sensors, live | Car on the floor |
| `python3 hardware/camera_pan.py` | Camera servo: centre, left, centre, right | Car battery on |
| `python3 hardware/pi_status.py` | Pi temperature, load, Wi-Fi, power once a second | Nothing |
| `python3 drive_server.py --dry-run --fake-sensor` | The control server with no motors and no sensors | `cert.pem`/`key.pem` (made by `camera_server.py`) |

Test one layer at a time: if a test fails, the problem is in the one new thing it adds. The full step-by-step order is in `../SETUP.md`.

## Website and headset

Run `camera_server.py` and `drive_server.py --dry-run --fake-sensor`, then open the pages in a browser:
`/` (start + session log), `/begin`, `/settings`, `/spectator`, `/about`. The headset page needs the
Quest (or Meta's Quest emulator in a desktop browser) to enter mixed reality.
