/*
  readings.js - turns drive_server.py's messages into things to show:
  colours, the alert banner, the reading cards and the checklist rows.

  Pure functions (no drawing, no page elements), shared by the headset page
  (drive.js), the begin screen, the start screen and the spectator view,
  so they all say exactly the same thing.

  Everything is built from the robot's SENSOR LIST (the "robot" message,
  from hardware/rear_sensor.py describe()), so a new sensor shows up
  everywhere without changing this file.
*/

// =============================================================================
// COLOURS for drawn panels (the web pages use css/site.css instead)
// =============================================================================

const STATUS = {
  standard:    { ok: "#34c759", warn: "#ffcc00", danger: "#ff453a", off: "#8e8e93" },
  colourblind: { ok: "#3d9bdc", warn: "#e69f00", danger: "#e5571b", off: "#8e8e93" },
  contrast:    { ok: "#00e05a", warn: "#ffd400", danger: "#ff2a1f", off: "#b0b0b0" },
};
const STATUS_LIGHT = {
  standard:    { ok: "#1e8e46", warn: "#a96b00", danger: "#d32f2f", off: "#6b7280" },
  colourblind: { ok: "#0068a8", warn: "#b26b00", danger: "#c2410c", off: "#6b7280" },
  contrast:    { ok: "#006b2b", warn: "#7a4d00", danger: "#b00000", off: "#374151" },
};

/**
 * The colours for one theme and colour scheme.
 * @param {"dark"|"light"} theme
 * @param {"standard"|"colourblind"|"contrast"} scheme
 * @returns {object} panel, panelEdge, card, text, muted, track + ok/warn/danger/off
 */
export function palette(theme, scheme = "standard") {
  const dark = theme !== "light";
  const s = (dark ? STATUS : STATUS_LIGHT)[scheme] || STATUS.standard;
  return Object.assign({
    dark,
    panel: dark ? "rgba(15, 17, 21, 0.92)" : "rgba(250, 251, 252, 0.95)",
    panelEdge: dark ? "rgba(255, 255, 255, 0.10)" : "rgba(0, 0, 0, 0.12)",
    card: dark ? "rgba(255, 255, 255, 0.06)" : "rgba(0, 0, 0, 0.05)",
    text: dark ? "#eef0f2" : "#15171b",
    muted: dark ? "#a3a9b3" : "#59606d",
    track: dark ? "rgba(255, 255, 255, 0.14)" : "rgba(0, 0, 0, 0.12)",
    bezel: dark ? 0x0b0d10 : 0xe9ebef,          // the video frame, as a 3D colour
  }, s);
}

/** Status level -> colour name in a palette. */
export const LEVEL_COLOR = { clear: "ok", slow: "warn", stop: "danger", edge: "danger", fault: "off" };

// =============================================================================
// FORMATTING
// =============================================================================

/** A distance in the chosen units: "4.5 in" or "11 cm". */
export function showDistance(cm, units) {
  if (cm == null) return "-";
  return units === "cm" ? Math.round(cm) + " cm" : (cm / 2.54).toFixed(1) + " in";
}

/** Where a sensor is, in words: "behind", "ahead", "on the left"... */
export function where(position) {
  return {
    rear: "behind", front: "ahead", left: "on the left", right: "on the right",
    rear_left: "behind left", rear_right: "behind right",
    front_left: "ahead left", front_right: "ahead right",
  }[position] || "";
}

/** Which way a sensor limits: rear sensors limit reverse, front ones forward. */
export function direction(position) {
  return String(position || "").startsWith("front") ? "forward" : "reverse";
}

// =============================================================================
// THE ALERT BANNER
// =============================================================================

/**
 * What the alert banner should say right now, if anything.
 * Most urgent first: connection lost, edge, stop, sensor not answering, slow.
 *
 * @param {object} p
 * @param {object|null} p.robot     the robot message (sensor list)
 * @param {object|null} p.readings  the latest readings message
 * @param {boolean} p.fresh         readings arrived in the last second
 * @param {boolean} p.linkLost      the link was open and has dropped
 * @param {string}  p.units         "in" or "cm"
 * @returns {{level: "none"|"warn"|"danger"|"off", text: string, sensor: string|null}}
 */
export function alertFor({ robot, readings, fresh, linkLost, units }) {
  if (linkLost) return { level: "danger", text: "Connection lost: robot stopped", sensor: null };
  if (!readings || !fresh || !robot) return { level: "none", text: "", sensor: null };
  const sensors = robot.sensors || [];
  const info = (id) => sensors.find(s => s.id === id) || { id, name: id, position: "rear" };
  const r = readings.sensors || {};
  const dirOf = (s) => direction(s.position);

  // Edges and stops block motion: show those first, from any sensor.
  for (const s of sensors) {
    const v = r[s.id];
    if (v && v.state === "edge")
      return { level: "danger", sensor: s.id,
               text: `Edge ${where(s.position)}: ${dirOf(s)} blocked` };
  }
  for (const s of sensors) {
    const v = r[s.id];
    if (v && v.state === "stop")
      return { level: "danger", sensor: s.id,
               text: `Stop: obstacle ${showDistance(v.cm, units)} ${where(s.position)}, ${dirOf(s)} blocked` };
  }
  for (const s of sensors) {
    const v = r[s.id];
    if (v && v.state === "fault")
      return { level: "off", sensor: s.id, text: `${s.name} sensor not answering: ${dirOf(s)} blocked` };
  }
  for (const s of sensors) {
    const v = r[s.id];
    if (v && v.state === "slow") {
      const pct = Math.round((readings.reverse_limit ?? 1) * 100);
      return { level: "warn", sensor: s.id,
               text: `Slow: ${showDistance(v.cm, units)} ${where(s.position)}, ${dirOf(s)} ${pct}%` };
    }
  }
  return { level: "none", text: "", sensor: null };
}

// =============================================================================
// READING CARDS (dashboard, strip, spectator view)
// =============================================================================

/**
 * Every card this robot could show, as [id, label], for the settings screens.
 * Number / on-off sensors from the sensor list are added automatically.
 */
export function cardCatalog(robot) {
  const list = [
    ["video", "Video"], ["link", "Link"], ["wifi", "Wi-Fi"], ["pi_temp", "Pi temperature"],
    ["power", "Pi power"], ["wheels", "Wheel power"], ["camera", "Camera angle"],
    ["headlook", "Head-look"], ["cpu", "Pi load"], ["battery", "Battery"],
    ["speed", "Speed"], ["altitude", "Altitude"], ["heading", "Heading"],
  ];
  for (const s of (robot && robot.sensors) || [])
    if (s.kind === "number" || s.kind === "onoff") list.push(["sensor:" + s.id, s.name]);
  return list;
}

/** The default card list: [{id, on}], in order. */
export function defaultCards(robot) {
  const on = new Set(["video", "link", "wifi", "pi_temp", "power", "wheels", "camera", "headlook"]);
  return cardCatalog(robot).map(([id]) => ({ id, on: on.has(id) || id.startsWith("sensor:") }));
}

/**
 * The cards to draw right now: [{id, label, value, level}].
 * A card whose reading isn't available (e.g. battery on the car) is left out.
 *
 * @param {object} p
 * @param {Array|null} p.cardList  settings.cards (null = defaults)
 * @param {object} p.link          the DriveLink (robot, readings, status, linkMs)
 * @param {object} p.local         page-side values: videoFps, videoLive, pan, headLook
 */
export function cardsFor({ cardList, link, local }) {
  const robot = link.robot;
  const list = cardList || defaultCards(robot);
  const st = link.statusFresh ? link.status : null;
  const rd = link.readingsFresh ? link.readings : null;
  const lvl = (v, okBelow, warnBelow) => v < okBelow ? "ok" : v < warnBelow ? "warn" : "danger";
  const out = [];
  const add = (id, label, value, level = "text") => out.push({ id, label, value, level });

  for (const { id, on } of list) {
    if (!on) continue;
    if (id === "video") add(id, "Video", local.videoLive ? local.videoFps + " fps" : "NONE",
                            !local.videoLive || local.videoFps < 8 ? "danger" : local.videoFps < 15 ? "warn" : "ok");
    else if (id === "link") add(id, "Link", !link.open ? "OFF" : link.linkMs == null ? "..." : link.linkMs + " ms",
                                !link.open ? "danger" : link.linkMs == null ? "off" : lvl(link.linkMs, 150, 300));
    else if (id === "wifi" && st && st.wifi_dbm != null) add(id, "Wi-Fi", st.wifi_dbm + " dBm", lvl(-st.wifi_dbm, 67, 75));
    else if (id === "pi_temp" && st && st.cpu_temp_c != null) add(id, "Pi temp", Math.round(st.cpu_temp_c) + " °C", lvl(st.cpu_temp_c, 70, 80));
    else if (id === "power" && st && st.power_ok != null)
      add(id, "Power", st.power_ok === false ? "LOW!" : st.power_warned ? "dipped" : "OK",
          st.power_ok === false ? "danger" : st.power_warned ? "warn" : "ok");
    else if (id === "cpu" && st && st.cpu_load_pct != null) add(id, "Pi load", st.cpu_load_pct + "%", lvl(st.cpu_load_pct, 80, 100));
    else if (id === "battery" && st && st.battery_v != null) add(id, "Battery", st.battery_v.toFixed(2) + " V");
    else if (id === "speed" && st && st.speed_mps != null) add(id, "Speed", st.speed_mps.toFixed(2) + " m/s");
    else if (id === "altitude" && st && st.altitude_m != null) add(id, "Altitude", st.altitude_m.toFixed(1) + " m");
    else if (id === "heading" && st && st.heading_deg != null) add(id, "Heading", Math.round(st.heading_deg) + "°");
    else if (id === "wheels" && rd) add(id, "Wheels", rd.left_pct + " / " + rd.right_pct + "%");
    else if (id === "camera") {
      const pan = Math.round(local.pan || 0);
      add(id, "Camera", pan === 0 ? "ahead" : Math.abs(pan) + "° " + (pan > 0 ? "R" : "L"));
    } else if (id === "headlook") add(id, "Head-look", local.headLook ? "ON" : "off", local.headLook ? "ok" : "off");
    else if (id.startsWith("sensor:") && rd && robot) {
      const sid = id.slice(7), s = (robot.sensors || []).find(x => x.id === sid), v = (rd.sensors || {})[sid];
      if (s && v) add(id, s.name, v.value != null ? String(v.value) + (s.units ? " " + s.units : "") : (v.state || "-"),
                      LEVEL_COLOR[v.state] || "text");
    }
  }
  return out;
}

/** "Reverse OK" / "Reverse 40%" / "Reverse BLOCKED", for the gauge label. */
export function limitText(readings, fresh) {
  if (!readings || !fresh) return { text: "?", level: "off", value: 0 };
  const lim = readings.reverse_limit;
  return { value: lim, level: lim === 0 ? "danger" : lim < 1 ? "warn" : "ok",
           text: lim === 0 ? "BLOCKED" : lim < 1 ? Math.round(lim * 100) + "%" : "OK" };
}

// =============================================================================
// THE BEGIN-SCREEN CHECKLIST (and the start screen's status card)
// =============================================================================

/**
 * One row per check: [{label, value, level, fix}]. The fix text only shows
 * when a row isn't green.
 * @param {object} link   the DriveLink
 * @param {object} local  videoFps, videoLive
 * @param {string} units
 */
export function checklistFor(link, local, units) {
  const rows = [];
  const st = link.statusFresh ? link.status : null;
  const rd = link.readingsFresh ? link.readings : null;
  rows.push({ label: "Video", value: local.videoLive ? local.videoFps + " fps" : "no picture",
              level: !local.videoLive ? "danger" : local.videoFps < 10 ? "warn" : "ok",
              fix: !local.videoLive ? "Run python3 camera_server.py on the Pi" : "Video is slow: move closer to the router, or lower FRAMES_PER_SECOND" });
  rows.push({ label: "Drive link", value: !link.open ? "off" : link.linkMs == null ? "connected" : link.linkMs + " ms",
              level: !link.open ? "danger" : link.linkMs != null && link.linkMs >= 150 ? "warn" : "ok",
              fix: !link.open ? "Run python3 drive_server.py on the Pi (from ~/robot-car)" : "The link is slow: move closer to the router" });
  for (const s of (link.robot && link.robot.sensors) || []) {
    const v = rd && rd.sensors ? rd.sensors[s.id] : null;
    const state = v ? v.state : null;
    const value = !v ? "no data" : state === "fault" ? "not answering"
                : s.kind === "distance" ? showDistance(v.cm, units) : s.kind === "edge" ? (state === "edge" ? "EDGE" : "floor OK")
                : state || "ok";
    rows.push({ label: s.name + " sensor", value,
                level: !v || state === "fault" ? "danger" : state === "clear" ? "ok" : "warn",
                fix: !v ? "Waiting for drive_server.py" : state === "fault" ? s.fix || "Check its wiring and power"
                   : s.kind === "edge" ? "Edge seen: move the car back onto the floor" : "Something is close: clear the area" });
  }
  rows.push(st && st.power_ok != null
    ? { label: "Pi power", value: st.power_ok === false ? "LOW" : st.power_warned ? "dipped earlier" : "OK",
        level: st.power_ok === false ? "danger" : st.power_warned ? "warn" : "ok", fix: "Charge the car battery" }
    : { label: "Pi power", value: "no data", level: "off", fix: "Appears once drive_server.py is running (it can only be read on the Pi itself)" });
  if (st && st.wifi_dbm != null)
    rows.push({ label: "Wi-Fi", value: st.wifi_dbm + " dBm", level: st.wifi_dbm > -67 ? "ok" : st.wifi_dbm > -75 ? "warn" : "danger",
                fix: "Move the car or the router closer together" });
  if (st && st.cpu_temp_c != null)
    rows.push({ label: "Pi temperature", value: Math.round(st.cpu_temp_c) + " °C",
                level: st.cpu_temp_c < 70 ? "ok" : st.cpu_temp_c < 80 ? "warn" : "danger", fix: "Let the Pi cool down" });
  return rows;
}
