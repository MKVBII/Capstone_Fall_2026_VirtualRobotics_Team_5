# archive/early-tests/

The team's first connection tests from September 2026, kept for history. **None of these are used by the current code.** Each was replaced once the next step worked:

| File | What it proved | Replaced by |
|---|---|---|
| `https_server.py` | The Quest opens an https page served by the Pi (WebXR needs https) | `robot-car/camera_server.py` (same port, 8443) |
| `connection_test.py` + `wstest.html` | A WebSocket message gets from the Quest to the Pi and back | `robot-car/drive_server.py` (same port, 8765) + the headset page |
| `joystick_control.html` | The Quest's thumbsticks can be read and sent 25 times a second | `robot-car/web/pages/drive.html` + `web/js/drive.js` |
| `NOTES.md` | The original instructions for running these tests | `robot-car/SETUP.md` |

Moved here from `testing/`, `server/` and `vr-robot-controller/vr/` on 2026-11-05. Git keeps the full history of the old locations.
