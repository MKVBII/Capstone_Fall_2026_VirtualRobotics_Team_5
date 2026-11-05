/*
  settings-page.js - builds the settings form (pages/settings.html) from the
  setting list in settings.js, and saves every change to the Pi.

  Connects to drive_server.py as a "viewer" only to learn the robot's sensor
  list (for the dashboard readings) and which buttons it leaves free (for
  the shortcuts). Without it, the page still works with the defaults.
*/

import { SCHEMA, TABS, SHORTCUT_ACTIONS, loadSettings, saveSettings, applyScheme, defaults, valueText } from "./settings.js";
import { cardCatalog, defaultCards } from "./readings.js";
import { freeButtons, resolveShortcuts } from "./controls.js";
import { DriveLink, loadConfig } from "./link.js";

const CONFIG = await loadConfig();
let settings = await loadSettings();
applyScheme(settings);
let tab = TABS[0];
const link = new DriveLink({ role: "viewer", port: CONFIG.drive_port, viewerPort: CONFIG.viewer_port,
                             onMessage: (m) => { if (m.type === "robot") draw(); } });

/** Save, re-apply the colours, and flash "Saved". */
function changed() {
  saveSettings(settings);
  applyScheme(settings);
  const s = document.getElementById("saved");
  s.style.opacity = 1; clearTimeout(changed.t); changed.t = setTimeout(() => { s.style.opacity = 0; }, 1200);
}

/** One row: label + hint on the left, the control on the right. */
function row(entry, controlHtml) {
  return `<div class="setting"><label for="s-${entry.key}">${entry.label}
    ${entry.hint ? `<span class="hint">${entry.hint}</span>` : ""}</label>${controlHtml}</div>`;
}

/** The control for one setting, as HTML. */
function control(e) {
  const v = settings[e.key];
  if (e.type === "toggle")
    return `<label class="switch"><input type="checkbox" id="s-${e.key}" data-key="${e.key}" ${v ? "checked" : ""}><span></span></label>`;
  if (e.type === "choice")
    return `<select id="s-${e.key}" data-key="${e.key}">${e.options.map(([val, name]) =>
      `<option value="${val}" ${val === v ? "selected" : ""}>${name}</option>`).join("")}</select>`;
  if (e.type === "number")
    return `<div class="row" style="flex-wrap:nowrap"><input type="range" id="s-${e.key}" data-key="${e.key}"
      min="${e.min}" max="${e.max}" step="${e.step}" value="${v}"><span class="value" style="min-width:70px;text-align:right">${valueText(e, v)}</span></div>`;
  return "";
}

/** Draw the tabs and the current tab's settings. */
function draw() {
  document.getElementById("tabs").innerHTML = TABS.map(t =>
    `<button role="tab" aria-selected="${t === tab}" data-tab="${t}">${t}</button>`).join("");
  const robot = link.robot;
  const html = SCHEMA.filter(e => e.tab === tab).map(e => {
    if (e.type === "cards") {
      const names = Object.fromEntries(cardCatalog(robot));
      const list = (settings.cards || defaultCards(robot)).filter(c => names[c.id]);
      return `<div class="setting" style="grid-template-columns:1fr"><div>${e.label}<span class="hint">${e.hint}</span></div>
        <ul class="card-list">${list.map((c, i) => `<li>
          <label class="switch"><input type="checkbox" data-card="${c.id}" ${c.on ? "checked" : ""} aria-label="Show ${names[c.id]}"><span></span></label>
          <span>${names[c.id]}</span>
          <button class="btn" data-up="${c.id}" ${i === 0 ? "disabled" : ""} aria-label="Move ${names[c.id]} up">↑</button>
          <button class="btn" data-down="${c.id}" ${i === list.length - 1 ? "disabled" : ""} aria-label="Move ${names[c.id]} down">↓</button>
        </li>`).join("")}</ul></div>`;
    }
    if (e.type === "shortcuts") {
      const sc = resolveShortcuts(robot, settings.shortcuts);
      const buttons = freeButtons(robot);
      return `<div class="setting" style="grid-template-columns:1fr"><div>${e.label}<span class="hint">${e.hint}
          ${robot ? "" : " (Connect to the robot to see which buttons it leaves free.)"}</span></div></div>` +
        buttons.map(b => `<div class="setting"><label for="sc-${b}">${b.toUpperCase()} button</label>
          <select id="sc-${b}" data-shortcut="${b}">${SHORTCUT_ACTIONS.map(([val, name]) =>
            `<option value="${val}" ${(sc[b] || "none") === val ? "selected" : ""}>${name}</option>`).join("")}</select></div>`).join("");
    }
    return row(e, control(e));
  }).join("");
  document.getElementById("panel").innerHTML = html;
}

// One listener for every control (they're redrawn often).
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-tab],[data-up],[data-down]");
  if (!t) return;
  if (t.dataset.tab) { tab = t.dataset.tab; return draw(); }
  const list = (settings.cards || defaultCards(link.robot)).map(c => ({ ...c }));
  const id = t.dataset.up || t.dataset.down, i = list.findIndex(c => c.id === id), j = t.dataset.up ? i - 1 : i + 1;
  if (i < 0 || j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  settings.cards = list; changed(); draw();
});
document.addEventListener("input", (ev) => {
  const el = ev.target;
  if (el.dataset.key) {
    const e = SCHEMA.find(s => s.key === el.dataset.key);
    settings[e.key] = e.type === "toggle" ? el.checked : e.type === "number" ? Number(el.value) : el.value;
    if (e.type === "number") el.nextElementSibling.textContent = valueText(e, settings[e.key]);
    changed();
  } else if (el.dataset.card) {
    const list = (settings.cards || defaultCards(link.robot)).map(c => ({ ...c }));
    list.find(c => c.id === el.dataset.card).on = el.checked;
    settings.cards = list; changed();
  } else if (el.dataset.shortcut) {
    const sc = { ...resolveShortcuts(link.robot, settings.shortcuts) };
    for (const b of freeButtons(link.robot)) if (!sc[b]) sc[b] = "none";
    sc[el.dataset.shortcut] = el.value;
    settings.shortcuts = sc; changed();
  } else if (el.id === "page-theme") {
    window.Theme.set(el.value);
  }
});

document.getElementById("reset").addEventListener("click", () => {
  settings = defaults(); changed(); draw();
});
document.getElementById("page-theme").value = window.Theme.choice();
draw();
