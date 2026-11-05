/*
  spectator.js - the spectator view (pages/spectator.html): a mirror of the
  driver's headset.

  Connects to drive_server.py as a "viewer" (it can't drive). Besides the
  readings, the Pi passes on a "ui" message from the headset saying what's
  on show there (dashboard / strip / off, head-look, help card, settings
  panel, which page...). This page lays the same panels out where the
  headset puts them (1 metre = 500 "world" pixels, the same sizes as in
  drive.js), draws them with the same code (hud.js, panels.js), then scales
  the whole layout to fit the window, so nothing is ever cut off.

  With no driver in the headset, it shows the default layout from Settings.
*/

import { DriveLink, loadConfig } from "./link.js";
import { loadSettings, applyScheme } from "./settings.js";
import { palette, alertFor, cardsFor, limitText } from "./readings.js";
import { drawDashboard, drawBanner, drawStrip, bigReading, levelColor } from "./hud.js";
import { drawQuickBar, drawHelpCard, drawSettingsPanel } from "./panels.js";
import { resolveShortcuts } from "./controls.js";

const CONFIG = await loadConfig();
let settings = await loadSettings();
applyScheme(settings);
const link = new DriveLink({ role: "viewer", port: CONFIG.drive_port, viewerPort: CONFIG.viewer_port });
const $ = (id) => document.getElementById(id);
const img = document.querySelector("#screen img");
const TEXT_SCALE = { small: 0.85, normal: 1, large: 1.2 };

// Settings are saved on the Pi; re-read them so changes the driver makes
// (dashboard position, units, which readings...) show up here too.
setInterval(async () => { settings = await loadSettings(); applyScheme(settings); }, 2000);

// =============================================================================
// LAYOUT - where each panel goes, in world pixels (same numbers as drive.js)
// =============================================================================

const M = 500;                                         // world pixels per metre
const SW = 1.6 * M;                                    // the video screen at its base width
const SH = SW * CONFIG.video_height / CONFIG.video_width;

/** Put one element at a centre point (cx, cy) with a size (w x h). */
function place(el, cx, cy, w, h, show = true) {
  el.style.display = show ? "" : "none";
  if (!show) return null;
  Object.assign(el.style, { left: cx - w / 2 + "px", top: cy - h / 2 + "px", width: w + "px", height: h + "px" });
  return { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 };
}

/**
 * Lay out every panel for the current state, then scale it to fit.
 * @param {object} ui  what the headset shows (or the defaults)
 */
function layout(ui) {
  const boxes = [];
  const add = (b) => { if (b) boxes.push(b); };
  const s = settings.dashboard_size || 1;
  add(place($("screen"), 0, 0, SW, SH));
  place($("strip"), 0, -SH / 2 + 0.08 * M, SW * 0.96, 0.12 * M, ui.info_mode === 2 && !ui.settings_open);
  // (The banner position is set every frame in draw(): it eases in and out.)
  const tagY = SH / 2 + 0.07 * M;
  add(place($("tag-video"), -SW / 2 + 0.2 * M, tagY, 0.4 * M, 0.05 * M));
  add(place($("tag-rear"), 0, tagY, 0.4 * M, 0.05 * M));
  add(place($("tag-controls"), SW / 2 - 0.2 * M, tagY, 0.4 * M, 0.05 * M));
  const barY = SH / 2 + 0.17 * M;
  add(place($("bar"), 0, barY, 0.88 * M, 0.12 * M));
  // Dashboard: below the bar, or beside the screen (headset: turned to face you).
  const dw = 1.6 * M * s, dh = 0.52 * M * s;
  if (settings.dashboard_place === "below") {
    add(place($("dash"), 0, barY + 0.06 * M + 0.06 * M + dh / 2, dw, dh, ui.info_mode === 1));
  } else {
    const side = settings.dashboard_place === "left" ? -1 : 1;
    add(place($("dash"), side * (SW / 2 + 0.85 * M * s), 0, dw, dh, ui.info_mode === 1));
  }
  // Help card: beside the screen, on the side away from the dashboard.
  const helpSide = settings.dashboard_place === "right" ? -1 : 1;
  add(place($("help"), helpSide * (SW / 2 + 0.48 * M), 0, 0.88 * M, 1.12 * M, !!ui.help_open));
  add(place($("settings"), 0, 0, 1.4 * M, 0.9625 * M, !!ui.settings_open));

  // Scale everything that's showing to fit the stage, centred.
  const x0 = Math.min(...boxes.map(b => b.x0)), x1 = Math.max(...boxes.map(b => b.x1));
  const y0 = Math.min(...boxes.map(b => b.y0)), y1 = Math.max(...boxes.map(b => b.y1));
  const stage = $("stage").getBoundingClientRect(), pad = 16;
  const k = Math.min((stage.width - 2 * pad) / (x1 - x0), (stage.height - 2 * pad) / (y1 - y0));
  const ox = (stage.width - k * (x1 - x0)) / 2 - k * x0, oy = (stage.height - k * (y1 - y0)) / 2 - k * y0;
  $("world").style.transform = `translate(${ox}px, ${oy}px) scale(${k})`;
}

// =============================================================================
// DRAWING - 4 times a second, like the headset
// =============================================================================

let linkWasOpen = false, bannerShow = 0, startedAt = performance.now();
const hex = (n) => "#" + n.toString(16).padStart(6, "0");

/** What the headset is showing; with no driver, the default layout. */
function currentUi() {
  const ui = link.ui;
  if (ui && ui.driver) return ui;
  return { driver: false, in_mr: false, info_mode: 1, head_look: false, help_open: false, settings_open: false };
}

function draw() {
  if (link.open) linkWasOpen = true;
  const ui = currentUi();
  layout(ui);
  const pal = palette(settings.headset_theme, settings.colour_scheme), ts = TEXT_SCALE[settings.text_size] || 1;
  const alert = alertFor({ robot: link.robot, readings: link.readings, fresh: link.readingsFresh,
                           linkLost: linkWasOpen && !link.open, units: settings.units });
  const values = link.readingsFresh && link.readings ? link.readings.sensors || {} : {};
  const limit = limitText(link.readings, link.readingsFresh);
  const sensors = (link.robot && link.robot.sensors) || [];
  const imgLive = img.complete && img.naturalWidth > 0;

  // The reading cards, with the headset's own values (video fps, head-look,
  // its link time) when a driver is in; this page's own otherwise.
  const local = ui.driver
    ? { videoFps: ui.video_fps, videoLive: ui.video_live, pan: ui.pan || 0, headLook: ui.head_look }
    : { videoLive: imgLive, videoFps: "-", pan: link.statusFresh ? link.status.pan_deg || 0 : 0, headLook: false };
  const linkView = ui.driver ? Object.assign(Object.create(link), { linkMs: ui.link_ms }) : link;
  let cards = cardsFor({ cardList: settings.cards, link: linkView, local });
  if (!ui.driver) cards = cards.filter(c => c.id !== "headlook" && c.id !== "video");

  // Video border: tinted amber / red with the alert, like the headset.
  const tint = !settings.border_flash || alert.level === "none" ? pal.bezel
             : alert.level === "warn" ? (pal.dark ? 0x6b5300 : 0xf5d77a) : alert.level === "danger" ? (pal.dark ? 0x7f1d1d : 0xf4a3a3) : (pal.dark ? 0x3a3d44 : 0xc9ccd2);
  $("screen").style.setProperty("--bezel", hex(tint));

  // Status tags under the screen.
  const tag = (id, text, color) => { const el = $(id); el.textContent = text; el.style.setProperty("--dot", color); };
  const live = ui.driver ? ui.video_live : imgLive;
  tag("tag-video", live ? "LIVE" : "NO VIDEO", live ? pal.ok : pal.danger);
  const big = bigReading(sensors, values, alert, settings.units);
  tag("tag-rear", big ? (big.label === "REAR" ? "REAR " : big.label + " ") + big.text : "NO SENSORS",
      big ? levelColor(pal, big.level) : pal.off);
  tag("tag-controls", ui.driver ? "CONTROLS ON" : "CONTROLS OFF", ui.driver ? pal.ok : pal.danger);

  // Quick-button bar (shows which buttons are on in the headset).
  drawQuickBar($("bar").getContext("2d"), { headLook: !!ui.head_look, infoMode: ui.info_mode,
    settingsOpen: !!ui.settings_open, helpOpen: !!ui.help_open }, pal, null);

  // Dashboard or strip.
  if (ui.info_mode === 1) {
    drawDashboard($("dash").getContext("2d"), { robot: link.robot, values, alert, units: settings.units, cards,
      limit, page: ui.card_page || 0, overflow: settings.card_overflow, textScale: ts, hover: null }, pal);
  } else if (ui.info_mode === 2) {
    const items = [];
    if (big) items.push({ label: big.label[0] + big.label.slice(1).toLowerCase(), value: big.text, level: big.level });
    items.push({ label: "Reverse", value: limit.text, level: limit.level });
    items.push(...cards.filter(c => ["video", "link", "power"].includes(c.id)));
    drawStrip($("strip").getContext("2d"), items, pal, ts);
  }

  // Alert banner (hidden while the driver has settings open, like the headset).
  const showBanner = settings.banner && alert.level !== "none" && !ui.settings_open;
  bannerShow += ((showBanner ? 1 : 0) - bannerShow) * 0.5;
  if (showBanner) drawBanner($("banner").getContext("2d"), alert, pal, ts);
  const bannerY = -SH / 2 + (ui.info_mode === 2 ? 0.22 : 0.09) * M + (1 - bannerShow) * 0.05 * M;
  place($("banner"), 0, bannerY, 1.4 * M, 0.11 * M, bannerShow > 0.02);
  $("banner").style.opacity = bannerShow;

  // Help card and settings panel, when the driver has them open.
  if (ui.help_open) {
    drawHelpCard($("help").getContext("2d"), link.robot, settings.shortcuts, pal, null,
                 { pressed: new Set(ui.pressed || []), sticks: ui.sticks || {} });
  }
  if (ui.settings_open) {
    drawSettingsPanel($("settings").getContext("2d"), { tab: ui.settings_tab || "Display", page: ui.settings_page || 0,
      settings, robot: link.robot, shortcuts: resolveShortcuts(link.robot, settings.shortcuts) }, pal, null);
  }

  // Header: robot name and what the driver is doing.
  $("robot-name").textContent = link.robot ? link.robot.name : "Connecting...";
  $("driver-state").textContent = !link.open ? "" : !ui.driver ? "· No one is driving"
    : ui.in_mr ? "· Driver in the headset" : "· Driver on the begin screen";
  showNotice();
}

/** If the readings link isn't up after a few seconds, say why and how to fix it. */
function showNotice() {
  const el = $("notice");
  if (link.open || performance.now() - startedAt < 4000) { el.style.display = "none"; return; }
  el.style.display = "block";
  const host = location.hostname;
  if (location.protocol === "https:") {
    el.innerHTML = `<strong>Readings not connected.</strong> Either <code>drive_server.py</code> isn't running on
      the Pi, or this browser hasn't accepted the Pi's certificate for the readings yet.
      Open <a href="https://${host}:${CONFIG.drive_port}/" target="_blank" rel="noopener">https://${host}:${CONFIG.drive_port}</a>,
      choose <em>Advanced → Continue</em>, then come back (that page itself shows an error, which is fine).
      Or use <a href="http://${host}:8000/spectator">http://${host}:8000/spectator</a>, which needs no certificate.`;
  } else {
    el.innerHTML = `<strong>Readings not connected.</strong> Check that <code>drive_server.py</code> is running on
      the Pi (it prints "view-only readings for http pages on ws://0.0.0.0:${CONFIG.viewer_port}").`;
  }
}

draw();
setInterval(draw, 250);
window.addEventListener("resize", () => layout(currentUi()));

// Full screen: hides the browser and this page's header.
$("full").addEventListener("click", () => {
  document.body.classList.add("hide-header");
  document.documentElement.requestFullscreen().catch(() => {});
});
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) document.body.classList.remove("hide-header");
  layout(currentUi());
});
