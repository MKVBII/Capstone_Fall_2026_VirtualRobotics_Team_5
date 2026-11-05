/*
  drive.js - everything the headset page does.

  Runs in:    the Meta Quest 3 browser (pages/drive.html loads it)
  Talks to:   camera_server.py  /stream       the camera pictures (MJPEG)
                                /config.json  picture size and port numbers
              drive_server.py   wss://PI_IP:8765  sticks out, readings back

  WHAT IT DOES
    1. Video:     reads the camera stream and draws the newest picture onto
                  the <canvas id="video">, which is also the texture on the
                  floating screen in mixed reality.
    2. Controls:  25 times a second, sends the thumbsticks (and the camera
                  pan angle) to drive_server.py over a WebSocket. If those
                  messages stop, drive_server.py stops the car by itself.
    3. Readings:  receives the rear sensors (10x/s) and Pi health (1x/s)
                  from drive_server.py and shows them: status tags, the
                  dashboard / strip, the screen border colour, beeps and
                  controller vibration.
    4. Head-look: optionally turns the camera servo with your head.
    5. 3D scene:  builds the floating screen with three.js and runs the
                  mixed-reality session.

  CONTROLLER BUTTONS
    Left stick    forward / back          Right stick   turn
    A (right)     info: off -> dashboard below the video -> strip across
                  the top of the video -> off
    X (left)      head-look on/off
    Grip          bring the screen back in front of you (and, with
                  head-look on, make this direction "straight ahead")
    Meta button   leave mixed reality (the car stops)

  Sections below follow that order. Settings you might change are at the
  top of the first section.
*/

import * as THREE from "three";

// Picture size and port numbers come from camera_server.py, so they're set
// in ONE place (its SETTINGS section). Top-level `await` is allowed here
// because this file is a module.
const CONFIG = await fetch("/config.json").then(r => r.json());

// =============================================================================
// SETTINGS - values you might want to change
// =============================================================================

// --- The floating screen ---
const PANEL_WIDTH = 1.6;     // screen width, metres
const PANEL_DISTANCE = 1.8;  // how far in front of you it appears, metres
const PANEL_DROP = 0.1;      // how far below eye level, metres (more comfortable)
const VIDEO_W = CONFIG.video_width, VIDEO_H = CONFIG.video_height;

// --- Joysticks ---
const DRIVE_PORT = CONFIG.drive_port;   // drive_server.py listens here
const SEND_HZ = 25;                     // stick messages per second to the car
const DEADZONE = 0.12;                  // ignore tiny stick wobble near centre
const CURVE = 2.0;                      // fine control near centre, full at the edge

// --- Head-look (camera servo follows your head; see hardware/camera_pan.py) ---
const PAN_LIMIT = 70;          // degrees each way; same as camera_pan.py
const HEAD_DEADZONE = 4;       // head turns smaller than this leave the camera centred
const HEAD_SMOOTHING = 0.15;   // 0..1 per frame. Lower = smoother, but more lag
const SCREEN_FOLLOW = 0.08;    // how quickly the screen swings round after you

// --- Readings ---
const DISTANCE_UNITS = "in";   // "in" or "cm" for the rear sensor
const REAR_SHOW_CM = 150;      // farther than this, just say "REAR CLEAR"

// --- Colours (status tags, dashboard, 2D pill) ---
const GREEN = "#34c759", AMBER = "#ffcc00", RED = "#ff453a", GREY = "#8e8e93";
const WHITE = "#f1f3f4";
const REAR_COLOR = { clear: GREEN, slow: AMBER, stop: RED, edge: RED, fault: GREY };

// --- Page elements (pages/drive.html) ---
const videoCanvas = document.getElementById("video");
videoCanvas.width = VIDEO_W;
videoCanvas.height = VIDEO_H;
const videoCtx = videoCanvas.getContext("2d");
const btn = document.getElementById("enter");
const msg = document.getElementById("msg");
const rearBox = document.getElementById("rear");
const info2d = document.getElementById("info2d");


// =============================================================================
// 1. VIDEO - receive the camera stream and draw the newest picture
// =============================================================================
// camera_server.py's /stream sends, forever:
//     "--frame", headers including "Content-Length: N", a blank line,
//     then N bytes of JPEG.
// We cut out each JPEG and draw it onto videoCanvas.

const videoTexture = new THREE.CanvasTexture(videoCanvas);
videoTexture.colorSpace = THREE.SRGBColorSpace;
videoTexture.generateMipmaps = false;
videoTexture.minFilter = THREE.LinearFilter;
// ^ Sharper: the screen shows about one video pixel per headset pixel, so
//   skip the blurrier pre-shrunk copies ("mipmaps") 3D engines usually make.
//   Also less work per frame, which helps latency.

let lastFrameAt = 0;                  // when the last picture was drawn (ms)
let framesDrawn = 0, videoFps = 0;    // pictures shown in the last second
setInterval(() => { videoFps = framesDrawn; framesDrawn = 0; }, 1000);
let newest = null;                    // newest JPEG not yet drawn (a Blob)
let drawing = false;                  // is drawNewest() already running?

/**
 * Decode and draw the newest JPEG, then any that arrived meanwhile.
 * Only ever draws the NEWEST picture: if two arrive while one is being
 * decoded, the older one is skipped, so the video never falls behind.
 */
async function drawNewest() {
  drawing = true;
  while (newest) {
    const jpeg = newest; newest = null;
    try {
      const bitmap = await createImageBitmap(jpeg);
      videoCtx.drawImage(bitmap, 0, 0, videoCanvas.width, videoCanvas.height);
      bitmap.close();
      videoTexture.needsUpdate = true;
      lastFrameAt = performance.now();
      framesDrawn++;
    } catch (e) { /* a damaged frame - just skip it */ }
  }
  drawing = false;
}

/**
 * Find the blank line (\r\n\r\n) that ends a part's headers.
 * @param {Uint8Array} bytes
 * @returns {number} its position, or -1 if it hasn't arrived yet
 */
function headerEnd(bytes) {
  for (let i = 0; i + 3 < bytes.length; i++)
    if (bytes[i] === 13 && bytes[i+1] === 10 && bytes[i+2] === 13 && bytes[i+3] === 10) return i;
  return -1;
}

/** Join two byte arrays into a new one. */
function join(a, b) {
  const c = new Uint8Array(a.length + b.length); c.set(a); c.set(b, a.length); return c;
}

/**
 * Read /stream forever, handing each complete JPEG to drawNewest().
 * Reconnects every second if the Pi or the Wi-Fi drops.
 */
async function readStream() {
  for (;;) {
    try {
      const res = await fetch("/stream", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const reader = res.body.getReader();
      let buf = new Uint8Array(0);
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf = join(buf, value);
        for (;;) {                                      // every complete picture in buf
          const end = headerEnd(buf);
          if (end < 0) break;
          const headers = new TextDecoder().decode(buf.subarray(0, end));
          const m = /Content-Length:\s*(\d+)/i.exec(headers);
          const start = end + 4;
          if (!m) { buf = buf.subarray(start); continue; }
          const len = parseInt(m[1], 10);
          if (buf.length < start + len) break;          // rest still arriving
          newest = new Blob([buf.slice(start, start + len)], { type: "image/jpeg" });
          buf = buf.subarray(start + len);
          if (!drawing) drawNewest();
        }
      }
    } catch (e) { /* fall through and retry */ }
    await new Promise(r => setTimeout(r, 1000));
  }
}
readStream();


// =============================================================================
// 2. CONTROLS - the joystick link to drive_server.py
// =============================================================================
// A secure WebSocket (wss://) to the Pi. While in mixed reality, the
// thumbsticks are sent 25 times a second (see the animation loop in
// section 5). drive_server.py stops the car by itself if they stop arriving.
//
// Messages SENT to drive_server.py:
//   {"lx", "ly", "rx", "ry", "pan"}   sticks (-1..1) + camera angle (degrees)
//   {"type": "ping", "t"}             once a second, to measure the link delay

let ws = null;
let lastSent = 0;            // when the sticks were last sent (ms)

/** Open the WebSocket, and reopen it every second whenever it closes. */
function connectDrive() {
  ws = new WebSocket("wss://" + location.hostname + ":" + DRIVE_PORT);
  ws.onclose = () => setTimeout(connectDrive, 1000);   // keep retrying
  ws.onerror = () => {};                               // onclose handles it
  ws.onmessage = onDriveMessage;                       // readings coming back (section 3)
}

// Once a second, time a round trip to drive_server.py (the "Link" reading).
setInterval(() => {
  if (controlsOn()) ws.send(JSON.stringify({ type: "ping", t: performance.now() }));
}, 1000);
connectDrive();

/** @returns {boolean} true if the link to drive_server.py is open */
function controlsOn() { return ws && ws.readyState === WebSocket.OPEN; }

/** Send one message to drive_server.py, if the link is open. */
function sendSticks(msg) {
  if (controlsOn()) ws.send(JSON.stringify(msg));
}

/**
 * Deadzone + curve for one stick axis.
 * Values inside DEADZONE become 0; the rest is rescaled to 0..1 and raised
 * to CURVE, which gives fine control near the centre and full power at the edge.
 * @param {number} value  raw axis, -1..1
 * @returns {number} shaped axis, -1..1
 */
function condition(value) {
  const sign = Math.sign(value), magnitude = Math.abs(value);
  if (magnitude < DEADZONE) return 0;
  return sign * Math.pow((magnitude - DEADZONE) / (1 - DEADZONE), CURVE);
}

/**
 * Read both thumbsticks.
 * Quest thumbsticks are axes[2] (x) and axes[3] (y). Pushing forward is
 * NEGATIVE y; drive_server.py flips it. A sleeping controller counts as centred.
 * @param {XRSession} session
 * @returns {{lx:number, ly:number, rx:number, ry:number}}
 */
function readSticks(session) {
  let lx = 0, ly = 0, rx = 0, ry = 0;
  for (const source of session.inputSources) {
    const pad = source.gamepad;
    if (!pad || pad.axes.length < 4) continue;
    if (source.handedness === "left")  { lx = condition(pad.axes[2]); ly = condition(pad.axes[3]); }
    if (source.handedness === "right") { rx = condition(pad.axes[2]); ry = condition(pad.axes[3]); }
  }
  return { lx, ly, rx, ry };
}


// =============================================================================
// 3. READINGS - messages from drive_server.py, and the warnings they trigger
// =============================================================================
// Messages RECEIVED from drive_server.py:
//   {"type":"rear", cm, back_state, down_cm, floor_cm, down_state,
//    state, reverse_limit, source, left_pct, right_pct}                10x/s
//      cm, back_state       BACK sensor (obstacles); null if switched off
//      down_cm, floor_cm,   DOWN sensor (edges): reading, floor baseline,
//      down_state           state; null if switched off
//      state, reverse_limit the two sensors combined (see hardware/rear_sensor.py)
//      source               "back" / "down": which sensor set the state
//      left_pct, right_pct  what the wheels are actually being told
//   {"type":"status", cpu_temp_c, cpu_load_pct, wifi_dbm, power_ok,
//    power_warned, throttled, pan_deg, ...}                            1x/s
//   {"type":"pong", t}                                                 reply to our ping

let rear = null, rearAt = 0;        // latest "rear" message, and when it arrived
let status = {}, statusAt = 0;      // latest "status" message, and when it arrived
let linkMs = null;                  // last measured round-trip time, ms
let lastSticks = { lx: 0, ly: 0, rx: 0, ry: 0 };   // last sticks sent (for the warnings)

/** Handle one message from drive_server.py. */
function onDriveMessage(event) {
  let m;
  try { m = JSON.parse(event.data); } catch (e) { return; }
  if (m.type === "rear") {
    rear = m; rearAt = performance.now();
    const [text, color] = rearLabel();
    rearBox.textContent = text; rearBox.style.background = color;
  } else if (m.type === "status") {
    status = m; statusAt = performance.now();
  } else if (m.type === "pong" && typeof m.t === "number") {
    linkMs = Math.round(performance.now() - m.t);
  }
}

/** @returns {boolean} true if a rear reading arrived in the last second */
function rearFresh() { return rear && performance.now() - rearAt < 1000; }

/** Format a distance in DISTANCE_UNITS, e.g. "4.5 in" or "11 cm". */
function showDistance(cm) {
  return DISTANCE_UNITS === "in" ? (cm / 2.54).toFixed(1) + " in" : Math.round(cm) + " cm";
}

/**
 * The rear-sensor text and colour, used by the 3D tag, the dashboard and
 * the 2D pill.
 * @returns {[string, string]} [text, colour]
 */
function rearLabel() {
  if (!rearFresh())           return ["REAR: NO DATA", GREY];
  if (rear.state === "edge")  return ["EDGE BEHIND!", RED];
  if (rear.state === "fault")                                   // say which sensor
    return [rear.source === "down" ? "EDGE SENSOR ?" : "REAR SENSOR ?", GREY];
  if (rear.cm == null || rear.cm >= REAR_SHOW_CM) return ["REAR CLEAR", REAR_COLOR[rear.state]];
  // ^ The BACK sensor points straight back, so its distance is always worth
  //   showing - unless nothing is in range, or it's switched off (null).
  return ["REAR " + showDistance(rear.cm), REAR_COLOR[rear.state]];
}

/**
 * The DOWN (floor) sensor as a dashboard row.
 * @returns {[string, string, string] | null} [label, value, colour], or
 *   null if there's no fresh reading or the sensor is switched off
 */
function floorRow() {
  if (!rearFresh() || rear.down_state == null) return null;
  const s = rear.down_state;
  return ["Floor", s === "edge" ? "EDGE!" : s === "fault" ? "?" : "OK",
          s === "edge" ? RED : s === "fault" ? GREY : GREEN];
}

// --- Parking-sensor warnings, only while the stick is pulled BACK ---
// Beeps (Web Audio API, built into the browser) that speed up as the gap
// closes, plus a controller buzz when reversing is blocked.
let audio = null;        // AudioContext; created by the Enter button (browsers need a tap first)
let nextBeep = 0;        // earliest time the next beep may play (ms)

/** Play a short tone. @param {number} freq Hz  @param {number} ms length */
function beep(freq, ms) {
  if (!audio) return;
  const osc = audio.createOscillator(), gain = audio.createGain();
  osc.frequency.value = freq; gain.gain.value = 0.15;
  osc.connect(gain).connect(audio.destination);
  osc.start(); osc.stop(audio.currentTime + ms / 1000);
}

/**
 * Vibrate both controllers (WebXR controllers are ordinary Gamepads).
 * Both hands, since some Quest browser versions route vibration to the wrong one.
 * @param {XRSession} session  @param {number} strength 0..1  @param {number} ms
 */
function buzz(session, strength, ms) {
  for (const source of session.inputSources) {
    const h = source.gamepad && source.gamepad.hapticActuators &&
              source.gamepad.hapticActuators[0];
    if (h && h.pulse) h.pulse(strength, ms);
  }
}

/**
 * Beep / buzz according to the rear sensors. Called every frame.
 * Slow: beeps that speed up as reverse is limited more. Stop / edge / fault:
 * fast beeps (low for an edge) plus a buzz.
 * @param {XRSession} session  @param {number} time  frame time, ms
 */
function rearWarnings(session, time) {
  const reversing = lastSticks.ly > 0.05;        // Quest: pulling back = positive
  if (!rearFresh() || !reversing || time < nextBeep) return;
  if (rear.state === "slow") {
    beep(880, 60);
    nextBeep = time + 120 + 600 * rear.reverse_limit;   // closer = faster
  } else if (rear.state !== "clear") {               // stop / edge / fault
    beep(rear.state === "edge" ? 440 : 1320, 100);
    buzz(session, 0.8, 100);
    nextBeep = time + 150;
  }
}


// =============================================================================
// 4. HEAD-LOOK AND BUTTONS
// =============================================================================
// Head-look off: camera straight ahead, screen stays put in the room.
// Head-look on:  turning your head turns the camera, up to PAN_LIMIT each
// way, and the screen swings round smoothly to stay in front of you. Small
// head movements (HEAD_DEADZONE) are ignored and the angle is smoothed, so
// the picture doesn't jitter - jitter and lag are what make people queasy.

let headLook = false;    // is head-look on?
let refYaw = 0;          // the head direction that counts as "straight ahead", radians
let panNow = 0;          // smoothed camera angle being sent, degrees (+ = right)
let frameCount = 0, displayFps = 0;   // headset frames drawn in the last second
setInterval(() => { displayFps = frameCount; frameCount = 0; }, 1000);

/**
 * Which way the head faces, left/right only.
 * @param {XRViewerPose} pose
 * @returns {number} radians, + = left
 */
function yawOf(pose) {
  const o = pose.transform.orientation;
  const f = new THREE.Vector3(0, 0, -1)
    .applyQuaternion(new THREE.Quaternion(o.x, o.y, o.z, o.w));
  return Math.atan2(-f.x, -f.z);
}

/**
 * Move panNow a step toward where the camera should point: the head's turn
 * from refYaw (if head-look is on and past the deadzone), else straight ahead.
 * @param {XRViewerPose|null} pose
 */
function updatePan(pose) {
  let target = 0;
  if (headLook && pose) {
    let turned = (yawOf(pose) - refYaw) * 180 / Math.PI;
    turned = ((turned + 540) % 360) - 180;          // keep it in -180..180
    const right = -turned;                           // camera angles: + = right
    if (Math.abs(right) >= HEAD_DEADZONE)
      target = Math.max(-PAN_LIMIT, Math.min(PAN_LIMIT, right));
  }
  panNow += (target - panNow) * HEAD_SMOOTHING;      // ease toward it
}

// Buttons react once per press, not on every frame they're held.
const wasDown = {};      // button key -> was it down last frame?

/**
 * @returns {boolean} true on the first frame a button is pressed
 * @param {XRInputSource} source  @param {number} index  gamepad button index
 * @param {string} key  a name to remember this button by
 */
function pressedOnce(source, index, key) {
  const b = source.gamepad && source.gamepad.buttons[index];
  const down = !!(b && b.pressed);
  const fresh = down && !wasDown[key];
  wasDown[key] = down;
  return fresh;
}

/**
 * Handle A (info panels) and X (head-look). On Quest controllers
 * buttons[4] is A on the right hand and X on the left.
 * @param {XRSession} session  @param {XRViewerPose|null} pose
 */
function readButtons(session, pose) {
  for (const source of session.inputSources) {
    if (source.handedness === "right" && pressedOnce(source, 4, "A")) cycleInfo();
    if (source.handedness === "left" && pressedOnce(source, 4, "X") && pose) {
      headLook = !headLook;
      refYaw = yawOf(pose);                          // "straight ahead" = where you look now
    }
  }
}


// =============================================================================
// 5. THE 3D SCENE - floating screen, tags, info panels, animation loop
// =============================================================================

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x000000, 0);           // see-through = your real room
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType("local");
renderer.xr.setFoveation(0);
// ^ Draw the whole view at full sharpness. By default the edges of your
//   view are drawn at lower resolution to save work ("foveation"), which
//   makes the screen look blurry whenever it isn't dead centre.
renderer.domElement.style.display = "none";    // only drawn inside the headset
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera();  // the headset controls this
const panelH = PANEL_WIDTH * VIDEO_H / VIDEO_W; // screen height, keeping the picture's shape
const screen = new THREE.Group();              // the screen and everything attached to it
scene.add(screen);

/**
 * A flat rectangle with rounded corners.
 * @param {number} w  width  @param {number} h  height  @param {number} r  corner radius (metres)
 * @returns {THREE.ShapeGeometry}
 */
function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);         s.lineTo(x + w - r, y);     s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);     s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);         s.quadraticCurveTo(x, y, x + r, y);
  return new THREE.ShapeGeometry(s);
}

// The bezel: a dark frame behind the picture. Its colour turns amber/red
// when something is behind the car (see the animation loop).
const bezel = new THREE.Mesh(roundedRect(PANEL_WIDTH + 0.06, panelH + 0.06, 0.03),
  new THREE.MeshBasicMaterial({ color: 0x0b0d10, transparent: true, opacity: 0.92 }));
bezel.position.z = -0.005;                     // just behind the picture
screen.add(bezel);

// The picture itself.
screen.add(new THREE.Mesh(new THREE.PlaneGeometry(PANEL_WIDTH, panelH),
  new THREE.MeshBasicMaterial({ map: videoTexture, toneMapped: false })));

/**
 * Make a small status tag under the screen: a coloured dot and a word,
 * drawn on a canvas and shown as a texture.
 * @param {number} x  left/right position under the screen, metres
 * @returns {function(string, string)} set(text, colour); only redraws when they change
 */
function makeTag(x) {
  const canvas = Object.assign(document.createElement("canvas"), { width: 512, height: 64 });
  const ctx = canvas.getContext("2d");
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.05),
    new THREE.MeshBasicMaterial({ map: texture, transparent: true, toneMapped: false }));
  mesh.position.set(x, -panelH / 2 - 0.07, 0);
  screen.add(mesh);

  let current = "";
  return function set(text, color) {
    if (text + color === current) return;      // only redraw when it changes
    current = text + color;
    ctx.clearRect(0, 0, 512, 64);
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(24, 32, 10, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#e8eaed";
    ctx.font = "600 32px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 46, 34);
    texture.needsUpdate = true;
  };
}
const setTag = makeTag(-PANEL_WIDTH / 2 + 0.2);         // left:   LIVE / NO VIDEO
const setControlTag = makeTag(PANEL_WIDTH / 2 - 0.2);   // right:  CONTROLS ON / OFF
const setRearTag = makeTag(0);                          // centre: rear sensors

// --- Info panels -------------------------------------------------------------
// Press A to cycle: off -> DASHBOARD below the video -> STRIP across the top
// of the video -> off. Each is a canvas redrawn 4x a second and shown as a
// texture, the same trick as the tags above.
//
// Why BELOW the video: head-look follows left/right head turns only, so
// glancing DOWN (like at a car's dashboard) never moves the camera or the
// screen. Panels at the sides couldn't be read with head-look on: turning
// to look at them swung the screen - and them - away.
let infoMode = 0;                                    // 0 off, 1 dashboard, 2 strip

// Dashboard size/position - change these if it's too low, too small, etc.
const DASH_W = PANEL_WIDTH;                          // as wide as the video
const DASH_H = 0.5;                                  // metres
const DASH_TILT = 0.45;                              // radians tipped back to face you
const DASH_FORWARD = 0.3;                            // metres closer to you than the video

/**
 * Make an info panel: a canvas shown on a flat rectangle, hidden at first.
 * @param {number} w  @param {number} h  size in metres
 * @param {number} cw @param {number} ch canvas size in pixels
 * @returns {{canvas, ctx, texture, mesh}}
 */
function makePanel(w, h, cw, ch) {
  const canvas = Object.assign(document.createElement("canvas"), { width: cw, height: ch });
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();   // crisper when tilted
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
    new THREE.MeshBasicMaterial({ map: texture, transparent: true, toneMapped: false }));
  mesh.visible = false;
  screen.add(mesh);
  return { canvas, ctx: canvas.getContext("2d"), texture, mesh };
}
const dash = makePanel(DASH_W, DASH_H, 1600, 500);
dash.mesh.position.set(0, -panelH / 2 - 0.12 - DASH_H / 2, DASH_FORWARD);  // under the tags
dash.mesh.rotation.x = -DASH_TILT;                   // top leans away, faces up at you
const strip = makePanel(PANEL_WIDTH * 0.96, 0.12, 1920, 144);
strip.mesh.position.set(0, panelH / 2 - 0.08, 0.01); // across the top of the video

/** A button: show the next info mode (off -> dashboard -> strip -> off). */
function cycleInfo() {
  infoMode = (infoMode + 1) % 3;
  dash.mesh.visible = infoMode === 1;
  strip.mesh.visible = infoMode === 2;
  drawInfo();
}

// Each reading below is a row: [label, value text, colour]. Missing readings
// are left out, so a robot that sends e.g. altitude_m or speed_mps in its
// status message gets those rows too.

/** Green below okBelow, amber below warnBelow, otherwise red. */
function level(v, okBelow, warnBelow) { return v < okBelow ? GREEN : v < warnBelow ? AMBER : RED; }

/** @returns {boolean} true if a status message arrived in the last 3 seconds */
function statusFresh() { return performance.now() - statusAt < 3000; }

/** The rear reading shortened for big text ("4.5 in", "CLEAR", "EDGE!"). */
function rearBig() {
  const [text, color] = rearLabel();
  return [text.replace("REAR: ", "").replace("REAR ", "").replace("EDGE BEHIND!", "EDGE!"), color];
}

/** How much reverse is allowed: "OK", "52%" or "BLOCKED". */
function reverseRow() {
  if (!rearFresh()) return ["Reverse", "?", GREY];
  const lim = rear.reverse_limit;
  return ["Reverse", lim === 0 ? "BLOCKED" : lim < 1 ? Math.round(lim * 100) + "%" : "OK",
          lim === 0 ? RED : lim < 1 ? AMBER : GREEN];
}

/** Dashboard middle column: floor, wheels, robot motion, camera, head-look. */
function driveRows() {
  const rows = [];
  const floor = floorRow();
  if (floor) rows.push(floor);
  if (rearFresh()) rows.push(["Wheels", rear.left_pct + " / " + rear.right_pct + "%", WHITE]);
  if (statusFresh() && status.speed_mps != null)   rows.push(["Speed", status.speed_mps.toFixed(2) + " m/s", WHITE]);
  if (statusFresh() && status.altitude_m != null)  rows.push(["Altitude", status.altitude_m.toFixed(1) + " m", WHITE]);
  if (statusFresh() && status.heading_deg != null) rows.push(["Heading", Math.round(status.heading_deg) + "°", WHITE]);
  const pan = Math.round(panNow);
  rows.push(["Camera", pan === 0 ? "ahead" : Math.abs(pan) + "° " + (pan > 0 ? "R" : "L"), WHITE]);
  rows.push(["Head-look (X)", headLook ? "ON" : "off", headLook ? GREEN : GREY]);
  return rows;
}

/**
 * Dashboard right column: video, link and Pi health, most important first
 * (the column shows at most 6 rows). Pi load only appears when it's 80%+.
 */
function systemRows() {
  const rows = [];
  const live = performance.now() - lastFrameAt < 1000;
  rows.push(["Video", live ? videoFps + " fps" : "NONE", !live ? RED : videoFps < 8 ? RED : videoFps < 15 ? AMBER : GREEN]);
  rows.push(["Link", !controlsOn() ? "OFF" : linkMs === null ? "..." : linkMs + " ms",
             !controlsOn() ? RED : linkMs === null ? GREY : level(linkMs, 150, 300)]);
  if (statusFresh()) {
    if (status.power_ok === false) rows.push(["Power", "LOW!", RED]);
    else if (status.power_warned)  rows.push(["Power", "dipped", AMBER]);
    else if (status.power_ok)      rows.push(["Power", "OK", GREEN]);
    if (status.battery_v != null)  rows.push(["Battery", status.battery_v.toFixed(2) + " V", WHITE]);
    if (status.wifi_dbm != null)   rows.push(["Wi-Fi", status.wifi_dbm + " dBm", level(-status.wifi_dbm, 67, 75)]);
    if (status.cpu_temp_c != null) rows.push(["Pi temp", Math.round(status.cpu_temp_c) + " °C", level(status.cpu_temp_c, 70, 80)]);
    if (status.throttled) rows.push(["Pi", "THROTTLED", AMBER]);
    if (status.cpu_load_pct != null && status.cpu_load_pct >= 80)   // only when it's a problem
      rows.push(["Pi load", status.cpu_load_pct + "%", level(status.cpu_load_pct, 80, 100)]);
  } else {
    rows.push(["Pi", "no data", GREY]);
  }
  return rows;
}

/** Draw up to 6 rows: label on the left at x0, value on the right at x1. */
function drawRows(ctx, rows, x0, x1) {
  rows.slice(0, 6).forEach(([label, value, color], i) => {
    const y = 66 + i * 76;
    ctx.textAlign = "left";  ctx.fillStyle = "#b8bcc2"; ctx.font = "500 40px system-ui, sans-serif";
    ctx.fillText(label, x0, y);
    ctx.textAlign = "right"; ctx.fillStyle = color;     ctx.font = "700 46px system-ui, sans-serif";
    ctx.fillText(value, x1, y);
  });
}

/** Redraw the dashboard: big rear reading (left), driveRows, systemRows. */
function drawDash() {
  const { ctx, canvas } = dash;
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "rgba(11, 13, 16, 0.9)";
  ctx.beginPath(); ctx.roundRect(0, 0, W, H, 36); ctx.fill();
  ctx.textBaseline = "middle";

  // Left: the rear sensor, as big as possible - the thing you need at a glance.
  const [big, bigColor] = rearBig();
  const [, revText, revColor] = reverseRow();
  ctx.textAlign = "center";
  ctx.fillStyle = "#b8bcc2"; ctx.font = "600 40px system-ui, sans-serif";
  ctx.fillText("REAR", 250, 66);
  let size = 130;                                    // shrink long words to fit the box
  do { ctx.font = "800 " + size + "px system-ui, sans-serif"; size -= 6; }
  while (ctx.measureText(big).width > 440 && size > 40);
  ctx.fillStyle = bigColor;
  ctx.fillText(big, 250, 230);
  ctx.fillStyle = revColor; ctx.font = "700 50px system-ui, sans-serif";
  ctx.fillText("Reverse " + revText, 250, 400);

  // Column dividers.
  ctx.fillStyle = "rgba(255, 255, 255, 0.12)";
  ctx.fillRect(500, 30, 3, H - 60); ctx.fillRect(1050, 30, 3, H - 60);

  drawRows(ctx, driveRows(), 540, 1010);
  drawRows(ctx, systemRows(), 1090, W - 40);
  dash.texture.needsUpdate = true;
}

/** The few readings worth showing ON the video, for strip mode. */
function stripItems() {
  const [big, bigColor] = rearBig();
  const keep = (rows, labels) => rows.filter(r => labels.includes(r[0]));
  return [["Rear", big, bigColor], reverseRow(),
          ...keep(systemRows(), ["Video", "Link", "Power"])];
}

/** Redraw the strip, shrinking the text until everything fits on one line. */
function drawStrip() {
  const { ctx, canvas } = strip;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "rgba(11, 13, 16, 0.75)";
  ctx.beginPath(); ctx.roundRect(0, 0, canvas.width, canvas.height, 28); ctx.fill();
  ctx.textBaseline = "middle"; ctx.textAlign = "left";
  const items = stripItems();
  // Measure everything first, shrinking the text until it all fits.
  let scale = 1, widths, total;
  const labelFont = () => "500 " + Math.round(40 * scale) + "px system-ui, sans-serif";
  const valueFont = () => "800 " + Math.round(52 * scale) + "px system-ui, sans-serif";
  for (;;) {
    widths = items.map(([label, value]) => {
      ctx.font = labelFont(); const lw = ctx.measureText(label).width + 14 * scale;
      ctx.font = valueFont(); return [lw, lw + ctx.measureText(value).width];
    });
    total = widths.reduce((sum, w) => sum + w[1], 0);
    if (total + 40 * (items.length - 1) <= canvas.width - 60 || scale < 0.6) break;
    scale -= 0.05;
  }
  const gap = (canvas.width - 60 - total) / Math.max(1, items.length - 1);
  let x = 30;
  items.forEach(([label, value, color], i) => {
    ctx.fillStyle = "#b8bcc2"; ctx.font = labelFont(); ctx.fillText(label, x, 74);
    ctx.fillStyle = color;     ctx.font = valueFont(); ctx.fillText(value, x + widths[i][0], 74);
    x += widths[i][1] + gap;
  });
  strip.texture.needsUpdate = true;
}

/** All readings as one line, for the 2D page (laptop / before entering MR). */
function compactLine() {
  return [["Rear", ...rearBig()], reverseRow(), ...driveRows(), ...systemRows()]
    .filter(r => !["Wheels", "Head-look (X)"].includes(r[0]));
}

/** Redraw whichever info panel is showing, plus the 2D line. Runs 4x a second. */
function drawInfo() {
  if (infoMode === 1) drawDash();
  if (infoMode === 2) drawStrip();
  info2d.textContent = compactLine().map(r => r[0] + " " + r[1]).join("  ·  ");
}
setInterval(drawInfo, 250);

// --- Screen placement --------------------------------------------------------
let needsPlacement = false;   // set by the grip button / entering MR

/**
 * Put the screen PANEL_DISTANCE in front of wherever you're looking
 * (left/right only - looking up or down doesn't tilt it).
 * @param {XRViewerPose} pose
 * @param {number} amount  1 = jump there; less than 1 = move that fraction
 *   of the way (used every frame by head-look, so the screen glides after you)
 */
function placeScreen(pose, amount = 1) {
  const p = pose.transform.position, o = pose.transform.orientation;
  const head = new THREE.Vector3(p.x, p.y, p.z);
  const forward = new THREE.Vector3(0, 0, -1)
    .applyQuaternion(new THREE.Quaternion(o.x, o.y, o.z, o.w));
  forward.y = 0;
  if (forward.lengthSq() < 1e-4) forward.set(0, 0, -1);
  forward.normalize();
  const target = head.clone().addScaledVector(forward, PANEL_DISTANCE);
  target.y = head.y - PANEL_DROP;
  screen.position.lerp(target, amount);
  screen.lookAt(head.x, screen.position.y, head.z);   // face you, upright
}

// --- The animation loop: runs once per headset frame (72-120 times a second) ---
renderer.setAnimationLoop((time, frame) => {
  if (!renderer.xr.isPresenting) return;
  frameCount++;
  const pose = frame ? frame.getViewerPose(renderer.xr.getReferenceSpace()) : null;

  // Screen placement and head-look.
  if (pose && needsPlacement) {
    placeScreen(pose); needsPlacement = false;
    refYaw = yawOf(pose);                            // re-centre head-look too
  }
  if (frame) readButtons(frame.session, pose);       // A / X buttons
  updatePan(pose);                                   // camera angle
  if (headLook && pose) placeScreen(pose, SCREEN_FOLLOW);   // screen follows you

  // Status tags under the screen.
  const live = performance.now() - lastFrameAt < 1000;
  setTag(live ? "LIVE" : "NO VIDEO", live ? "#34c759" : "#ff453a");
  setControlTag(controlsOn() ? "CONTROLS ON" : "CONTROLS OFF",
                controlsOn() ? "#34c759" : "#ff453a");

  // Send the sticks, at most SEND_HZ times a second.
  if (frame && time - lastSent >= 1000 / SEND_HZ) {
    lastSent = time;
    lastSticks = readSticks(frame.session);          // remembered for the warnings
    lastSticks.pan = Math.round(panNow);             // camera servo angle
    sendSticks(lastSticks);
  }

  // Rear sensors: centre tag, screen border colour, beeps / buzz.
  const [rearText, rearColor] = rearLabel();
  setRearTag(rearText, rearColor);
  const danger = rearFresh() && rear.state !== "clear";
  bezel.material.color.set(!danger ? 0x0b0d10 : rear.state === "slow" ? 0x6b5300 : 0x7f1d1d);
  if (frame) rearWarnings(frame.session, time);

  renderer.render(scene, camera);
});


// =============================================================================
// 6. THE "ENTER MIXED REALITY" BUTTON
// =============================================================================

/**
 * Check whether this browser can do mixed reality, then enable the button
 * or explain why not.
 */
async function checkSupport() {
  if (!window.isSecureContext) {
    // Browsers only allow mixed reality on "secure" pages. Plain http:// to
    // the Pi counts as secure only after the one-time Quest setting below.
    const https = "https://" + location.hostname + ":" + CONFIG.https_port + "/xr";
    btn.textContent = "Mixed reality blocked on http://";
    msg.innerHTML =
      "One-time Quest setting: open <code>chrome://flags</code>, search " +
      "<b>insecure</b>, set <b>Insecure origins treated as secure</b> to " +
      "<b>Enabled</b>, type <code>" + location.origin + "</code> in its box, " +
      "tap outside the box, then tap <b>Relaunch</b>. " +
      'Or use the https page: <a style="color:#8cf" href="' + https + '">' + https + "</a>";
    return;
  }
  if (!navigator.xr || !(await navigator.xr.isSessionSupported("immersive-ar"))) {
    btn.textContent = "Mixed reality not available here";
    msg.textContent = "Open this page in the Meta Quest browser to use mixed reality.";
    return;
  }
  btn.disabled = false;
  btn.textContent = "Enter mixed reality";
  msg.textContent = "The camera appears as a floating screen in your room. " +
    "Left stick: forward/back. Right stick: turn. " +
    "A: info panels. X: head-look (camera follows your head). " +
    "Squeeze a grip button to bring the screen back in front of you. " +
    "Press the Meta button on the right controller to leave (the car stops).";
}

// Start the mixed-reality session. Leaving it (Meta button) re-centres the
// camera and sends all-zero sticks, so the car stops.
btn.addEventListener("click", async () => {
  audio = audio || new AudioContext();               // sound needs a tap to start
  audio.resume();
  try {
    const session = await navigator.xr.requestSession("immersive-ar");
    session.addEventListener("squeeze", () => { needsPlacement = true; });
    session.addEventListener("end", () => {
      headLook = false; panNow = 0;                 // camera back to centre
      sendSticks({ lx: 0, ly: 0, rx: 0, ry: 0, pan: 0 });   // leaving = stop the car
      btn.disabled = false; btn.textContent = "Enter mixed reality";
    });
    await renderer.xr.setSession(session);
    needsPlacement = true;
    btn.disabled = true; btn.textContent = "In mixed reality";
  } catch (e) {
    msg.textContent = "Couldn't start mixed reality: " + e.message;
  }
});

checkSupport();
