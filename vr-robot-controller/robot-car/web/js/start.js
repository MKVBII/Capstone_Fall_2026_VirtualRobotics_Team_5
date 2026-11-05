/*
  start.js - the start screen's live parts (pages/index.html):
  the robot status card and the session log.

  Connects to drive_server.py as a "viewer" (js/link.js): it only watches,
  so opening or closing this page never affects driving.
*/

import { DriveLink, loadConfig } from "./link.js";
import { loadSettings, applyScheme } from "./settings.js";
import { checklistFor } from "./readings.js";

const CONFIG = await loadConfig();
const settings = await loadSettings();
applyScheme(settings);
const link = new DriveLink({ role: "viewer", port: CONFIG.drive_port, viewerPort: CONFIG.viewer_port });
const thumb = document.querySelector(".thumb");

/** Is the camera picture showing? (An <img> showing MJPEG has a size once it has a picture.) */
function videoLive() { return thumb.complete && thumb.naturalWidth > 0; }

/** Redraw the status card. */
function drawStatus() {
  const rows = checklistFor(link, { videoLive: videoLive(), videoFps: "-" }, settings.units)
    .map(r => r.label === "Video" ? { ...r, value: videoLive() ? "picture arriving" : "no picture",
                                      level: videoLive() ? "ok" : "danger" } : r);
  document.getElementById("status").innerHTML = rows.map(r =>
    `<li><span class="dot ${r.level}"></span><span>${r.label}</span><span class="value">${r.value}</span>
     ${r.level === "danger" ? `<span class="fix">${r.fix}</span>` : ""}</li>`).join("");
  const worst = rows.some(r => r.level === "danger") ? "danger" : rows.some(r => r.level === "warn") ? "warn" : "ok";
  document.getElementById("ready").innerHTML = `<span class="dot ${worst}"></span><span>${
    worst === "ok" ? "Ready" : worst === "warn" ? "Check the warnings" : "Not ready"}</span>`;
  document.getElementById("robot-name").textContent = link.robot ? link.robot.name
    : link.open ? "Connected, waiting for the robot..." : "Can't reach drive_server.py - is it running on the Pi?";

  // Session log button.
  const logging = link.statusFresh ? link.status.logging : null;
  const b = document.getElementById("log-toggle");
  b.disabled = !link.open;
  b.textContent = logging ? "Stop recording" : "Start recording";
  b.classList.toggle("danger", !!logging);
  b.classList.toggle("primary", !logging);
  document.getElementById("log-state").textContent = logging ? "Recording to " + logging : link.open ? "" : "Needs drive_server.py";
}
setInterval(drawStatus, 500);

document.getElementById("log-toggle").addEventListener("click", () => {
  const logging = link.statusFresh ? link.status.logging : null;
  link.send({ type: "log", on: !logging });
  setTimeout(drawLogs, 1500);
});

/** List the saved logs, newest first, with download links. */
async function drawLogs() {
  let logs = [];
  try { logs = await fetch("/api/logs", { cache: "no-store" }).then(r => r.json()); } catch (e) { /* ignore */ }
  document.getElementById("logs").innerHTML = logs.length
    ? logs.slice(0, 10).map(l => `<li><a href="/logs/${encodeURIComponent(l.name)}" download>${l.name}</a>
        <span class="muted">${l.size_kb} KB</span></li>`).join("")
    : `<li class="muted">No recordings yet.</li>`;
}
drawLogs();
setInterval(drawLogs, 5000);
