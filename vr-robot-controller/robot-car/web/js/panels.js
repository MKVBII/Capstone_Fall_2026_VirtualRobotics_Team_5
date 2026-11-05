/*
  panels.js - draws the headset's clickable panels onto 2D canvases:
  the quick-button bar, the settings panel and the help card.

  Used by:  drive.js, which shows each canvas on a 3D panel and works out
            where the controller's pointer hits it.
  Why canvases: inside mixed reality the Quest can't show normal web page
  elements, so every panel is drawn as a picture and clicked by pointing.

  Every draw function returns its clickable areas as
      [{id, x, y, w, h}]   in canvas pixels
  and drive.js turns a pointer hit into one of those ids. `hover` is the id
  the pointer is on now, drawn highlighted.
*/

import { SCHEMA, TABS, valueText, SHORTCUT_ACTIONS } from "./settings.js";
import { cardCatalog, defaultCards } from "./readings.js";
import { controlsFor, freeButtons, actionName } from "./controls.js";

const FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif";
function font(ctx, weight, px) { ctx.font = `${weight} ${px}px ${FONT}`; }
function rr(ctx, x, y, w, h, r, fill, stroke, lw = 3) {
  ctx.beginPath(); ctx.roundRect(x, y, w, h, r);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lw; ctx.stroke(); }
}

/**
 * A clickable button: rounded box with centred text, highlighted on hover.
 * Adds itself to `hits`.
 */
function button(ctx, hits, hover, pal, id, x, y, w, h, text, opts = {}) {
  const on = hover === id;
  rr(ctx, x, y, w, h, Math.min(18, h / 2), opts.fill || (on ? pal.track : pal.card), on ? pal.text : pal.panelEdge, on ? 4 : 2);
  font(ctx, opts.weight || 700, opts.size || 30);
  ctx.fillStyle = opts.color || pal.text; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, x + w / 2, y + h / 2 + 1);
  hits.push({ id, x, y, w, h });
}

// =============================================================================
// QUICK-BUTTON BAR (under the video)
// =============================================================================

/** The buttons on the bar, in order: [id, label]. */
export const BAR_BUTTONS = [
  ["headlook", "Head-look"], ["dashboard", "Dashboard"], ["recenter", "Re-centre"],
  ["help", "Help"], ["settings", "Settings"],
];

/** Draw one icon, centred at (x, y), using simple shapes. */
function icon(ctx, id, x, y, color) {
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 5; ctx.lineCap = "round"; ctx.lineJoin = "round";
  ctx.beginPath();
  if (id === "headlook") {            // an eye
    ctx.moveTo(x - 24, y); ctx.quadraticCurveTo(x, y - 22, x + 24, y); ctx.quadraticCurveTo(x, y + 22, x - 24, y);
    ctx.stroke(); ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill();
  } else if (id === "dashboard") {    // a gauge
    ctx.arc(x, y + 8, 22, Math.PI, 0); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, y + 8); ctx.lineTo(x + 12, y - 8); ctx.stroke();
  } else if (id === "recenter") {     // a target
    ctx.arc(x, y, 18, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
  } else if (id === "help") {         // a question mark
    font(ctx, 800, 44); ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("?", x, y + 2);
  } else if (id === "settings") {     // a gear
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4;
      ctx.moveTo(x + Math.cos(a) * 14, y + Math.sin(a) * 14); ctx.lineTo(x + Math.cos(a) * 24, y + Math.sin(a) * 24);
    }
    ctx.stroke(); ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI * 2); ctx.stroke();
  }
}

/**
 * Draw the quick-button bar. Canvas: 1100 x 150 px.
 * @param {object} state  headLook (bool), infoMode (0/1/2), settingsOpen, helpOpen
 */
export function drawQuickBar(ctx, state, pal, hover) {
  const W = ctx.canvas.width, H = ctx.canvas.height, hits = [];
  ctx.clearRect(0, 0, W, H);
  rr(ctx, 0, 0, W, H, 40, pal.panel);
  const n = BAR_BUTTONS.length, slot = W / n;
  BAR_BUTTONS.forEach(([id, label], i) => {
    const cx = slot * i + slot / 2;
    const active = (id === "headlook" && state.headLook) || (id === "dashboard" && state.infoMode > 0) ||
                   (id === "settings" && state.settingsOpen) || (id === "help" && state.helpOpen);
    const on = hover === id;
    ctx.beginPath(); ctx.arc(cx, 58, 40, 0, Math.PI * 2);
    ctx.fillStyle = active ? pal.ok : on ? pal.track : pal.card; ctx.fill();
    if (on) { ctx.lineWidth = 4; ctx.strokeStyle = pal.text; ctx.stroke(); }
    icon(ctx, id, cx, 58, active ? (pal.dark ? "#0b0d10" : "#ffffff") : pal.text);
    font(ctx, 600, 24); ctx.fillStyle = pal.muted; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const sub = id === "dashboard" ? ["Dashboard", "Dash: below", "Dash: strip"][state.infoMode] : label;
    ctx.fillText(sub, cx, 124);
    hits.push({ id, x: slot * i, y: 0, w: slot, h: H });
  });
  return hits;
}

// =============================================================================
// SETTINGS PANEL
// =============================================================================

const ROWS_PER_PAGE = 7;

/**
 * The rows the settings panel shows on one tab, as simple descriptions:
 *   {kind: "setting", entry}            one SCHEMA entry
 *   {kind: "card", id, label, on}       one dashboard reading
 *   {kind: "shortcut", button}          one A/B/X/Y shortcut
 */
function rowsFor(tab, settings, robot) {
  const rows = [];
  for (const entry of SCHEMA.filter(s => s.tab === tab)) {
    if (entry.type === "cards") {
      const list = settings.cards || defaultCards(robot);
      const names = Object.fromEntries(cardCatalog(robot));
      for (const c of list) if (names[c.id]) rows.push({ kind: "card", id: c.id, label: names[c.id], on: c.on });
    } else if (entry.type === "shortcuts") {
      for (const b of freeButtons(robot)) rows.push({ kind: "shortcut", button: b });
    } else rows.push({ kind: "setting", entry });
  }
  return rows;
}

/**
 * Draw the settings panel. Canvas: 1600 x 1100 px.
 * @param {object} st  tab (name), page (number), settings, shortcuts (resolved), robot
 * @returns {Array} clickable areas. Ids:
 *   close, reset, tab:<name>, page-prev, page-next,
 *   toggle:<key>, dec:<key>, inc:<key>, prev:<key>, next:<key>,
 *   card:<id> (on/off), card-up:<id> (move up), sc:<button> (next action)
 */
export function drawSettingsPanel(ctx, st, pal, hover) {
  const W = ctx.canvas.width, H = ctx.canvas.height, hits = [];
  ctx.clearRect(0, 0, W, H);
  rr(ctx, 0, 0, W, H, 44, pal.panel, pal.panelEdge, 3);
  ctx.textBaseline = "middle";

  // Title, the "paused" note, and Close.
  // The paused note starts after the title's real width, so a wider headset
  // font can't run them together, and is shrunk if it would reach Close.
  ctx.textAlign = "left"; font(ctx, 800, 54); ctx.fillStyle = pal.text; ctx.fillText("Settings", 64, 80);
  const noteX = 64 + ctx.measureText("Settings").width + 36, noteMax = W - 260 - noteX - 24;
  let notePx = 28;
  font(ctx, 500, notePx);
  while (notePx > 18 && ctx.measureText("Robot paused while settings are open").width > noteMax) font(ctx, 500, --notePx);
  ctx.fillStyle = pal.warn; ctx.fillText("Robot paused while settings are open", noteX, 84);
  button(ctx, hits, hover, pal, "close", W - 244, 42, 180, 76, "Close", { fill: hover === "close" ? pal.ok : pal.card });

  // Tabs.
  const tw = (W - 112) / TABS.length;
  TABS.forEach((t, i) => {
    const x = 56 + i * tw, sel = st.tab === t, id = "tab:" + t;
    rr(ctx, x + 4, 136, tw - 8, 72, 16, sel ? pal.track : hover === id ? pal.card : null);
    font(ctx, 700, 32); ctx.textAlign = "center"; ctx.fillStyle = sel ? pal.text : pal.muted;
    ctx.fillText(t, x + tw / 2, 173);
    if (sel) rr(ctx, x + 30, 202, tw - 60, 6, 3, pal.ok);
    hits.push({ id, x: x + 4, y: 136, w: tw - 8, h: 72 });
  });

  // The rows on this tab (paged).
  const rows = rowsFor(st.tab, st.settings, st.robot);
  const pages = Math.max(1, Math.ceil(rows.length / ROWS_PER_PAGE));
  const page = Math.min(st.page, pages - 1);
  const top = 236, rowH = 106;
  rows.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE).forEach((row, i) => {
    const y = top + i * rowH, cy = y + rowH / 2;
    ctx.fillStyle = pal.panelEdge; ctx.fillRect(56, y + rowH - 2, W - 112, 2);
    ctx.textAlign = "left";
    const cx = W - 56;           // controls are right-aligned to here
    if (row.kind === "setting") {
      const e = row.entry, v = st.settings[e.key];
      font(ctx, 600, 34); ctx.fillStyle = pal.text; ctx.fillText(e.label, 56, e.hint ? cy - 16 : cy);
      if (e.hint) { font(ctx, 400, 24); ctx.fillStyle = pal.muted; ctx.fillText(e.hint, 56, cy + 22); }
      if (e.type === "toggle") {
        const id = "toggle:" + e.key, x = cx - 140, on = !!v;
        rr(ctx, x, cy - 30, 140, 60, 30, on ? pal.ok : pal.track, hover === id ? pal.text : null, 4);
        ctx.beginPath(); ctx.arc(on ? x + 110 : x + 30, cy, 24, 0, Math.PI * 2); ctx.fillStyle = "#ffffff"; ctx.fill();
        hits.push({ id, x, y: cy - 34, w: 140, h: 68 });
      } else {
        const dec = e.type === "number" ? "dec:" : "prev:", inc = e.type === "number" ? "inc:" : "next:";
        const w = 420, x = cx - w;
        button(ctx, hits, hover, pal, dec + e.key, x, cy - 34, 76, 68, e.type === "number" ? "−" : "‹", { size: 40 });
        button(ctx, hits, hover, pal, inc + e.key, cx - 76, cy - 34, 76, 68, e.type === "number" ? "+" : "›", { size: 40 });
        font(ctx, 700, 30); ctx.textAlign = "center"; ctx.fillStyle = pal.text;
        ctx.fillText(valueText(e, v), x + w / 2, cy);
      }
    } else if (row.kind === "card") {
      font(ctx, 600, 34); ctx.fillStyle = pal.text; ctx.fillText(row.label, 56, cy);
      const id = "card:" + row.id, x = cx - 140;
      rr(ctx, x, cy - 30, 140, 60, 30, row.on ? pal.ok : pal.track, hover === id ? pal.text : null, 4);
      ctx.beginPath(); ctx.arc(row.on ? x + 110 : x + 30, cy, 24, 0, Math.PI * 2); ctx.fillStyle = "#ffffff"; ctx.fill();
      hits.push({ id, x, y: cy - 34, w: 140, h: 68 });
      button(ctx, hits, hover, pal, "card-up:" + row.id, x - 200, cy - 34, 170, 68, "Move up", { size: 26 });
    } else if (row.kind === "shortcut") {
      font(ctx, 600, 34); ctx.fillStyle = pal.text; ctx.fillText(row.button.toUpperCase() + " button", 56, cy);
      const id = "sc:" + row.button, w = 420;
      button(ctx, hits, hover, pal, id, cx - w, cy - 34, w, 68, actionName(st.shortcuts[row.button] || "none") + "  ›", { size: 28 });
    }
  });

  // Bottom: page buttons and Reset.
  const by = H - 104;
  if (pages > 1) {
    if (page > 0) button(ctx, hits, hover, pal, "page-prev", 56, by, 200, 72, "‹ Back");
    font(ctx, 600, 28); ctx.textAlign = "center"; ctx.fillStyle = pal.muted;
    ctx.fillText(`Page ${page + 1} of ${pages}`, 400, by + 36);
    if (page < pages - 1) button(ctx, hits, hover, pal, "page-next", 540, by, 200, 72, "More ›");
  }
  button(ctx, hits, hover, pal, "reset", W - 376, by, 320, 72, "Reset to defaults", { size: 28, color: pal.danger });
  return hits;
}

/** The next value for a choice setting (wraps round), or a shortcut. */
export function cycle(options, value, step = 1) {
  const i = options.indexOf(value);
  return options[(i + step + options.length) % options.length];
}

/** All the action ids a shortcut can take, in order. */
export const SHORTCUT_IDS = SHORTCUT_ACTIONS.map(a => a[0]);

// =============================================================================
// HELP CARD
// =============================================================================

/**
 * Draw the help card: every control on both controllers, one controller
 * above the other. Canvas 1100 x 1400 (a tall card beside the video).
 * Whatever is being pressed or moved right now lights up, and each
 * thumbstick row shows where the stick is, so controls can be tried out
 * while reading.
 * @param {object|null} robot  @param {object|null} chosenShortcuts settings.shortcuts
 * @param {object} [live]  from drive.js: {pressed: Set("left:stick", "right:a"...),
 *                         sticks: {left: [x, y], right: [x, y]}}
 */
export function drawHelpCard(ctx, robot, chosenShortcuts, pal, hover, live) {
  const W = ctx.canvas.width, H = ctx.canvas.height, hits = [];
  const pressed = (live && live.pressed) || new Set(), sticks = (live && live.sticks) || {};
  ctx.clearRect(0, 0, W, H);
  rr(ctx, 0, 0, W, H, 44, pal.panel, pal.panelEdge, 3);
  ctx.textBaseline = "middle"; ctx.textAlign = "left";
  font(ctx, 800, 54); ctx.fillStyle = pal.text; ctx.fillText("Controls", 64, 84);
  font(ctx, 500, 28); ctx.fillStyle = pal.muted;
  ctx.fillText(robot ? robot.name : "Waiting for the robot...", 64, 136);
  button(ctx, hits, hover, pal, "close", W - 244, 46, 180, 76, "Close");

  const c = controlsFor(robot, chosenShortcuts);
  const rowH = 80;
  let y = 210;
  [["Left controller", "left", c.left], ["Right controller", "right", c.right]].forEach(([title, hand, list]) => {
    font(ctx, 700, 32); ctx.fillStyle = pal.muted; ctx.textAlign = "left"; ctx.fillText(title, 64, y);
    y += 62;
    list.forEach((item) => {
      const on = pressed.has(hand + ":" + item.key);
      // The control's name chip: filled in the "ok" colour while in use.
      rr(ctx, 64, y - 32, 190, 64, 16, on ? pal.ok : pal.card, on ? pal.text : null, 3);
      font(ctx, 800, 26); ctx.textAlign = "center";
      ctx.fillStyle = on ? "#ffffff" : pal.text;
      ctx.fillText(item.name, 64 + 95, y);
      // What it does.
      const stickPos = item.key === "stick" && sticks[hand];
      const textW = W - 64 - 280 - (stickPos ? 110 : 0);
      ctx.textAlign = "left"; font(ctx, on ? 700 : 500, 28);
      ctx.fillStyle = item.label === "Not used" ? pal.muted : pal.text;
      wrap(ctx, item.label, 280, y, textW, 34);
      // Thumbstick: a small circle with a dot showing where the stick is.
      if (stickPos) {
        const cx = W - 64 - 40, r = 36;
        ctx.beginPath(); ctx.arc(cx, y, r, 0, Math.PI * 2);
        ctx.strokeStyle = pal.muted; ctx.lineWidth = 3; ctx.stroke();
        ctx.beginPath(); ctx.arc(cx + stickPos[0] * (r - 10), y + stickPos[1] * (r - 10), 10, 0, Math.PI * 2);
        ctx.fillStyle = on ? pal.ok : pal.muted; ctx.fill();
      }
      y += rowH;
    });
    y += 24;
  });
  font(ctx, 500, 26); ctx.fillStyle = pal.muted; ctx.textAlign = "left";
  wrap(ctx, "Try a control: it lights up here. The robot really moves, so keep it on a block or in a clear space.",
       64, H - 70, W - 128, 34);
  return hits;
}

/** Draw text in up to two lines, wrapping at maxWidth. */
function wrap(ctx, text, x, y, maxWidth, lineH) {
  const words = text.split(" ");
  let line = "", lines = [];
  for (const w of words) {
    const t = line ? line + " " + w : w;
    if (ctx.measureText(t).width > maxWidth && line) { lines.push(line); line = w; } else line = t;
  }
  lines.push(line);
  lines = lines.slice(0, 2);
  lines.forEach((l, i) => ctx.fillText(l, x, y + (i - (lines.length - 1) / 2) * lineH));
}
