/*
  controls.js - what every Quest controller button does, and a drawing of it.

  Used by:  the begin screen (controller drawing) and drive.js (button
            shortcuts, and the in-headset help card).
  Built from: the robot's "controls" list and default shortcuts (from
            drive_server.py), plus the shortcuts chosen in Settings. So a
            drone that uses A/B for take-off/land shows those, and gets no
            headset shortcuts on them.
*/

import { SHORTCUT_ACTIONS } from "./settings.js";

const BUTTONS = ["a", "b", "x", "y"];

/**
 * Which headset action each free button does.
 * @param {object|null} robot      the robot message
 * @param {object|null} chosen     settings.shortcuts (null = robot defaults)
 * @returns {object} e.g. {x: "headlook", a: "dashboard"} (buttons the robot
 *   uses are never included)
 */
export function resolveShortcuts(robot, chosen) {
  const used = new Set(((robot && robot.controls) || []).map(c => c.input));
  const base = chosen || (robot && robot.shortcuts) || {};
  const out = {};
  for (const b of BUTTONS) if (!used.has(b) && base[b] && base[b] !== "none") out[b] = base[b];
  return out;
}

/** The buttons a shortcut may be put on (the ones the robot leaves free). */
export function freeButtons(robot) {
  const used = new Set(((robot && robot.controls) || []).map(c => c.input));
  return BUTTONS.filter(b => !used.has(b));
}

/** On-screen name of a shortcut action, e.g. "Head-look on/off". */
export function actionName(action) {
  return (SHORTCUT_ACTIONS.find(a => a[0] === action) || [, action])[1];
}

/**
 * Every control on both controllers, with what it does.
 * @returns {{left: Array<{key, name, label}>, right: Array<{key, name, label}>}}
 */
export function controlsFor(robot, chosenShortcuts) {
  const robotLabel = {};
  for (const c of (robot && robot.controls) || []) robotLabel[c.input] = c.label;
  const sc = resolveShortcuts(robot, chosenShortcuts);
  const button = (b) => robotLabel[b] || (sc[b] ? actionName(sc[b]) : "Not used");
  // Order matters: the list is numbered 1, 2, 3... to match controllerSVG's markers.
  const common = [
    { key: "grip", name: "Grip", label: "Bring the screen back in front of you" },
    { key: "trigger", name: "Trigger", label: "Point at a button or panel and pull to click" },
  ];
  return {
    left: [
      { key: "stick", name: "Thumbstick", label: robotLabel.left_stick || "Not used" },
      { key: "x", name: "X", label: button("x") },
      { key: "y", name: "Y", label: button("y") },
      ...common,
    ],
    right: [
      { key: "stick", name: "Thumbstick", label: robotLabel.right_stick || "Not used" },
      { key: "a", name: "A", label: button("a") },
      { key: "b", name: "B", label: button("b") },
      ...common,
      { key: "meta", name: "Meta button", label: "Leave mixed reality (the robot stops)" },
    ],
  };
}

/**
 * A simple drawing of one Quest controller seen from above, with numbered
 * markers matching the list next to it.
 * @param {"left"|"right"} hand
 * @returns {string} SVG markup (uses currentColor, so it follows the theme)
 */
export function controllerSVG(hand) {
  const right = hand === "right";
  const m = (x, y, n) => `<g><circle cx="${x}" cy="${y}" r="13" fill="var(--accent)"/>` +
    `<text x="${x}" y="${y + 5}" text-anchor="middle" font-size="14" font-weight="700" fill="var(--accent-text)">${n}</text></g>`;
  // Body: a rounded grip with a ring on top. Mirrored for the left hand.
  const body = `<path d="M60 40 Q60 18 90 16 L130 16 Q160 18 160 44 L150 150 Q146 176 118 178 L102 178 Q74 176 70 150 Z"
     fill="var(--surface-2)" stroke="currentColor" stroke-width="2.5"/>
    <ellipse cx="110" cy="30" rx="62" ry="22" fill="none" stroke="currentColor" stroke-width="2.5" opacity="0.6"/>`;
  const stick = `<circle cx="95" cy="62" r="17" fill="none" stroke="currentColor" stroke-width="2.5"/><circle cx="95" cy="62" r="8" fill="currentColor"/>`;
  const b1 = `<circle cx="132" cy="84" r="9" fill="none" stroke="currentColor" stroke-width="2.5"/>`;
  const b2 = `<circle cx="126" cy="58" r="9" fill="none" stroke="currentColor" stroke-width="2.5"/>`;
  const markers = [m(95, 62, 1), m(150, 96, 2), m(146, 46, 3), m(66, 122, 4), m(82, 168, 5)];
  if (right) markers.push(m(110, 112, 6));
  const meta = right ? `<circle cx="110" cy="112" r="6" fill="currentColor" opacity="0.7"/>` : "";
  return `<svg viewBox="0 0 220 200" role="img" aria-label="${hand} Quest controller" style="color:var(--muted);max-width:220px;width:100%">
    <g ${right ? "" : 'transform="translate(220 0) scale(-1 1)"'}>${body}${stick}${b1}${b2}${meta}</g>
    ${right ? markers.join("") : markers.map(s => s.replace(/cx="(\d+)"/, (_, x) => `cx="${220 - x}"`).replace(/x="(\d+)" y/, (_, x) => `x="${220 - x}" y`)).join("")}
  </svg>`;
}
