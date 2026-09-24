# Sprint 1 demo — no robot, no Pi, no Quest required

Everything below runs on a single laptop with Python 3.9+ installed. It
proves the real architecture works — the same server code, the same
WebSocket protocol, the same driver-plugin mechanism the OSOYOO car and
future drone will use — without any physical hardware in the room.

## What you're demonstrating

1. The server auto-discovers robot "drivers" from files on disk (right
   now: the real OSOYOO car driver, plus `sim_driver.py`, a fake robot
   built for exactly this situation).
2. A client (today: a terminal script standing in for the Quest headset)
   asks for the robot list, picks one, and streams control input to it —
   the "menu screen on bootup" and "swap robots for a fast demo"
   mechanism, live.
3. The server pushes live status/telemetry back on a timer.
4. Discrete commands (e.g. a horn) round-trip through the same contract
   a drone's "takeoff"/"land" will later use.
5. A full automated test suite (`pytest`) backing all of the above.

## Setup (once)

```bash
git clone <your repo URL>
cd vr-robot-controller/pi-server
pip install -r requirements.txt      # only needs `websockets` for dev-machine use
```

(`RPi.GPIO` and the PCA9685 libraries in `requirements.txt` are commented
out — they're Pi-only and not needed to run this demo.)

## Running the demo (two terminals)

**Terminal 1 — start the server:**

```bash
cd pi-server
python3 server.py
```

**Terminal 2 — run the fake client:**

```bash
cd pi-server
python3 dev_tools/fake_client.py
```

Watch both terminals side by side. You'll see the fake client list the
available robots, select `sim_driver`, stream ~5 seconds of varying
control values, receive live status pushes (a slowly draining fake
battery, fake sensor readings), fire the driver's `honk` command, and
disconnect cleanly — and the server terminal logging each control update
and driver action as it happens.

## What this proves for sprint 1

- The WebSocket protocol (`docs/message_contract.md`) is implemented and
  working end to end, not just designed on paper.
- The driver-plugin system (`docs/architecture.md` section 3) really
  does let a robot be selected and driven without any per-robot code in
  the server — `sim_driver.py` and `osoyoo_car_driver.py` are both just
  files in `drivers/`, discovered the same way.
- The safety property (a broken driver can't take the server down) is
  covered by an automated test, not just a claim — see
  `tests/pi_server_tests/test_driver_registry.py`.
- The full test suite passes: run `pytest tests/pi_server_tests/ -v`
  from the repo root, or point at the CI badge once the repo is pushed
  to GitHub (`.github/workflows/tests.yml` runs this on every push).

## What this does NOT prove yet (be upfront about this in the presentation)

This demo never touches GPIO, a camera, or real motors — it's proof the
*software architecture* is solid, not proof the car drives. The honest
framing for sprint 1: "the control pipeline, protocol, and plugin system
are built and tested; hardware bring-up on the physical OSOYOO car is
the next sprint's work." See `docs/architecture.md` section 7 for the
full roadmap and section 8 for what's still an open decision.
