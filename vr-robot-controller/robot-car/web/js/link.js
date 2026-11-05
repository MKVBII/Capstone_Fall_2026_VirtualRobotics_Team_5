/*
  link.js - the WebSocket connection from a page to drive_server.py.

  Used by:  drive.js (as a "driver": sends the sticks), and the start
            screen and spectator view (as "viewers": only receive).
  Talks to: wss://PI_IP:8765 (drive_server.py). The port comes from
            camera_server.py's /config.json. A viewer on a plain http page
            uses the view-only ws://PI_IP:8766 instead, which needs no
            certificate (see VIEWER_PORT in drive_server.py).

  It reconnects by itself every second, times a ping once a second (the
  "Link" reading), and keeps the latest of each message type:
      link.robot     {"type":"robot", name, controls, shortcuts, sensors}
      link.readings  {"type":"readings", state, reverse_limit, source, sensors, ...}
      link.status    {"type":"status", cpu_temp_c, wifi_dbm, power_ok, logging, ...}
      link.ui        {"type":"ui", driver, in_mr, info_mode, help_open, ...}
                     what the headset is showing (for the spectator view)
  plus when each arrived, so stale data can be shown as stale.
*/

export class DriveLink {
  /**
   * @param {object} opts
   * @param {"driver"|"viewer"} opts.role  viewers can't drive, and their
   *   leaving doesn't stop the car
   * @param {number} opts.port   drive_server.py's port (CONFIG.drive_port)
   * @param {number} [opts.viewerPort]  its view-only port (CONFIG.viewer_port),
   *   used by viewers on http pages
   * @param {function(object)} [opts.onMessage]  called with every message
   */
  constructor({ role, port, viewerPort, onMessage }) {
    this.role = role;
    this.port = port;
    this.viewerPort = viewerPort;
    this.onMessage = onMessage || (() => {});
    this.ws = null;
    this.robot = null;       this.robotAt = 0;
    this.readings = null;    this.readingsAt = 0;
    this.status = null;      this.statusAt = 0;
    this.ui = null;          // what the headset shows (from the driver)
    this.linkMs = null;      // last round-trip time, ms
    this.everOpened = false; // has it ever connected? (for "connection lost")
    this.connect();
    setInterval(() => this.send({ type: "ping", t: performance.now() }), 1000);
  }

  /** Open the WebSocket; reopen it a second after it closes. */
  connect() {
    const plain = this.role === "viewer" && location.protocol === "http:" && this.viewerPort;
    this.url = plain ? "ws://" + location.hostname + ":" + this.viewerPort
                     : "wss://" + location.hostname + ":" + this.port;
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => { this.everOpened = true; ws.send(JSON.stringify({ type: "hello", role: this.role })); };
    ws.onclose = () => { this.linkMs = null; setTimeout(() => this.connect(), 1000); };
    ws.onerror = () => {};                       // onclose handles it
    ws.onmessage = (event) => this.receive(event);
  }

  /** Store one message from drive_server.py and pass it on. */
  receive(event) {
    let m;
    try { m = JSON.parse(event.data); } catch (e) { return; }
    const now = performance.now();
    if (m.type === "robot") { this.robot = m; this.robotAt = now; }
    else if (m.type === "readings") { this.readings = m; this.readingsAt = now; }
    else if (m.type === "status") { this.status = m; this.statusAt = now; }
    else if (m.type === "ui") this.ui = m;
    else if (m.type === "pong" && typeof m.t === "number") this.linkMs = Math.round(now - m.t);
    this.onMessage(m);
  }

  /** @returns {boolean} true while connected */
  get open() { return !!this.ws && this.ws.readyState === WebSocket.OPEN; }

  /** Send a message (an object) if connected. */
  send(msg) { if (this.open) this.ws.send(JSON.stringify(msg)); }

  /** @returns {boolean} true if a readings message arrived in the last second */
  get readingsFresh() { return !!this.readings && performance.now() - this.readingsAt < 1000; }

  /** @returns {boolean} true if a status message arrived in the last 3 seconds */
  get statusFresh() { return !!this.status && performance.now() - this.statusAt < 3000; }
}

/** Read camera_server.py's /config.json (picture size and ports). */
export async function loadConfig() {
  return fetch("/config.json").then(r => r.json());
}
