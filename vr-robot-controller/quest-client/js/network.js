/**
 * WebSocket client to the Pi's pi-server/server.py. Protocol is documented
 * in docs/message_contract.md. This file's only job: open the socket,
 * reconnect with backoff if it drops, throttle outgoing control messages
 * to a fixed rate (not once per XR frame — that would flood the link),
 * and hand incoming messages to callbacks. It has no robot-specific logic
 * — the robot list, selection, and commands are all generic passthrough.
 */
class RobotConnection {
  constructor(url, {
    sendHz = 25,
    onStatus = null,
    onStateChange = null,
    onRobotList = null,
    onRobotSelected = null,
    onCommandResult = null,
  } = {}) {
    this.url = url;
    this.sendIntervalMs = 1000 / sendHz;
    this.onStatus = onStatus;
    this.onStateChange = onStateChange;
    this.onRobotList = onRobotList;
    this.onRobotSelected = onRobotSelected;
    this.onCommandResult = onCommandResult;
    this.ws = null;
    this.lastSendTime = 0;
    this.reconnectDelayMs = 500;
    this._connect();
  }

  _connect() {
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.reconnectDelayMs = 500;
      this._setState("connected");
    };
    this.ws.onclose = () => {
      this._setState("disconnected");
      setTimeout(() => this._connect(), this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 1.5, 5000);
    };
    this.ws.onerror = () => {
      // onclose fires right after in the browser WebSocket API; nothing extra needed here.
    };
    this.ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        console.warn("Dropped malformed message from server", event.data);
        return;
      }
      switch (msg.type) {
        case "status":
          if (this.onStatus) this.onStatus(msg);
          break;
        case "robots":
          if (this.onRobotList) this.onRobotList(msg.robots, msg.activeRobotId);
          break;
        case "robotSelected":
          if (this.onRobotSelected) this.onRobotSelected(msg);
          break;
        case "commandResult":
          if (this.onCommandResult) this.onCommandResult(msg);
          break;
        default:
          console.warn("Unknown message type from server:", msg.type);
      }
    };
  }

  _setState(state) {
    if (this.onStateChange) this.onStateChange(state);
  }

  _sendJson(obj) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  /** Call every XR frame; internally throttled to sendHz. Ignored
   * server-side if no robot is currently selected. */
  sendControl({ x, y, z, yaw, headYaw }) {
    const now = performance.now();
    if (now - this.lastSendTime < this.sendIntervalMs) return;
    if (this._sendJson({ type: "control", x, y, z, yaw, headYaw, t: now })) {
      this.lastSendTime = now;
    }
  }

  /** Ask the server to (re-)scan drivers/ and report what's available —
   * this is what lets a newly-uploaded driver file show up in the menu
   * without restarting the server. */
  requestRobotList() {
    this._sendJson({ type: "listRobots" });
  }

  /** Switch the active robot. Response arrives via onRobotSelected. */
  selectRobot(id) {
    this._sendJson({ type: "selectRobot", id });
  }

  /** Fire a discrete, robot-specific command (e.g. "takeoff"). Response
   * arrives via onCommandResult. */
  sendCommand(name, kwargs = {}) {
    this._sendJson({ type: "command", name, kwargs });
  }
}
