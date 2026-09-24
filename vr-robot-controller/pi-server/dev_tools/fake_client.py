#!/usr/bin/env python3
"""Stands in for the Quest headset over the WebSocket protocol, from a
plain terminal. No Quest, no Pi, no robot — this is the fastest way to
demo (or debug) the full control loop end to end using only a laptop.

Pairs with drivers/sim_driver.py: run server.py in one terminal, this in
another, and you can drive the simulated robot through exactly the
protocol described in docs/message_contract.md, live, in front of anyone.

Usage:
    python3 dev_tools/fake_client.py                  # connects to ws://localhost:8765
    python3 dev_tools/fake_client.py ws://PI_IP:8765   # point at a real server elsewhere

Once connected it will:
  1. Print the robot list the server reports (via listRobots).
  2. Select the first available driver automatically (sim_driver, if present).
  3. Send a few seconds of varying control values, so you can watch
     server.py's logs and the driver's own print()s react live.
  4. Fire the driver's first supported command, if it has one.
  5. Print every `status` push the server sends back, the whole time.

This intentionally has no dependency on quest-client/ or a browser — it
only speaks the JSON-over-WebSocket contract, the same one the real
Quest page uses, so it's a legitimate way to prove the server side of
the architecture works before any headset or hardware is in the room.

Implementation note: a WebSocket connection only has one incoming
stream, and `status` pushes can arrive at any time interleaved with the
replies we're waiting for (robots/robotSelected/commandResult) — so a
single background task reads everything, prints status pushes as they
arrive, and hands anything else to the main coroutine through a queue.
"""
import asyncio
import json
import math
import sys
import time

import websockets

DEFAULT_URL = "ws://localhost:8765"


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"[fake_client] connecting to {url} ...")

    async with websockets.connect(url) as ws:
        replies = asyncio.Queue()
        reader_task = asyncio.create_task(_read_loop(ws, replies))

        robots = await replies.get()
        print(f"[fake_client] server says available robots: {robots}")

        robot_list = robots.get("robots", [])
        if not robot_list:
            print("[fake_client] no drivers discovered on the server — is drivers/ empty? exiting.")
            reader_task.cancel()
            return

        # Prefer sim_driver for a hardware-free demo, otherwise take the first one.
        chosen = next((r for r in robot_list if r["id"] == "sim_driver"), robot_list[0])
        print(f"[fake_client] selecting robot: {chosen['id']} ({chosen['displayName']})")
        await ws.send(json.dumps({"type": "selectRobot", "id": chosen["id"]}))
        selected = await replies.get()
        print(f"[fake_client] selectRobot response: {selected}")
        if not selected.get("ok"):
            print("[fake_client] selection failed, exiting.")
            reader_task.cancel()
            return

        print("[fake_client] sending ~5s of varying control input (watch server.py's terminal) ...")
        start = time.monotonic()
        while time.monotonic() - start < 5.0:
            t = time.monotonic() - start
            await ws.send(json.dumps({
                "type": "control",
                "x": 0.0,
                "y": math.sin(t * 2) * 0.6,   # forward/back sweep
                "z": 0.0,
                "yaw": math.cos(t * 2) * 0.4,  # turn sweep
                "headYaw": 0.0,
                "t": t,
            }))
            await asyncio.sleep(0.05)  # ~20 Hz, matching the real client's throttle

        commands = selected.get("supportedCommands") or []
        if commands:
            name = commands[0]
            print(f"[fake_client] firing command: {name}")
            await ws.send(json.dumps({"type": "command", "name": name, "kwargs": {}}))
            result = await replies.get()
            print(f"[fake_client] commandResult: {result}")

        await asyncio.sleep(1.0)  # let a couple more status pushes print via the reader task

        print("[fake_client] sending stop (zeroed control) and disconnecting")
        await ws.send(json.dumps({"type": "control", "x": 0, "y": 0, "z": 0, "yaw": 0, "headYaw": 0, "t": 0}))
        await asyncio.sleep(0.2)
        reader_task.cancel()


async def _read_loop(ws, replies: asyncio.Queue):
    """Reads every incoming message. `status` pushes are printed
    immediately (they're unsolicited); everything else goes on the
    queue for main() to consume in request/response order."""
    try:
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "status":
                print(f"[fake_client] status: {msg}")
            else:
                await replies.put(msg)
    except asyncio.CancelledError:
        pass
    except websockets.ConnectionClosed:
        pass


if __name__ == "__main__":
    asyncio.run(main())
