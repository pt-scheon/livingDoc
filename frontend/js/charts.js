// Small dependency-free SVG charts drawn from the JSON API (replaces Foresight's matplotlib figures).
// Colours come from CSS classes (css/components.css), so light/dark themes just work.
import { shortDate } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null) el.append(k);
  return el;
}
const text = (str, attrs) => { const t = s("text", attrs); t.textContent = str; return t; };

function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1))));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/**
 * days: [{date, point, lo50, hi50, lo80, hi80, actual, actual_kind, is_future}]
 * festivals: [{name, start, end}], labels: {today, ariaLabel}
 */
export function forecastChart({ days, festivals = [], labels, lang }) {
  const W = 720, H = 300, L = 46, R = 12, T = 14, B = 28;
  const n = days.length;
  const x = (i) => L + (n <= 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const top = niceMax(Math.max(...days.map((d) => Math.max(d.hi80 ?? 0, d.actual ?? 0, d.point ?? 0))) * 1.05);
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": labels.ariaLabel, preserveAspectRatio: "xMidYMid meet" });

  for (let g = 0; g <= 4; g++) {
    const v = (top / 4) * g;
    svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "ch-grid" }), text(Math.round(v), { x: L - 6, y: y(v) + 4, class: "ch-axis", "text-anchor": "end" }));
  }
  for (const f of festivals) {
    const a = days.findIndex((d) => d.date >= f.start), bRev = [...days].reverse().findIndex((d) => d.date <= f.end);
    if (a < 0 || bRev < 0) continue;
    const b = n - 1 - bRev;
    if (b < a) continue;
    const half = (W - L - R) / Math.max(n - 1, 1) / 2;
    svg.append(s("rect", { x: x(a) - half, y: T, width: x(b) - x(a) + 2 * half, height: H - T - B, class: "ch-fest" }),
      (x(b) - x(a) + 2 * half) > 46 ? text(f.name, { x: x(a) - half + 3, y: T + 11, class: "ch-fest-label" }) : null);
  }
  const path = (pts) => pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
  const band = (lo, hi, cls) => {
    const up = days.map((d, i) => [x(i), y(d[hi])]), dn = days.map((d, i) => [x(i), y(d[lo])]).reverse();
    return s("path", { d: path([...up, ...dn]) + "Z", class: cls });
  };
  svg.append(band("lo80", "hi80", "ch-band80"), band("lo50", "hi50", "ch-band50"));
  svg.append(s("path", { d: path(days.map((d, i) => [x(i), y(d.point)])), class: "ch-line", fill: "none" }));

  const ti = days.findIndex((d) => d.is_future);
  if (ti > 0) svg.append(s("line", { x1: x(ti), x2: x(ti), y1: T, y2: H - B, class: "ch-today" }), text(labels.today, { x: x(ti) + 4, y: H - B - 4, class: "ch-axis" }));
  days.forEach((d, i) => {
    if (d.actual == null) return;
    svg.append(s("circle", { cx: x(i), cy: y(d.actual), r: 3.2, class: d.actual_kind === "real" ? "ch-real" : "ch-assumed" }));
  });
  const step = Math.max(1, Math.round(n / 7));
  days.forEach((d, i) => { if (i % step === 0) svg.append(text(shortDate(d.date, lang), { x: x(i), y: H - 8, class: "ch-axis", "text-anchor": "middle" })); });
  return svg;
}

/** Forecast vs reality for graded days: rows [{date, actual, point, lo80, hi80}] */
export function scoreChart({ rows, labels, lang }) {
  const W = 720, H = 240, L = 46, R = 12, T = 12, B = 28;
  const n = rows.length;
  const x = (i) => L + (n <= 1 ? (W - L - R) / 2 : (i / (n - 1)) * (W - L - R));
  const top = niceMax(Math.max(...rows.map((r) => Math.max(r.hi80 ?? 0, r.actual ?? 0))) * 1.05);
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": labels.ariaLabel });
  for (let g = 0; g <= 4; g++) {
    const v = (top / 4) * g;
    svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "ch-grid" }), text(Math.round(v), { x: L - 6, y: y(v) + 4, class: "ch-axis", "text-anchor": "end" }));
  }
  rows.forEach((r, i) => {
    const hit = r.actual >= r.lo80 && r.actual <= r.hi80;
    svg.append(s("line", { x1: x(i), x2: x(i), y1: y(r.hi80), y2: y(r.lo80), class: "ch-whisker" }),
      s("circle", { cx: x(i), cy: y(r.point), r: 2.6, class: "ch-pred" }),
      s("circle", { cx: x(i), cy: y(r.actual), r: 3.6, class: hit ? "ch-real" : "ch-miss" }));
  });
  const step = Math.max(1, Math.round(n / 7));
  rows.forEach((r, i) => { if (i % step === 0) svg.append(text(shortDate(r.date, lang), { x: x(i), y: H - 8, class: "ch-axis", "text-anchor": "middle" })); });
  return svg;
}

/** Cash from promises: days [{date, net_p10, net_p50, net_p90}] with a zero line. */
export function cashChart({ days, labels, lang }) {
  const W = 720, H = 260, L = 56, R = 12, T = 12, B = 28;
  const n = days.length;
  const x = (i) => L + (n <= 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const lo = Math.min(0, ...days.map((d) => d.net_p10)), hi = Math.max(1, ...days.map((d) => d.net_p90));
  const span = hi - lo || 1, pad = span * 0.06;
  const y = (v) => T + (1 - (v - (lo - pad)) / (span + 2 * pad)) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": labels.ariaLabel });
  for (let g = 0; g <= 4; g++) {
    const v = lo + (span / 4) * g;
    svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "ch-grid" }), text(Math.round(v).toLocaleString(), { x: L - 6, y: y(v) + 4, class: "ch-axis", "text-anchor": "end" }));
  }
  const path = (pts) => pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
  const up = days.map((d, i) => [x(i), y(d.net_p90)]), dn = days.map((d, i) => [x(i), y(d.net_p10)]).reverse();
  svg.append(s("path", { d: path([...up, ...dn]) + "Z", class: "ch-band80" }));
  svg.append(s("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "ch-zero" }));
  svg.append(s("path", { d: path(days.map((d, i) => [x(i), y(d.net_p50)])), class: "ch-line", fill: "none" }));
  const step = Math.max(1, Math.round(n / 7));
  days.forEach((d, i) => { if (i % step === 0) svg.append(text(shortDate(d.date, lang), { x: x(i), y: H - 8, class: "ch-axis", "text-anchor": "middle" })); });
  return svg;
}
