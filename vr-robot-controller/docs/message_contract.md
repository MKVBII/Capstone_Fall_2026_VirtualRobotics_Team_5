# WebSocket Message Contract

The entire wire protocol between the Quest-side page and the Pi-side
server. This is the network-level half of the "universal" boundary (see
`docs/architecture.md` section 3 and `docs/adding_a_robot.md`) — it's
generic across any robot whose driver implements `RobotDriver`, wheeled
or flying, and doesn't change when a new robot is added.

Transport: a single WebSocket connection, one client at a time, JSON text
frames. No binary frames, no sub-protocols.

## Client → Server

### `control`

Sent by `quest-client/js/network.js`, throttled to ~20–30 messages/second
(not once per XR frame). Ignored server-side if no robot is currently
selected.

```json
{
  "type": "control",
  "x": 0.1,
  "y": -0.7,
  "z": 0.0,
  "yaw": 0.3,
  "headYaw": 15.2,
  "t": 172345.6
}
```

| Field | Type | Range | Meaning |
|---|---|---|---|
| `x` | float | -1.0 to 1.0 | Strafe / roll, raw (server applies deadzone/curve via `mapping.condition_axis`) |
| `y` | float | -1.0 to 1.0 | Forward-back / pitch, raw |
| `z` | float | -1.0 to 1.0 | Vertical / throttle, raw |
| `yaw` | float | -1.0 to 1.0 | Turn / yaw rate, raw |
| `headYaw` | float | degrees, relative to session start | Headset yaw, raw (server applies smoothing/clamping) |
| `t` | float | `performance.now()` at send time | Client-side timestamp, currently unused server-side; kept for future latency measurement |

See `docs/adding_a_robot.md` for the axis convention (Mode 2 RC/drone layout) and which axes a wheeled vs. flying robot typically uses.

### `listRobots`

Ask the server to (re-)scan `pi-server/drivers/` and report what's available. Sent automatically on connect, and whenever the Quest page's "Rescan drivers/" button is clicked — this is what lets a newly-uploaded driver file show up without restarting the server.

```json
{ "type": "listRobots" }
```

### `selectRobot`

Switch the active robot. The server stops and shuts down the previous driver (if any) before instantiating the new one.

```json
{ "type": "selectRobot", "id": "osoyoo_car_driver" }
```

### `command`

Fire a discrete, driver-specific action (arm, takeoff, land, ...). `kwargs` is passed through to the driver's `command()` method as keyword arguments.

```json
{ "type": "command", "name": "takeoff", "kwargs": {} }
```

## Server → Client

### `status`

Pushed by `pi-server/server.py`'s `status_push_loop()` at `STATUS_PUSH_HZ` (default 5/sec), whenever a client is connected and a robot is selected.

```json
{
  "type": "status",
  "batteryVoltage": 7.4,
  "obstacleDistanceM": 0.42,
  "lineTrackingSensors": [false, false, true, false, false],
  "connected": true,
  "extra": {}
}
```

| Field | Type | Meaning |
|---|---|---|
| `batteryVoltage` | float | Volts, 0 if the driver doesn't support reading it |
| `obstacleDistanceM` | float | Ultrasonic reading in meters, -1 if not available |
| `lineTrackingSensors` | bool[5] | Raw line-tracking array state, left to right |
| `connected` | bool | Whether the driver considers its hardware initialized |
| `extra` | object | Driver-specific telemetry not covered by the fields above (e.g. `{"altitudeM": 1.2}` for a drone). Rendered generically by the client. |

### `robots`

Sent in response to `listRobots`, and automatically right after connecting.

```json
{
  "type": "robots",
  "robots": [
    { "id": "osoyoo_car_driver", "displayName": "OSOYOO Pi Car", "description": "2-wheel differential drive rover, model 2020005500" }
  ],
  "activeRobotId": null
}
```

### `robotSelected`

Response to `selectRobot`.

```json
{ "type": "robotSelected", "id": "osoyoo_car_driver", "ok": true, "supportedCommands": [] }
```

On failure: `{ "type": "robotSelected", "id": "...", "ok": false, "error": "unknown_driver" }`.

### `commandResult`

Response to `command`.

```json
{ "type": "commandResult", "name": "takeoff", "ok": true }
```

## Design rules

1. A robot driver that can't fulfill part of the contract (no servo, no line sensors) still returns a `RobotStatus` with documented defaults — see `pi-server/robot_driver_base.py` — rather than the field being omitted. The client never needs per-robot logic to read this.
2. All control axes are normalized floats, not robot-native units (motor PWM ticks, raw encoder counts, SDK-specific velocity ranges). Unit conversion happens only inside the driver.
3. `control` messages are silently ignored (not an error) when no robot is selected — the client doesn't need to track selection state defensively before sending.
4. If this contract needs a breaking change later (new required field, changed range), bump a `protocolVersion` field rather than silently changing meaning — not needed yet since there's only ever one client and one server in this project, but worth remembering if that changes.
