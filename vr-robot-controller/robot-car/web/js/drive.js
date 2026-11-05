/*
  drive.js - the headset page: begin screen in 2D, driving in mixed reality.

  Runs in:    the Meta Quest 3 browser (pages/drive.html loads it)
  Talks to:   camera_server.py  /stream        camera pictures (MJPEG)
                                /config.json   picture size and port numbers
                                /api/settings  saved settings (js/settings.js)
              drive_server.py   wss://PI_IP:8765 (js/link.js): sticks out,
                                robot info + readings + status back

  WHAT IT DOES
    1. Video:      reads the camera stream and draws the newest picture onto
                   <canvas id="video">, which is also the texture on the
                   floating screen in mixed reality.
    2. Begin screen (2D): live checklist, controller drawing, Enter button
                   (warns first if a check is red).
    3. Controls:   25 times a second, sends the thumbsticks and the camera
                   pan angle. drive_server.py stops the car by itself if those
                   messages stop. While the settings panel is open, the
                   sticks are sent as zero: the robot stops.
    4. The 3D scene: the floating screen, status tags, alert banner,
                   dashboard / strip, quick-button bar, settings panel, help card.
    5. Pointer:    point either controller at a button or panel and pull the
                   trigger. The ray only shows when it's on something clickable.
    6. Buttons:    A / B / X / Y run the shortcuts chosen in Settings (for the
                   car: X = head-look, A = dashboard), unless the robot uses them.
    7. Alerts:     banner, screen border colour, beeps and controller buzz,
                   all from js/readings.js alertFor().

  Settings (screen size, units, beeps...) live in js/settings.js and apply
  as soon as they change.
*/

import * as THREE from "three";
import { DriveLink, loadConfig } from "./link.js";
import { SCHEMA, loadSettings, saveSettings, applyScheme, clampNumber, defaults } from "./settings.js";
import { palette, alertFor, cardsFor, limitText, checklistFor, defaultCards } from "./readings.js";
import { drawDashboard, drawBanner, drawStrip, bigReading, levelColor } from "./hud.js";
import { controlsFor, controllerSVG, resolveShortcuts, freeButtons } from "./controls.js";
import { drawQuickBar, drawSettingsPanel, drawHelpCard, cycle, SHORTCUT_IDS } from "./panels.js";

// Picture size and ports come from camera_server.py; settings from the Pi.
// Top-level `await` is allowed here because this file is a module.
const CONFIG = await loadConfig();
let settings = await loadSettings();
applyScheme(settings);

// =============================================================================
// FIXED VALUES (things that aren't user settings)
// =============================================================================
const BASE_WIDTH = 1.6;       // screen width the layout below is designed for, metres
const SEND_HZ = 25;           // stick messages per second to the robot
const VIDEO_W = CONFIG.video_width, VIDEO_H = CONFIG.video_height;
const PANEL_H = BASE_WIDTH * VIDEO_H / VIDEO_W;   // screen height at BASE_WIDTH, keeping the picture's shape
const TEXT_SCALE = { small: 0.85, normal: 1, large: 1.2 };

// Page elements (pages/drive.html).
const videoCanvas = document.getElementById("video");
videoCanvas.width = VIDEO_W;
videoCanvas.height = VIDEO_H;
const videoCtx = videoCanvas.getContext("2d");
const btn = document.getElementById("enter");
const msg = document.getElementById("msg");

// Page-side state.
let headLook = false;      // camera follows your head?
let wantHeadLookRef = false; // set "straight ahead" on the next frame (needs the head pose)
let refYaw = 0;            // head direction that counts as "straight ahead", radians
let panNow = 0;            // smoothed camera angle being sent, degrees (+ = right)
let infoMode = 0;          // 0 off, 1 dashboard, 2 strip
let settingsOpen = false;  // settings panel showing (robot paused)
let helpOpen = false;      // help card showing
let settingsTab = "Display", settingsPage = 0;
let cardPage = 0;          // which page of reading cards the dashboard shows
let needsPlacement = false;// put the screen in front of you on the next frame


// =============================================================================
// 1. VIDEO - receive the camera stream and draw the newest picture
// =============================================================================
// camera_server.py's /stream sends, forever: "--frame", headers including
// "Content-Length: N", a blank line, then N bytes of JPEG. We cut out each
// JPEG and draw it onto videoCanvas.

const videoTexture = new THREE.CanvasTexture(videoCanvas);
videoTexture.colorSpace = THREE.SRGBColorSpace;
videoTexture.generateMipmaps = false;
videoTexture.minFilter = THREE.LinearFilter;
// ^ Sharper: the screen shows about one video pixel per headset pixel, so
//   skip the blurrier pre-shrunk copies ("mipmaps") 3D engines usually make.

let lastFrameAt = 0;                  // when the last picture was drawn (ms)
let framesDrawn = 0, videoFps = 0;    // pictures shown in the last second
setInterval(() => { videoFps = framesDrawn; framesDrawn = 0; }, 1000);
let newest = null;                    // newest JPEG not yet drawn (a Blob)
let drawing = false;                  // is drawNewest() already running?

/** @returns {boolean} true if a picture arrived in the last second */
function videoLive() { return performance.now() - lastFrameAt < 1000; }

/**
 * Decode and draw the newest JPEG, then any that arrived meanwhile.
 * Only ever draws the NEWEST picture, so the video never falls behind.
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

/** Position of the blank line (\r\n\r\n) that ends a part's headers, or -1. */
function headerEnd(bytes) {
  for (let i = 0; i + 3 < bytes.length; i++)
    if (bytes[i] === 13 && bytes[i+1] === 10 && bytes[i+2] === 13 && bytes[i+3] === 10) return i;
  return -1;
}

/** Join two byte arrays into a new one. */
function join(a, b) {
  const c = new Uint8Array(a.length + b.length); c.set(a); c.set(b, a.length); return c;
}

/** Read /stream forever, handing each JPEG to drawNewest(). Reconnects every second. */
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
// 2. THE LINK TO drive_server.py, AND THE BEGIN SCREEN
// =============================================================================

const link = new DriveLink({ role: "driver", port: CONFIG.drive_port, onMessage: (m) => {
  if (m.type === "robot") { drawControls(); redrawPanels(); }
}});
let linkWasOpen = false;   // for "Connection lost" (only after it has worked once)

/** Page-side values the readings functions need. */
function local() {
  return { videoFps, videoLive: videoLive(), pan: panNow, headLook };
}

/** The begin screen's checklist, redrawn twice a second. */
function drawChecklist() {
  const rows = checklistFor(link, local(), settings.units);
  document.getElementById("checklist").innerHTML = rows.map(r => `
    <li><span class="dot ${r.level}"></span><span>${r.label}</span><span class="value">${r.value}</span>
    ${r.level !== "ok" ? `<span class="fix">${r.fix}</span>` : ""}</li>`).join("");
  document.getElementById("robot-name").textContent = link.robot
    ? `Driving: ${link.robot.name}` : link.open ? "Connected, waiting for the robot..." : "Can't reach drive_server.py yet";
}
setInterval(drawChecklist, 500);

/** The begin screen's controller drawings and numbered lists. */
function drawControls() {
  const c = controlsFor(link.robot, settings.shortcuts);
  const list = (items) => items.map(i =>
    `<li class="${i.label === "Not used" ? "unused" : ""}"><b>${i.name}</b> ${i.label}</li>`).join("");
  document.getElementById("controls").innerHTML = `
    <div class="controller"><h3>Left controller</h3>${controllerSVG("left")}<ol>${list(c.left)}</ol></div>
    <div class="controller"><h3>Right controller</h3>${controllerSVG("right")}<ol>${list(c.right)}</ol></div>`;
}
drawControls();


// =============================================================================
// 3. CONTROLS - sticks and buttons
// =============================================================================
let lastSent = 0;          // when the sticks were last sent (ms)
let lastSticks = { lx: 0, ly: 0, rx: 0, ry: 0 };   // last sticks sent (for the warnings)

/**
 * Deadzone + curve for one stick axis (Settings: stick dead zone / curve).
 * Inside the dead zone = 0; the rest is rescaled to 0..1 and raised to the
 * curve: fine control near the centre, full power at the edge.
 */
function condition(value) {
  const dz = settings.stick_deadzone, curve = settings.stick_curve;
  const sign = Math.sign(value), magnitude = Math.abs(value);
  if (magnitude < dz) return 0;
  return sign * Math.pow((magnitude - dz) / (1 - dz), curve);
}

/**
 * Read both thumbsticks, with the settings applied (invert, speed limit).
 * Quest thumbsticks are axes[2] (x) and axes[3] (y); pushing forward is
 * NEGATIVE y (drive_server.py flips it). A sleeping controller = centred.
 */
function readSticks(session) {
  let lx = 0, ly = 0, rx = 0, ry = 0;
  for (const source of session.inputSources) {
    const pad = source.gamepad;
    if (!pad || pad.axes.length < 4) continue;
    if (source.handedness === "left")  { lx = condition(pad.axes[2]); ly = condition(pad.axes[3]); }
    if (source.handedness === "right") { rx = condition(pad.axes[2]); ry = condition(pad.axes[3]); }
  }
  const limit = settings.speed_limit / 100;      // can only lower the robot's own limits
  if (settings.invert_throttle) ly = -ly;
  if (settings.invert_turn) rx = -rx;
  return { lx: lx * limit, ly: ly * limit, rx: rx * limit, ry: ry * limit };
}

// Buttons react once per press, not on every frame they're held.
const wasDown = {};
function pressedOnce(source, index, key) {
  const b = source.gamepad && source.gamepad.buttons[index];
  const down = !!(b && b.pressed);
  const fresh = down && !wasDown[key];
  wasDown[key] = down;
  return fresh;
}

/**
 * A / B / X / Y: run that button's shortcut. Quest controllers: buttons[4]
 * is A (right) / X (left), buttons[5] is B (right) / Y (left). Buttons the
 * robot uses itself are sent to it in the stick message instead.
 * @returns {object} robot buttons held right now, e.g. {a: true}
 */
function readButtons(session) {
  const shortcuts = resolveShortcuts(link.robot, settings.shortcuts);
  const robotButtons = new Set(((link.robot && link.robot.controls) || []).map(c => c.input));
  const held = {};
  for (const source of session.inputSources) {
    if (!source.gamepad) continue;
    const names = source.handedness === "right" ? ["a", "b"] : source.handedness === "left" ? ["x", "y"] : [];
    names.forEach((name, i) => {
      const index = 4 + i;
      if (robotButtons.has(name)) { const b = source.gamepad.buttons[index]; held[name] = !!(b && b.pressed); return; }
      if (pressedOnce(source, index, name) && shortcuts[name]) runAction(shortcuts[name]);
    });
  }
  return held;
}

// --- Live controls on the help card -----------------------------------------
// While the help card is open, whatever you press or move lights up on it.
let liveInputs = { pressed: new Set(), sticks: {} };
let liveKey = "";

/**
 * What's being pressed or moved right now on each controller.
 * Quest buttons: [0] trigger, [1] grip, [4] A / X, [5] B / Y.
 * @returns {{pressed: Set<string>, sticks: object}} e.g. pressed has
 *   "left:stick", "right:a"; sticks.left = [x, y] from -1 to 1
 */
function readLiveInputs(session) {
  const pressed = new Set(), sticks = {};
  for (const source of session.inputSources) {
    const pad = source.gamepad, hand = source.handedness;
    if (!pad || (hand !== "left" && hand !== "right")) continue;
    const down = (i) => !!(pad.buttons[i] && pad.buttons[i].pressed);
    if (down(0)) pressed.add(hand + ":trigger");
    if (down(1)) pressed.add(hand + ":grip");
    if (down(4)) pressed.add(hand + (hand === "left" ? ":x" : ":a"));
    if (down(5)) pressed.add(hand + (hand === "left" ? ":y" : ":b"));
    if (pad.axes.length >= 4) {
      const x = pad.axes[2], y = pad.axes[3];
      sticks[hand] = [x, y];
      if (Math.hypot(x, y) > 0.15) pressed.add(hand + ":stick");
    }
  }
  return { pressed, sticks };
}

/** Every frame while the help card is open: redraw it if anything changed. */
function updateLiveInputs(session) {
  liveInputs = readLiveInputs(session);
  const round = (v) => Math.round(v * 10);   // ignore tiny stick wobble
  const key = [...liveInputs.pressed].sort().join() + "|" +
    Object.entries(liveInputs.sticks).map(([h, [x, y]]) => h + round(x) + "," + round(y)).join();
  if (key !== liveKey) { liveKey = key; redrawPanels(); sendUi(); }
}

/** Do one headset action (from a shortcut button or the quick-button bar). */
function runAction(action) {
  if (action === "headlook") { headLook = !headLook; wantHeadLookRef = true; }
  else if (action === "dashboard") { infoMode = (infoMode + 1) % 3; }
  else if (action === "recenter") { needsPlacement = true; }
  else if (action === "help") { helpOpen = !helpOpen; if (helpOpen) settingsOpen = false; }
  else if (action === "settings") { settingsOpen = !settingsOpen; if (settingsOpen) helpOpen = false; settingsPage = 0; }
  layout(); redrawPanels(); sendUi();
}

// --- Head-look ---------------------------------------------------------------
/** Which way the head faces, left/right only: radians, + = left. */
function yawOf(pose) {
  const o = pose.transform.orientation;
  const f = new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(o.x, o.y, o.z, o.w));
  return Math.atan2(-f.x, -f.z);
}

/** Move panNow a step toward where the camera should point. */
function updatePan(pose) {
  let target = 0;
  if (headLook && pose) {
    let turned = (yawOf(pose) - refYaw) * 180 / Math.PI;
    turned = ((turned + 540) % 360) - 180;          // keep it in -180..180
    const right = -turned;                           // camera angles: + = right
    if (Math.abs(right) >= settings.headlook_deadzone)
      target = Math.max(-settings.headlook_limit, Math.min(settings.headlook_limit, right));
  }
  panNow += (target - panNow) * settings.headlook_smoothing;
}


// =============================================================================
// 4. THE 3D SCENE
// =============================================================================

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x000000, 0);           // see-through = your real room
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType("local");
renderer.xr.setFoveation(0);                   // full sharpness everywhere (no blurry edges)
renderer.domElement.style.display = "none";    // only drawn inside the headset
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera();  // the headset controls this
const screen = new THREE.Group();              // the screen and everything attached to it
scene.add(screen);

/** A flat rounded rectangle, w x h metres, corner radius r. */
function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);         s.lineTo(x + w - r, y);     s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);     s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);         s.quadraticCurveTo(x, y, x + r, y);
  return new THREE.ShapeGeometry(s);
}

// The bezel (frame) behind the picture; tints amber / red with alerts.
const bezel = new THREE.Mesh(roundedRect(BASE_WIDTH + 0.06, PANEL_H + 0.06, 0.03),
  new THREE.MeshBasicMaterial({ color: 0x0b0d10, transparent: true, opacity: 0.92 }));
bezel.position.z = -0.005;
screen.add(bezel);
screen.add(new THREE.Mesh(new THREE.PlaneGeometry(BASE_WIDTH, PANEL_H),
  new THREE.MeshBasicMaterial({ map: videoTexture, toneMapped: false })));

/**
 * A canvas shown on a flat panel attached to the screen.
 * @param {number} w @param {number} h  size in metres
 * @param {number} cw @param {number} ch canvas size in pixels
 * @returns {{canvas, ctx, texture, mesh, hits: Array}}  hits = its clickable areas
 */
function makePanel(w, h, cw, ch, { visible = true, order = 1 } = {}) {
  const canvas = Object.assign(document.createElement("canvas"), { width: cw, height: ch });
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();   // crisper when tilted
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
    new THREE.MeshBasicMaterial({ map: texture, transparent: true, toneMapped: false, depthTest: order < 5 }));
  mesh.visible = visible;
  mesh.renderOrder = order;
  screen.add(mesh);
  return { canvas, ctx: canvas.getContext("2d"), texture, mesh, hits: [] };
}

// Small status tags under the screen: a coloured dot and a word.
function makeTag(x) {
  const p = makePanel(0.4, 0.05, 512, 64);
  p.mesh.position.set(x, -PANEL_H / 2 - 0.07, 0);
  let current = "";
  return function set(text, color) {
    const key = text + color + settings.headset_theme;
    if (key === current) return;                // only redraw when it changes
    current = key;
    const ctx = p.ctx; ctx.clearRect(0, 0, 512, 64);
    ctx.fillStyle = color; ctx.beginPath(); ctx.arc(24, 32, 10, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#e8eaed"; ctx.font = "600 32px system-ui, sans-serif"; ctx.textBaseline = "middle";
    ctx.fillText(text, 46, 34);
    p.texture.needsUpdate = true;
  };
}
const setTag = makeTag(-BASE_WIDTH / 2 + 0.2);          // left:   LIVE / NO VIDEO
const setControlTag = makeTag(BASE_WIDTH / 2 - 0.2);    // right:  CONTROLS ON / OFF
const setRearTag = makeTag(0);                          // centre: nearest distance / edge

// The rest: banner, strip, quick-button bar, dashboard, settings panel, help card.
const banner = makePanel(1.4, 0.11, 1400, 110, { visible: false, order: 3 });
const strip = makePanel(BASE_WIDTH * 0.96, 0.12, 1920, 144, { visible: false, order: 2 });
const bar = makePanel(0.88, 0.12, 1100, 150);
const dash = makePanel(1.6, 0.52, 1600, 520, { visible: false });
const settingsPanel = makePanel(1.4, 0.9625, 1600, 1100, { visible: false, order: 6 });
const help = makePanel(0.88, 1.12, 1100, 1400, { visible: false, order: 6 });   // tall card beside the screen
bar.mesh.position.set(0, -PANEL_H / 2 - 0.17, 0.02);
settingsPanel.mesh.position.set(0, 0, 0.12);
let bannerShow = 0;        // 0..1, eases in and out

/** Place / size everything from the settings (runs whenever they change). */
function layout() {
  screen.scale.setScalar(settings.screen_width / BASE_WIDTH);
  const s = settings.dashboard_size;
  dash.mesh.scale.setScalar(s);
  if (settings.dashboard_place === "below") {
    // Below the quick-button bar, tipped up toward you like a car dashboard.
    // Head-look follows left/right turns only, so glancing down never moves it.
    dash.mesh.position.set(0, -PANEL_H / 2 - 0.27 - 0.26 * s, 0.3);
    dash.mesh.rotation.set(-0.45, 0, 0);
  } else {
    const side = settings.dashboard_place === "left" ? -1 : 1;
    dash.mesh.position.set(side * (BASE_WIDTH / 2 + 0.85 * s), 0, 0.25);
    dash.mesh.rotation.set(0, -side * 0.5, 0);    // turned to face you
  }
  dash.mesh.visible = infoMode === 1;
  strip.mesh.visible = infoMode === 2 && !settingsOpen;   // would cover the panel's top edge
  strip.mesh.position.set(0, PANEL_H / 2 - 0.08, 0.01);
  settingsPanel.mesh.visible = settingsOpen;
  // The help card sits beside the screen (on the side away from the
  // dashboard), turned to face you, so the video stays clear and you can
  // try each control while reading what it does.
  const helpSide = settings.dashboard_place === "right" ? -1 : 1;
  help.mesh.position.set(helpSide * (BASE_WIDTH / 2 + 0.48), 0, 0.22);
  help.mesh.rotation.set(0, -helpSide * 0.45, 0);
  help.mesh.visible = helpOpen;
}
layout();

/** Theme colours for the 3D panels (Settings: headset panels + colours). */
function pal() { return palette(settings.headset_theme, settings.colour_scheme); }

// What the pointer is on: {panel, id} or null; each panel redraws with its hover.
let hovered = { bar: null, settings: null, help: null, dash: null };

/** Redraw the clickable panels (bar, settings, help) with the current state. */
function redrawPanels() {
  const p = pal();
  bar.hits = drawQuickBar(bar.ctx, { headLook, infoMode, settingsOpen, helpOpen }, p, hovered.bar);
  bar.texture.needsUpdate = true;
  if (settingsOpen) {
    settingsPanel.hits = drawSettingsPanel(settingsPanel.ctx, {
      tab: settingsTab, page: settingsPage, settings, robot: link.robot,
      shortcuts: resolveShortcuts(link.robot, settings.shortcuts) }, p, hovered.settings);
    settingsPanel.texture.needsUpdate = true;
  }
  if (helpOpen) {
    help.hits = drawHelpCard(help.ctx, link.robot, settings.shortcuts, p, hovered.help, liveInputs);
    help.texture.needsUpdate = true;
  }
}

/** The current alert, used by the banner, the border, the sounds and the tag. */
function currentAlert() {
  return alertFor({ robot: link.robot, readings: link.readings, fresh: link.readingsFresh,
                    linkLost: linkWasOpen && !link.open, units: settings.units });
}

/** Redraw the dashboard / strip / banner. Runs 4x a second (and on changes). */
function drawInfo() {
  const p = pal(), ts = TEXT_SCALE[settings.text_size] || 1;
  const alert = currentAlert();
  const values = link.readingsFresh && link.readings ? link.readings.sensors || {} : {};
  const cards = cardsFor({ cardList: settings.cards, link, local: local() });
  const limit = limitText(link.readings, link.readingsFresh);
  if (infoMode === 1) {
    dash.hits = drawDashboard(dash.ctx, { robot: link.robot, values, alert, units: settings.units, cards, limit,
                                          page: cardPage, overflow: settings.card_overflow, textScale: ts,
                                          hover: hovered.dash }, p);
    cardPage = Math.min(cardPage, (dash.hits.pages || 1) - 1);   // e.g. after cards were turned off
    dash.texture.needsUpdate = true;
  }
  if (infoMode === 2) {
    const big = bigReading((link.robot && link.robot.sensors) || [], values, alert, settings.units);
    const items = [];
    if (big) items.push({ label: big.label[0] + big.label.slice(1).toLowerCase(), value: big.text, level: big.level });
    items.push({ label: "Reverse", value: limit.text, level: limit.level });
    items.push(...cards.filter(c => ["video", "link", "power"].includes(c.id)));
    drawStrip(strip.ctx, items, p, ts);
    strip.texture.needsUpdate = true;
  }
  if (settings.banner && alert.level !== "none") {
    drawBanner(banner.ctx, alert, p, ts);
    banner.texture.needsUpdate = true;
  }
}
setInterval(drawInfo, 250);

// --- Mirroring to the spectator view ------------------------------------------
// The headset tells drive_server.py what it's showing; the Pi passes it on
// to /spectator, which draws the same layout. Sent when something changes,
// and at least once a second (for the video fps / link readings).
let lastUiText = "", lastUiAt = 0;
function sendUi() {
  const r2 = (v) => Math.round(v * 100) / 100;
  const ui = {
    type: "ui", in_mr: renderer.xr.isPresenting, head_look: headLook, info_mode: infoMode,
    settings_open: settingsOpen, help_open: helpOpen, settings_tab: settingsTab,
    settings_page: settingsPage, card_page: cardPage, video_fps: videoFps,
    video_live: videoLive(), link_ms: link.linkMs, pan: Math.round(panNow),
    pressed: helpOpen ? [...liveInputs.pressed] : [],
    sticks: helpOpen ? Object.fromEntries(Object.entries(liveInputs.sticks).map(([h, [x, y]]) => [h, [r2(x), r2(y)]])) : {},
  };
  const text = JSON.stringify(ui), now = performance.now();
  if (text === lastUiText && now - lastUiAt < 1000) return;
  lastUiText = text; lastUiAt = now;
  link.send(ui);
}
setInterval(sendUi, 250);

/**
 * Put the screen settings.screen_distance in front of wherever you're
 * looking (left/right only - looking up or down doesn't tilt it).
 * @param {number} amount  1 = jump there; less = move that fraction of the way
 */
function placeScreen(pose, amount = 1) {
  const p = pose.transform.position, o = pose.transform.orientation;
  const head = new THREE.Vector3(p.x, p.y, p.z);
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(new THREE.Quaternion(o.x, o.y, o.z, o.w));
  forward.y = 0;
  if (forward.lengthSq() < 1e-4) forward.set(0, 0, -1);
  forward.normalize();
  const target = head.clone().addScaledVector(forward, settings.screen_distance);
  target.y = head.y - settings.screen_drop;
  screen.position.lerp(target, amount);
  screen.lookAt(head.x, screen.position.y, head.z);   // face you, upright
}


// =============================================================================
// 5. THE POINTER - point a controller at a button or panel, pull the trigger
// =============================================================================
const raycaster = new THREE.Raycaster();
const pointers = [0, 1].map((i) => {
  const controller = renderer.xr.getController(i);   // follows that controller's aim
  const ray = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -1)]),
                             new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 }));
  ray.visible = false;
  controller.add(ray);
  scene.add(controller);
  const ptr = { controller, ray, target: null };     // target: {name, id} under the pointer
  controller.addEventListener("selectstart", () => { if (ptr.target) click(ptr.target.name, ptr.target.id); });
  return ptr;
});

/** The panels the pointer can click, by name (only the visible ones). */
function clickable() {
  const list = [["bar", bar]];
  if (settingsOpen) list.unshift(["settings", settingsPanel]);
  if (helpOpen) list.unshift(["help", help]);
  if (infoMode === 1 && dash.hits.length) list.push(["dash", dash]);
  return list;
}

/** Which clickable area (if any) a point on a panel's canvas is in. */
function hitAt(panel, uv) {
  const x = uv.x * panel.canvas.width, y = (1 - uv.y) * panel.canvas.height;
  const h = panel.hits.find(r => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
  return h ? h.id : null;
}

/** Every frame: aim each controller's ray, find what it's on, update hover. */
function updatePointers() {
  const hover = { bar: null, settings: null, help: null, dash: null };
  const meshes = clickable();
  for (const ptr of pointers) {
    ptr.target = null; ptr.ray.visible = false;
    const m = ptr.controller.matrixWorld;
    raycaster.ray.origin.setFromMatrixPosition(m);
    raycaster.ray.direction.set(0, 0, -1).transformDirection(m);
    const hits = raycaster.intersectObjects(meshes.map(([, p]) => p.mesh), false);
    const first = hits.find(h => h.distance < 4);
    if (!first) continue;
    const [name, panel] = meshes.find(([, p]) => p.mesh === first.object);
    ptr.ray.visible = true;                              // only shown on something clickable
    ptr.ray.scale.z = first.distance;
    const id = hitAt(panel, first.uv);
    if (id) { ptr.target = { name, id }; hover[name] = id; }
  }
  if (JSON.stringify(hover) !== JSON.stringify(hovered)) { hovered = hover; redrawPanels(); drawInfo(); }
}

/** A click on a panel area. */
function click(name, id) {
  if (name === "bar") return runAction(id);
  if (name === "dash" && id === "page-next") { cardPage++; return drawInfo(); }
  if (name === "dash" && id === "page-prev") { cardPage = Math.max(0, cardPage - 1); return drawInfo(); }
  if (name === "help" && id === "close") return runAction("help");
  if (name === "settings") return settingsClick(id);
}

/** A click on the settings panel: change a setting, switch tab, close... */
function settingsClick(id) {
  const [what, key] = id.includes(":") ? [id.slice(0, id.indexOf(":")), id.slice(id.indexOf(":") + 1)] : [id, null];
  const entry = SCHEMA.find(s => s.key === key);
  if (what === "close") return runAction("settings");
  if (what === "tab") { settingsTab = key; settingsPage = 0; }
  else if (what === "page-next") settingsPage++;
  else if (what === "page-prev") settingsPage = Math.max(0, settingsPage - 1);
  else if (what === "reset") { settings = defaults(); }
  else if (what === "toggle") settings[key] = !settings[key];
  else if (what === "dec" || what === "inc") settings[key] = clampNumber(entry, settings[key] + (what === "inc" ? 1 : -1) * entry.step);
  else if (what === "prev" || what === "next") settings[key] = cycle(entry.options.map(o => o[0]), settings[key], what === "next" ? 1 : -1);
  else if (what === "card" || what === "card-up") {
    const list = (settings.cards || defaultCards(link.robot)).map(c => ({ ...c }));
    const i = list.findIndex(c => c.id === key);
    if (what === "card") list[i].on = !list[i].on;
    else if (i > 0) [list[i - 1], list[i]] = [list[i], list[i - 1]];
    settings.cards = list;
  } else if (what === "sc") {
    const sc = { ...resolveShortcuts(link.robot, settings.shortcuts) };
    for (const b of freeButtons(link.robot)) if (!sc[b]) sc[b] = "none";
    sc[key] = cycle(SHORTCUT_IDS, sc[key] || "none");
    settings.shortcuts = sc;
  }
  if (["screen_distance", "screen_drop"].includes(key)) needsPlacement = true;
  applyScheme(settings);
  saveSettings(settings);
  layout(); redrawPanels(); drawInfo(); drawControls();
}


// =============================================================================
// 6. ALERTS - border colour, beeps, vibration
// =============================================================================
let audio = null;          // AudioContext; started by the Enter button (browsers need a tap)
let nextBeep = 0;          // earliest time the next repeating beep may play (ms)
let lastLevelKey = "";     // to play one-off blips only when something changes

/** Play a short tone, at the volume in Settings. */
function beep(freq, ms, delay = 0) {
  if (!audio || !settings.beeps) return;
  const osc = audio.createOscillator(), gain = audio.createGain();
  osc.frequency.value = freq; gain.gain.value = 0.3 * settings.volume;
  osc.connect(gain).connect(audio.destination);
  const t = audio.currentTime + delay / 1000;
  osc.start(t); osc.stop(t + ms / 1000);
}

/** Vibrate both controllers (both: some Quest versions use the wrong hand). */
function buzz(session, ms) {
  if (!settings.vibration) return;
  for (const source of session.inputSources) {
    const h = source.gamepad && source.gamepad.hapticActuators && source.gamepad.hapticActuators[0];
    if (h && h.pulse) h.pulse(settings.vibration_strength, ms);
  }
}

/**
 * Sounds and vibration, every frame. Repeating sounds only while reversing,
 * unless Settings says "always":
 *   slow  -> beeps that speed up       stop -> continuous tone + buzz
 *   edge  -> low double beep + buzz
 * One-off blips when a sensor stops answering or the connection drops.
 */
function alertSounds(session, time, alert) {
  const key = alert.level + ":" + alert.sensor;
  if (key !== lastLevelKey) {
    if (alert.level === "off") beep(660, 120);                     // sensor not answering
    if (alert.text.startsWith("Connection lost")) beep(330, 220);
    lastLevelKey = key;
  }
  const reversing = lastSticks.ly > 0.05;                          // Quest: pulling back = positive
  if (!(reversing || settings.beep_when === "always") || time < nextBeep || !link.readingsFresh) return;
  const state = link.readings.state;
  if (state === "slow") { beep(880, 60); nextBeep = time + 120 + 600 * link.readings.reverse_limit; }
  else if (state === "stop") { beep(1320, 210); buzz(session, 100); nextBeep = time + 200; }
  else if (state === "edge") { beep(440, 90); beep(440, 90, 140); buzz(session, 100); nextBeep = time + 600; }
}


// =============================================================================
// 7. THE ANIMATION LOOP - once per headset frame (72-120 times a second)
// =============================================================================
renderer.setAnimationLoop((time, frame) => {
  if (!renderer.xr.isPresenting) return;
  const pose = frame ? frame.getViewerPose(renderer.xr.getReferenceSpace()) : null;
  if (link.open) linkWasOpen = true;

  // Screen placement and head-look.
  if (pose && needsPlacement) { placeScreen(pose); needsPlacement = false; refYaw = yawOf(pose); }
  if (pose && wantHeadLookRef) { refYaw = yawOf(pose); wantHeadLookRef = false; }
  const robotButtons = frame ? readButtons(frame.session) : {};
  updatePan(pose);
  if (headLook && pose) placeScreen(pose, 0.08);   // screen glides after you
  updatePointers();
  if (helpOpen && frame) updateLiveInputs(frame.session);

  // Status tags under the screen.
  const p = pal(), live = videoLive(), alert = currentAlert();
  setTag(live ? "LIVE" : "NO VIDEO", live ? p.ok : p.danger);
  setControlTag(link.open ? "CONTROLS ON" : "CONTROLS OFF", link.open ? p.ok : p.danger);
  const values = link.readingsFresh && link.readings ? link.readings.sensors || {} : {};
  const big = bigReading((link.robot && link.robot.sensors) || [], values, alert, settings.units);
  setRearTag(big ? (big.label === "REAR" ? "REAR " : big.label + " ") + big.text : "NO SENSORS",
             big ? levelColor(p, big.level) : p.off);

  // Send the sticks, at most SEND_HZ times a second. Settings open = robot paused.
  if (frame && time - lastSent >= 1000 / SEND_HZ) {
    lastSent = time;
    lastSticks = settingsOpen ? { lx: 0, ly: 0, rx: 0, ry: 0 } : readSticks(frame.session);
    const out = { ...lastSticks, pan: Math.round(panNow) };
    if (Object.keys(robotButtons).length) out.buttons = settingsOpen ? {} : robotButtons;
    link.send(out);
  }

  // Alerts: banner (eases in/out, sits under the strip), border, sounds.
  // (Hidden while settings are open: the robot is paused, and the banner
  // would sit over the top edge of the panel. The border still shows it.)
  const showBanner = settings.banner && alert.level !== "none" && !settingsOpen;
  bannerShow += ((showBanner ? 1 : 0) - bannerShow) * 0.2;
  banner.mesh.visible = bannerShow > 0.02;
  banner.mesh.material.opacity = bannerShow;
  banner.mesh.position.set(0, PANEL_H / 2 - (infoMode === 2 ? 0.22 : 0.09) + (1 - bannerShow) * 0.05, 0.015);
  const tint = !settings.border_flash || alert.level === "none" ? p.bezel
             : alert.level === "warn" ? (p.dark ? 0x6b5300 : 0xf5d77a) : alert.level === "danger" ? (p.dark ? 0x7f1d1d : 0xf4a3a3) : (p.dark ? 0x3a3d44 : 0xc9ccd2);
  bezel.material.color.set(tint);
  if (frame) alertSounds(frame.session, time, alert);

  renderer.render(scene, camera);
});


// =============================================================================
// 8. THE ENTER BUTTON
// =============================================================================

/** Check this browser can do mixed reality, then enable the button or say why not. */
async function checkSupport() {
  if (!window.isSecureContext) {
    // Browsers only allow mixed reality on "secure" pages. Plain http:// to
    // the Pi counts as secure only after the one-time Quest setting below.
    const https = "https://" + location.hostname + ":" + CONFIG.https_port + "/begin";
    btn.textContent = "Mixed reality needs https";
    msg.innerHTML =
      "Use the https page: <a href=\"" + https + "\">" + https + "</a>. Or the one-time Quest setting: " +
      "<code>chrome://flags</code>, search <b>insecure</b>, enable <b>Insecure origins treated as secure</b>, " +
      "type <code>" + location.origin + "</code>, then <b>Relaunch</b>.";
    return;
  }
  if (!navigator.xr || !(await navigator.xr.isSessionSupported("immersive-ar"))) {
    btn.textContent = "Mixed reality not available here";
    msg.textContent = "Open this page in the Meta Quest browser to drive. This screen still shows the checks.";
    return;
  }
  btn.disabled = false;
  btn.textContent = "Enter mixed reality";
  msg.textContent = "The camera appears as a floating screen in your room.";
}

/** Start the mixed-reality session. Leaving it stops the robot. */
async function enter() {
  audio = audio || new AudioContext();               // sound needs a tap to start
  audio.resume();
  try {
    const session = await navigator.xr.requestSession("immersive-ar");
    session.addEventListener("squeeze", () => { needsPlacement = true; });
    session.addEventListener("end", () => {
      headLook = false; panNow = 0; settingsOpen = false; helpOpen = false;
      link.send({ lx: 0, ly: 0, rx: 0, ry: 0, pan: 0 });   // leaving = stop the robot
      layout();
      btn.disabled = false; btn.textContent = "Enter mixed reality";
    });
    await renderer.xr.setSession(session);
    needsPlacement = true; linkWasOpen = link.open;
    layout(); redrawPanels(); drawInfo();
    btn.disabled = true; btn.textContent = "In mixed reality";
  } catch (e) {
    msg.textContent = "Couldn't start mixed reality: " + e.message;
  }
}

// Enter: if any check is red, list them first and ask.
const confirmBox = document.getElementById("confirm");
btn.addEventListener("click", () => {
  const red = checklistFor(link, local(), settings.units).filter(r => r.level === "danger");
  if (!red.length) return enter();
  document.getElementById("confirm-list").innerHTML =
    red.map(r => `<li><b>${r.label}:</b> ${r.value}. ${r.fix}</li>`).join("");
  confirmBox.hidden = false;
});
document.getElementById("confirm-yes").addEventListener("click", () => { confirmBox.hidden = true; enter(); });
document.getElementById("confirm-no").addEventListener("click", () => { confirmBox.hidden = true; });

checkSupport();
redrawPanels();

// For automated tests only: where a clickable area is in the room, so a test
// can point an emulated controller at it. Not used by the page itself.
window.__driveTest = {
  areaWorldPos(name, id) {
    const panel = { bar, settings: settingsPanel, help, dash }[name];
    const r = panel.hits.find(h => h.id === id);
    if (!r) return null;
    const u = (r.x + r.w / 2) / panel.canvas.width - 0.5, v = 0.5 - (r.y + r.h / 2) / panel.canvas.height;
    const g = panel.mesh.geometry.parameters;
    screen.updateMatrixWorld(true);
    return panel.mesh.localToWorld(new THREE.Vector3(u * g.width, v * g.height, 0)).toArray();
  },
  state: () => ({ headLook, infoMode, settingsOpen, helpOpen, settingsTab, cardPage, settings }),
  pointers: () => pointers.map(p => ({ pos: new THREE.Vector3().setFromMatrixPosition(p.controller.matrixWorld).toArray(),
                                       target: p.target, rayVisible: p.ray.visible })),
};
