/*
  settings.js - every setting the website and the headset have, in ONE list.

  Used by:  pages/settings.html (the laptop page draws a form from SCHEMA)
            js/drive.js (the in-headset settings panel draws from SCHEMA too,
            and reads the values to size the screen, beep, etc.)
  Saved:    on the Pi, in settings.json, through camera_server.py's
            /api/settings - so a change on the laptop reaches the headset.
            The one exception is the web-page light/dark choice, which is
            per device (js/theme.js).

  To add a setting: add an entry to SCHEMA, then use settings.<key> where
  it matters. Both settings screens pick it up automatically.

  Entry fields:
    key, tab, label, hint   names and help text
    type   "toggle" (true/false), "choice" (one of `options`),
           "number" (min..max in `step`s, shown with `unit`),
           "cards" (the dashboard reading list), "shortcuts" (A/B/X/Y)
    default                 the starting value
*/

export const TABS = ["Display", "Readings", "Alerts", "Controls"];

export const SCHEMA = [
  // --- Display ---------------------------------------------------------------
  { key: "headset_theme", tab: "Display", type: "choice", label: "Headset panels",
    hint: "Dark is easier on the eyes over the passthrough view.",
    options: [["dark", "Dark"], ["light", "Light"]], default: "dark" },
  { key: "screen_width", tab: "Display", type: "number", label: "Video screen size",
    hint: "Width of the floating screen.", min: 1.0, max: 2.4, step: 0.2, unit: "m", default: 1.6 },
  { key: "screen_distance", tab: "Display", type: "number", label: "Screen distance",
    hint: "How far in front of you it appears.", min: 1.0, max: 3.0, step: 0.1, unit: "m", default: 1.8 },
  { key: "screen_drop", tab: "Display", type: "number", label: "Screen below eye level",
    hint: "Negative = above eye level.", min: -0.3, max: 0.5, step: 0.05, unit: "m", default: 0.1 },
  { key: "dashboard_place", tab: "Display", type: "choice", label: "Dashboard position",
    hint: "Where the full dashboard sits. Below works best with head-look.",
    options: [["below", "Below"], ["left", "Left"], ["right", "Right"]], default: "below" },
  { key: "dashboard_size", tab: "Display", type: "number", label: "Dashboard size",
    min: 0.6, max: 1.4, step: 0.1, unit: "x", default: 1.0 },
  { key: "text_size", tab: "Display", type: "choice", label: "Text size",
    options: [["small", "Small"], ["normal", "Normal"], ["large", "Large"]], default: "normal" },
  { key: "units", tab: "Display", type: "choice", label: "Distance units",
    options: [["in", "Inches"], ["cm", "Centimetres"]], default: "in" },
  { key: "colour_scheme", tab: "Display", type: "choice", label: "Colours",
    hint: "Colour-blind-safe uses blue / orange / red-orange for OK / warning / danger.",
    options: [["standard", "Standard"], ["colourblind", "Colour-blind safe"], ["contrast", "High contrast"]],
    default: "standard" },

  // --- Readings --------------------------------------------------------------
  { key: "cards", tab: "Readings", type: "cards", label: "Dashboard readings",
    hint: "Which readings show, in this order.", default: null },
  // ^ null = the default list (see defaultCards in readings.js)
  { key: "card_overflow", tab: "Readings", type: "choice", label: "When they don't all fit",
    options: [["pages", "Second page (flip with the pointer)"], ["shrink", "Smaller cards"]], default: "pages" },

  // --- Alerts ----------------------------------------------------------------
  { key: "banner", tab: "Alerts", type: "toggle", label: "Alert banner", hint: "Across the top of the video.", default: true },
  { key: "border_flash", tab: "Alerts", type: "toggle", label: "Screen border colour", hint: "Amber / red frame round the video.", default: true },
  { key: "beeps", tab: "Alerts", type: "toggle", label: "Beeps", default: true },
  { key: "volume", tab: "Alerts", type: "number", label: "Beep volume", min: 0.1, max: 1, step: 0.1, unit: "", default: 0.5 },
  { key: "beep_when", tab: "Alerts", type: "choice", label: "Beep",
    options: [["reversing", "Only while reversing"], ["always", "Always"]], default: "reversing" },
  { key: "vibration", tab: "Alerts", type: "toggle", label: "Controller vibration", default: true },
  { key: "vibration_strength", tab: "Alerts", type: "number", label: "Vibration strength", min: 0.2, max: 1, step: 0.1, unit: "", default: 0.8 },

  // --- Controls --------------------------------------------------------------
  { key: "speed_limit", tab: "Controls", type: "number", label: "Speed limit",
    hint: "Can only lower the robot's own limit.", min: 10, max: 100, step: 10, unit: "%", default: 100 },
  { key: "stick_deadzone", tab: "Controls", type: "number", label: "Stick dead zone",
    hint: "Ignore tiny stick wobble near the centre.", min: 0, max: 0.3, step: 0.02, unit: "", default: 0.12 },
  { key: "stick_curve", tab: "Controls", type: "number", label: "Stick response curve",
    hint: "Higher = finer control near the centre.", min: 1, max: 3, step: 0.25, unit: "", default: 2 },
  { key: "invert_throttle", tab: "Controls", type: "toggle", label: "Invert forward / back", default: false },
  { key: "invert_turn", tab: "Controls", type: "toggle", label: "Invert turning", default: false },
  { key: "headlook_smoothing", tab: "Controls", type: "number", label: "Head-look smoothing",
    hint: "Lower = smoother but laggier.", min: 0.05, max: 0.5, step: 0.05, unit: "", default: 0.15 },
  { key: "headlook_deadzone", tab: "Controls", type: "number", label: "Head-look dead zone",
    hint: "Head turns smaller than this leave the camera centred.", min: 0, max: 15, step: 1, unit: "°", default: 4 },
  { key: "headlook_limit", tab: "Controls", type: "number", label: "Head-look turn limit",
    hint: "The servo can't go past 70°.", min: 20, max: 70, step: 5, unit: "°", default: 70 },
  { key: "shortcuts", tab: "Controls", type: "shortcuts", label: "Button shortcuts",
    hint: "Give a Quest button a headset action. Buttons the robot uses aren't offered.", default: null },
  // ^ null = the robot's defaults (drive_server.py DEFAULT_SHORTCUTS)
];

/** Actions a button shortcut can do, and their names on screen. */
export const SHORTCUT_ACTIONS = [
  ["none", "Nothing"], ["headlook", "Head-look on/off"], ["dashboard", "Dashboard"],
  ["recenter", "Re-centre screen"], ["help", "Help card"], ["settings", "Settings"],
];

/** Every setting at its default value. */
export function defaults() {
  const d = {};
  for (const s of SCHEMA) d[s.key] = s.default;
  return d;
}

/**
 * Read the saved settings from the Pi, filling in defaults for anything
 * missing (so a new setting works even with an old settings.json).
 * @returns {Promise<object>}
 */
export async function loadSettings() {
  let saved = {};
  try { saved = await fetch("/api/settings", { cache: "no-store" }).then(r => r.json()); }
  catch (e) { /* Pi unreachable: use defaults */ }
  return Object.assign(defaults(), saved || {});
}

let saveTimer = null;
/**
 * Save settings to the Pi. Waits 0.4 s after the last change, so dragging
 * a value doesn't send dozens of saves.
 * @param {object} settings
 */
export function saveSettings(settings) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
                             body: JSON.stringify(settings) }).catch(() => {});
  }, 400);
}

/** Apply the colour scheme setting to the page (css/site.css reads it). */
export function applyScheme(settings) {
  document.documentElement.dataset.scheme = settings.colour_scheme || "standard";
}

/** Clamp and round a number to its setting's range and step. */
export function clampNumber(entry, value) {
  const v = Math.min(entry.max, Math.max(entry.min, value));
  return Math.round(v / entry.step) * entry.step;
}

/** How to show a setting's current value as text, e.g. "1.6 m", "On", "Inches". */
export function valueText(entry, value) {
  if (entry.type === "toggle") return value ? "On" : "Off";
  if (entry.type === "choice") return (entry.options.find(o => o[0] === value) || [, String(value)])[1];
  if (entry.type === "number") {
    const decimals = entry.step < 0.1 ? 2 : entry.step < 1 ? 1 : 0;
    return Number(value).toFixed(decimals) + (entry.unit ? (entry.unit === "°" || entry.unit === "%" ? "" : " ") + entry.unit : "");
  }
  return "";
}
