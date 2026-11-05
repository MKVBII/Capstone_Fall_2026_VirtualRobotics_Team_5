/*
  hud.js - draws the dashboard, the alert banner and the strip onto a 2D
  canvas.

  Used by:  drive.js (the canvases become textures on 3D panels in the
            headset) and spectator.html (the same drawings on a normal page,
            so the audience sees exactly what the driver sees).
  Data:     comes from readings.js (alertFor, cardsFor, limitText) and the
            robot's sensor list, so extra sensors are drawn automatically:
            every "distance" sensor gets arcs at its position round the
            robot outline, every "edge" sensor a strip on its side.

  Every function takes a palette from readings.js palette(), so light and
  dark mode and the colour-blind scheme work everywhere.
*/

import { LEVEL_COLOR, showDistance, where } from "./readings.js";

const FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif";

/** Fill a rounded rectangle. */
function roundRect(ctx, x, y, w, h, r, fill, stroke) {
  ctx.beginPath(); ctx.roundRect(x, y, w, h, r);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 3; ctx.stroke(); }
}

/** Set a font: weight, size in px (times the text-size scale). */
function font(ctx, weight, px, scale = 1) { ctx.font = `${weight} ${Math.round(px * scale)}px ${FONT}`; }

/** Shrink text until it fits `maxWidth`, starting from `px`. Returns the size used. */
function fitText(ctx, text, weight, px, maxWidth, min = 20) {
  let size = px;
  do { ctx.font = `${weight} ${size}px ${FONT}`; size -= 4; }
  while (ctx.measureText(text).width > maxWidth && size > min);
  return size + 4;
}

/** A palette colour for a level name ("ok", "warn", "danger", "off", "text"). */
export function levelColor(pal, level) { return level === "text" ? pal.text : pal[level] || pal.text; }

// Direction each position's arcs face (canvas angles: 0 = right, PI/2 = down).
const FACING = {
  rear: Math.PI / 2, front: -Math.PI / 2, left: Math.PI, right: 0,
  rear_left: 3 * Math.PI / 4, rear_right: Math.PI / 4,
  front_left: -3 * Math.PI / 4, front_right: -Math.PI / 4,
};

/** The point on the robot outline where a sensor at `position` sits. */
function anchor(position, cx, cy, w, h) {
  const dx = { left: -1, right: 1, rear_left: -1, front_left: -1, rear_right: 1, front_right: 1 }[position] || 0;
  const dy = { rear: 1, front: -1, rear_left: 1, rear_right: 1, front_left: -1, front_right: -1 }[position] || 0;
  return [cx + dx * w / 2, cy + dy * h / 2];
}

/**
 * The top-down parking graphic: robot outline, arcs per distance sensor,
 * a strip per edge sensor.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} cx  centre x   @param {number} cy  centre y
 * @param {number} scale  1 = a 120 x 190 px robot
 * @param {Array} sensors  the robot's sensor list
 * @param {object} values  readings.sensors (id -> {cm, state}), or {} if stale
 * @param {object} pal     palette
 */
export function drawParking(ctx, cx, cy, scale, sensors, values, pal) {
  const w = 120 * scale, h = 190 * scale;
  // The robot: body, wheels, and a small arrow showing which way is front.
  roundRect(ctx, cx - w / 2, cy - h / 2, w, h, 22 * scale, pal.card, pal.muted);
  ctx.fillStyle = pal.muted;
  for (const sx of [-1, 1]) {
    roundRect(ctx, cx + sx * (w / 2 + 2 * scale) - (sx > 0 ? 0 : 14 * scale), cy + h * 0.12, 14 * scale, 46 * scale, 4 * scale, pal.muted);
  }
  ctx.beginPath();
  ctx.moveTo(cx, cy - h / 2 + 18 * scale);
  ctx.lineTo(cx - 14 * scale, cy - h / 2 + 40 * scale);
  ctx.lineTo(cx + 14 * scale, cy - h / 2 + 40 * scale);
  ctx.closePath(); ctx.fillStyle = pal.muted; ctx.fill();

  for (const s of sensors) {
    const v = values[s.id];
    const state = v ? v.state : "fault";
    const [ax, ay] = anchor(s.position, cx, cy, w, h);
    if (s.kind === "edge") {
      // A strip just inside the outline on that side.
      const color = levelColor(pal, state === "edge" ? "danger" : state === "fault" ? "off" : "ok");
      const horizontal = !["left", "right"].includes(s.position);
      const t = 10 * scale;
      if (horizontal) roundRect(ctx, cx - w / 2 + 14 * scale, ay - (ay > cy ? t + 6 * scale : -6 * scale), w - 28 * scale, t, t / 2, color);
      else roundRect(ctx, ax - (ax > cx ? t + 6 * scale : -6 * scale), cy - h / 2 + 20 * scale, t, h - 40 * scale, t / 2, color);
    } else if (s.kind === "distance") {
      // Three arcs facing outward. More light up, and turn red, as it gets closer.
      let lit = 0, color = pal.track;
      if (state === "slow" && v.cm != null && s.slow_cm != null) {
        const f = Math.max(0, Math.min(1, (s.slow_cm - v.cm) / (s.slow_cm - (s.stop_cm || 0))));
        lit = Math.min(3, 1 + Math.floor(f * 3)); color = pal.warn;
      } else if (state === "slow") { lit = 1; color = pal.warn; }
      else if (state === "stop") { lit = 3; color = pal.danger; }
      const face = FACING[s.position] ?? Math.PI / 2;
      [30, 54, 78].forEach((r, i) => {
        ctx.beginPath();
        ctx.arc(ax, ay, (r + 6) * scale, face - 0.62, face + 0.62);
        ctx.lineWidth = 13 * scale; ctx.lineCap = "round";
        ctx.strokeStyle = state === "fault" ? pal.off : i < lit ? color : pal.track;
        ctx.setLineDash(state === "fault" ? [6 * scale, 10 * scale] : []);
        ctx.stroke();
      });
      ctx.setLineDash([]);
    }
  }
}

/**
 * The distance to show in big text under the graphic: the sensor that's
 * raising the alert, else the nearest distance sensor.
 * @returns {{label: string, text: string, level: string} | null}
 */
export function bigReading(sensors, values, alert, units) {
  const dist = sensors.filter(s => s.kind === "distance");
  const edge = sensors.find(s => s.kind === "edge" && values[s.id] && values[s.id].state === "edge");
  if (edge) return { label: edge.name.toUpperCase(), text: "EDGE!", level: "danger" };
  let pick = alert && alert.sensor ? dist.find(s => s.id === alert.sensor) : null;
  if (!pick) pick = dist.slice().sort((a, b) => ((values[a.id] || {}).cm ?? 1e9) - ((values[b.id] || {}).cm ?? 1e9))[0];
  if (!pick) return null;
  const v = values[pick.id];
  if (!v) return { label: pick.name.toUpperCase(), text: "NO DATA", level: "off" };
  if (v.state === "fault") return { label: pick.name.toUpperCase(), text: "SENSOR ?", level: "off" };
  if (v.cm == null || v.cm >= 150) return { label: pick.name.toUpperCase(), text: "CLEAR", level: "ok" };
  return { label: pick.name.toUpperCase(), text: showDistance(v.cm, units), level: LEVEL_COLOR[v.state] || "ok" };
}

/**
 * The full dashboard. Canvas is meant to be 1600 x 520 px.
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} d
 *   robot, values (readings.sensors or {}), alert, units, cards (from
 *   cardsFor), limit (from limitText), page (card page index), overflow
 *   ("pages" | "shrink"), textScale (0.85 / 1 / 1.2), hover (id of the
 *   page button the pointer is on, or null)
 * @param {object} pal  palette
 * @returns {Array<{id, x, y, w, h}>} clickable areas (the Back / Next page
 *   buttons), with .pages = how many pages of cards there are
 */
export function drawDashboard(ctx, d, pal) {
  const W = ctx.canvas.width, H = ctx.canvas.height, ts = d.textScale || 1;
  ctx.clearRect(0, 0, W, H);
  roundRect(ctx, 0, 0, W, H, 40, pal.panel);
  ctx.textBaseline = "middle";
  const hits = [];
  const sensors = (d.robot && d.robot.sensors) || [];
  const hasGraphic = sensors.some(s => s.kind === "distance" || s.kind === "edge");

  // Left: the parking graphic and the big distance.
  let x0 = 40;
  if (hasGraphic) {
    drawParking(ctx, 250, 200, 1, sensors, d.values, pal);
    const big = bigReading(sensors, d.values, d.alert, d.units);
    if (big) {
      ctx.textAlign = "center";
      font(ctx, 600, 30, ts); ctx.fillStyle = pal.muted; ctx.fillText(big.label, 250, 400);
      fitText(ctx, big.text, 800, Math.round(76 * ts), 420);
      ctx.fillStyle = levelColor(pal, big.level); ctx.fillText(big.text, 250, 462);
    }
    ctx.fillStyle = pal.panelEdge; ctx.fillRect(500, 36, 3, H - 72);
    x0 = 540;
  }
  const x1 = W - 40, rw = x1 - x0;

  // Top right: how much reverse is allowed.
  ctx.textAlign = "left";
  font(ctx, 600, 32, ts); ctx.fillStyle = pal.muted; ctx.fillText("Reverse allowed", x0, 62);
  ctx.textAlign = "right"; font(ctx, 800, 40, ts);
  ctx.fillStyle = levelColor(pal, d.limit.level); ctx.fillText(d.limit.text, x1, 62);
  roundRect(ctx, x0, 96, rw, 22, 11, pal.track);
  if (d.limit.value > 0) roundRect(ctx, x0, 96, Math.max(22, rw * d.limit.value), 22, 11, levelColor(pal, d.limit.level));

  // The reading cards: 3 x 2 per page, or 4 x 3 smaller ones.
  const shrink = d.overflow === "shrink";
  const cols = shrink ? 4 : 3, rows = shrink ? 3 : 2, per = cols * rows, gap = 16;
  const pages = Math.max(1, Math.ceil(d.cards.length / per));
  const page = Math.min(d.page || 0, pages - 1);
  const top = 146, bottom = pages > 1 ? H - 78 : H - 32;
  const cw = (rw - gap * (cols - 1)) / cols, ch = (bottom - top - gap * (rows - 1)) / rows;
  d.cards.slice(page * per, page * per + per).forEach((c, i) => {
    const cx = x0 + (i % cols) * (cw + gap), cy = top + Math.floor(i / cols) * (ch + gap);
    roundRect(ctx, cx, cy, cw, ch, 18, pal.card);
    ctx.textAlign = "left";
    font(ctx, 500, shrink ? 24 : 28, ts); ctx.fillStyle = pal.muted; ctx.fillText(c.label, cx + 20, cy + ch * 0.32);
    ctx.fillStyle = levelColor(pal, c.level);
    fitText(ctx, c.value, 800, Math.round((shrink ? 34 : 46) * ts), cw - 40);
    ctx.fillText(c.value, cx + 20, cy + ch * 0.7);
  });

  // Page buttons, when the cards don't fit on one page:  ‹ Back   1 / 2   Next ›
  // A button that can't be used (Back on page 1, Next on the last page) is
  // drawn faded and isn't clickable.
  hits.pages = pages;
  if (pages > 1) {
    const by = H - 64, bw = 130, bh = 48, gapX = 130;
    const nextX = x1 - bw, backX = nextX - gapX - bw;
    ctx.textAlign = "center";
    font(ctx, 600, 26, ts); ctx.fillStyle = pal.muted;
    ctx.fillText(`${page + 1} / ${pages}`, nextX - gapX / 2, by + bh / 2);
    const pageButton = (id, x, text, usable) => {
      const on = usable && d.hover === id;
      ctx.globalAlpha = usable ? 1 : 0.35;
      roundRect(ctx, x, by, bw, bh, 14, on ? pal.track : pal.card, on ? pal.text : pal.panelEdge);
      font(ctx, 700, 26, ts); ctx.fillStyle = pal.text; ctx.fillText(text, x + bw / 2, by + bh / 2);
      ctx.globalAlpha = 1;
      if (usable) hits.push({ id, x, y: by, w: bw, h: bh });
    };
    pageButton("page-prev", backX, "‹ Back", page > 0);
    pageButton("page-next", nextX, "Next ›", page < pages - 1);
  }
  return hits;
}

/**
 * The alert banner. Canvas is meant to be 1400 x 110 px.
 * @param {object} alert  from readings.js alertFor()
 */
export function drawBanner(ctx, alert, pal, textScale = 1) {
  const W = ctx.canvas.width, H = ctx.canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (alert.level === "none") return;
  const bg = alert.level === "warn" ? pal.warn : alert.level === "danger" ? pal.danger : pal.off;
  const fg = alert.level === "warn" ? "#1d1600" : "#ffffff";
  roundRect(ctx, 4, 4, W - 8, H - 8, (H - 8) / 2, bg);
  // A warning triangle with "!".
  const ix = 70, iy = H / 2;
  ctx.beginPath(); ctx.moveTo(ix, iy - 28); ctx.lineTo(ix + 32, iy + 24); ctx.lineTo(ix - 32, iy + 24); ctx.closePath();
  ctx.fillStyle = fg; ctx.fill();
  ctx.fillStyle = bg; font(ctx, 900, 34); ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("!", ix, iy + 6);
  ctx.textAlign = "left"; ctx.fillStyle = fg;
  fitText(ctx, alert.text, 800, Math.round(50 * textScale), W - 170);
  ctx.fillText(alert.text, 124, H / 2 + 2);
}

/**
 * The strip: a few readings across the top of the video. 1920 x 144 px.
 * @param {Array<{label, value, level}>} items
 */
export function drawStrip(ctx, items, pal, textScale = 1) {
  const W = ctx.canvas.width, H = ctx.canvas.height;
  ctx.clearRect(0, 0, W, H);
  roundRect(ctx, 0, 0, W, H, 30, pal.panel);
  ctx.textBaseline = "middle"; ctx.textAlign = "left";
  // Measure everything first, shrinking the text until it all fits.
  let scale = textScale, widths, total;
  const labelFont = () => `500 ${Math.round(38 * scale)}px ${FONT}`;
  const valueFont = () => `800 ${Math.round(50 * scale)}px ${FONT}`;
  for (;;) {
    widths = items.map(({ label, value }) => {
      ctx.font = labelFont(); const lw = ctx.measureText(label).width + 14 * scale;
      ctx.font = valueFont(); return [lw, lw + ctx.measureText(value).width];
    });
    total = widths.reduce((sum, w) => sum + w[1], 0);
    if (total + 40 * (items.length - 1) <= W - 60 || scale < 0.5) break;
    scale -= 0.05;
  }
  const gap = (W - 60 - total) / Math.max(1, items.length - 1);
  let x = 30;
  items.forEach(({ label, value, level }, i) => {
    ctx.fillStyle = pal.muted; ctx.font = labelFont(); ctx.fillText(label, x, H / 2);
    ctx.fillStyle = levelColor(pal, level); ctx.font = valueFont(); ctx.fillText(value, x + widths[i][0], H / 2);
    x += widths[i][1] + gap;
  });
}

/** Re-exported for pages that describe a sensor's position in words. */
export { where };
