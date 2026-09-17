#!/usr/bin/env python3
"""Holds a WebSocket open, receives control values and commands from the
Quest headset, applies universal signal conditioning (mapping.py), and
calls whichever robot driver is currently active. Protocol is documented
in docs/message_contract.md.

The active driver is chosen at runtime, not hardcoded — see
driver_registry.py. On startup no driver is selected; the Quest page's
menu screen asks for the list of available robots (`listRobots`) and
picks one (`selectRobot`) before any control message does anything. This
is the "menu screen on bootup" / "swap robots for a fast demo" mechanism:
switching robots is a WebSocket round-trip, not a restart.

Run: python3 server.py
Config: see config.example.json (copy to config.json and edit).
"""
import asyncio
import json
import logging
import time

import websockets

import driver_registry
from mapping import condition_axis, HeadYawSmoother

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pi-server")

HOST = "0.0.0.0"
PORT = 8765
WATCHDOG_TIMEOUT_S = 0.3   # stop the robot if no message arrives within this window
STATUS_PUSH_HZ = 5         # how often to push RobotStatus back to the client


class ControllerServer:
    def __init__(self):
        self.available_drivers = driver_registry.discover()
        self.active_driver = None       # a RobotDriver instance, or None until selected
        self.active_driver_id = None
        self.head_smoother = HeadYawSmoother()
        self.last_message_time = 0.0
        self.connected_client = None

    # ---- connection lifecycle ----------------------------------------

    async def handle_connection(self, websocket):
        log.info("Client connected: %s", websocket.remote_address)
        self.connected_client = websocket
        self.last_message_time = time.monotonic()
        await self._send_robot_list(websocket)
        try:
            async for raw in websocket:
                await self._handle_message(websocket, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            log.info("Client disconnected — stopping robot")
            self._stop_active_driver()
            if self.connected_client is websocket:
                self.connected_client = None

    # ---- message handling ---------------------------------------------

    async def _handle_message(self, websocket, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Dropped malformed message: %r", raw[:100])
            return

        msg_type = msg.get("type")

        if msg_type == "control":
            self._handle_control(msg)
        elif msg_type == "listRobots":
            self.available_drivers = driver_registry.discover()  # pick up newly-uploaded files
            await self._send_robot_list(websocket)
        elif msg_type == "selectRobot":
            await self._handle_select_robot(websocket, msg.get("id"))
        elif msg_type == "command":
            await self._handle_command(websocket, msg.get("name"), msg.get("kwargs", {}))
        else:
            log.warning("Unknown message type: %r", msg_type)

    def _handle_control(self, msg: dict) -> None:
        if self.active_driver is None:
            return  # no robot selected yet — ignore control input rather than error

        x = condition_axis(float(msg.get("x", 0.0)))
        y = condition_axis(float(msg.get("y", 0.0)))
        z = condition_axis(float(msg.get("z", 0.0)))
        yaw = condition_axis(float(msg.get("yaw", 0.0)))
        head_yaw = float(msg.get("headYaw", 0.0))

        self.active_driver.set_axes(x, y, z, yaw)
        self.active_driver.set_camera_yaw(self.head_smoother.update(head_yaw))

        self.last_message_time = time.monotonic()

    async def _handle_select_robot(self, websocket, driver_id) -> None:
        info = self.available_drivers.get(driver_id)
        if info is None:
            await websocket.send(json.dumps({
                "type": "robotSelected", "id": driver_id, "ok": False, "error": "unknown_driver",
            }))
            return

        self._stop_active_driver()
        if self.active_driver is not None:
            try:
                self.active_driver.shutdown()
            except Exception as e:
                log.error("Error shutting down previous driver: %s", e)

        try:
            self.active_driver = info.instantiate()
            self.active_driver_id = driver_id
            log.info("Active robot switched to %r (%s)", driver_id, info.display_name)
            await websocket.send(json.dumps({
                "type": "robotSelected", "id": driver_id, "ok": True,
                "supportedCommands": self.active_driver.supported_commands(),
            }))
        except Exception as e:
            log.error("Failed to initialize driver %r: %s", driver_id, e)
            self.active_driver = None
            self.active_driver_id = None
            await websocket.send(json.dumps({
                "type": "robotSelected", "id": driver_id, "ok": False, "error": str(e),
            }))

    async def _handle_command(self, websocket, name, kwargs) -> None:
        if self.active_driver is None:
            result = {"ok": False, "error": "no_robot_selected"}
        else:
            try:
                result = self.active_driver.command(name, **(kwargs or {}))
            except Exception as e:
                log.error("Driver command %r raised: %s", name, e)
                result = {"ok": False, "error": str(e)}
        await websocket.send(json.dumps({"type": "commandResult", "name": name, **result}))

    async def _send_robot_list(self, websocket) -> None:
        await websocket.send(json.dumps({
            "type": "robots",
            "robots": [info.to_dict() for info in self.available_drivers.values()],
            "activeRobotId": self.active_driver_id,
        }))

    def _stop_active_driver(self) -> None:
        if self.active_driver is not None:
            try:
                self.active_driver.stop()
            except Exception as e:
                log.error("Error stopping active driver: %s", e)

    # ---- background loops ----------------------------------------------

    async def watchdog_loop(self):
        """Independent of the connection handler on purpose — see
        docs/architecture.md: a hung or buggy code path elsewhere should
        never be able to suppress this."""
        while True:
            await asyncio.sleep(0.05)
            idle_for = time.monotonic() - self.last_message_time
            if (self.connected_client is not None and self.active_driver is not None
                    and idle_for > WATCHDOG_TIMEOUT_S):
                log.warning("No control message for %.2fs — stopping robot", idle_for)
                self._stop_active_driver()

    async def status_push_loop(self):
        while True:
            await asyncio.sleep(1.0 / STATUS_PUSH_HZ)
            if self.connected_client is None or self.active_driver is None:
                continue
            status = self.active_driver.get_status()
            payload = json.dumps({
                "type": "status",
                "batteryVoltage": status.battery_voltage,
                "obstacleDistanceM": status.obstacle_distance_m,
                "lineTrackingSensors": status.line_tracking_sensors,
                "connected": status.connected,
                "extra": status.extra,
            })
            try:
                await self.connected_client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                pass


async def main():
    server = ControllerServer()
    log.info("Discovered %d driver(s): %s", len(server.available_drivers), list(server.available_drivers))

    async with websockets.serve(server.handle_connection, HOST, PORT):
        log.info("Listening on ws://%s:%d", HOST, PORT)
        await asyncio.gather(
            server.watchdog_loop(),
            server.status_push_loop(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
