// App shell pieces: sidebar / bottom navigation, and the Today hero.
import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { money } from "../format.js";
import { dateTime } from "../format.js";

export const VIEWS = ["overview", "stock", "money", "forecast", "trust", "found"];
const ICONS = {
  overview: "M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z",
  stock: "M3 7l9-4 9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10",
  money: "M3 8h15a3 3 0 0 1 3 3v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M3 8V6a2 2 0 0 1 2-2h11 M16 14.5h2",
  forecast: "M4 19V5 M4 19h16 M8 15l3-4 3 2 5-6",
  trust: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
  found: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4-4",
};
const SVG = "http://www.w3.org/2000/svg";
function svg(d, cls) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); if (cls) s.setAttribute("class", cls);
  const p = document.createElementNS(SVG, "path"); p.setAttribute("d", d); s.append(p);
  return s;
}
export function brandMark() {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 40 40"); s.setAttribute("class", "brand-mark"); s.setAttribute("aria-hidden", "true");
  const add = (tag, attrs) => { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); s.append(n); };
  add("rect", { width: 40, height: 40, rx: 11, fill: "#2b3a9e" });
  for (const [x, y] of [[10, 10], [20, 10], [30, 10], [15, 20], [25, 20], [10, 30], [20, 30], [30, 30]]) add("circle", { cx: x, cy: y, r: 2.6, fill: "#f2b01e" });
  add("circle", { cx: 20, cy: 20, r: 3.2, fill: "#fff" });
  return s;
}

export function createNav(actions) {
  const title = h("h1"), sub = h("small");
  const nav = h("nav", { class: "nav", id: "main-nav" });
  const signout = h("button", { class: "btn small", type: "button", id: "signout", onclick: () => actions.signOut() });
  const foot = h("div", { class: "side-foot" }, signout);
  const el = h("aside", { class: "side" }, h("div", { class: "brand" }, brandMark(), h("div", {}, title, sub)), nav, foot);
  let key = "";
  return {
    el,
    update(s) {
      const risks = s.doc?.risks?.length || 0;
      const sig = JSON.stringify([s.lang, s.view, risks, s.auth]);
      if (sig === key) return;
      key = sig;
      const L = (k, v) => t(s.lang, k, v);
      title.textContent = L("title"); sub.textContent = L("brand_sub");
      nav.setAttribute("aria-label", L("view_nav"));
      replace(nav, VIEWS.map((v) => h("a", { href: `#/${v}`, "data-view": v, "aria-current": s.view === v ? "page" : null },
        svg(ICONS[v]), h("span", { class: "l" }, L(`nav_${v}`)), v === "overview" && risks ? h("span", { class: "badge-n", "aria-label": String(risks) }, risks) : null)));
      signout.textContent = L("signout"); foot.hidden = !s.auth.required;
    },
  };
}

export function createHero(actions) {
  const el = h("section", { class: "hero", id: "hero", "aria-labelledby": "hero-h" });
  let key = "";
  // headline strings carry <b> markers; turn them into real nodes without innerHTML
  const rich = (str) => str.split(/(<b>.*?<\/b>)/).filter(Boolean).map((p) => (p.startsWith("<b>") ? h("b", {}, p.slice(3, -4)) : p));
  return {
    el,
    update(s) {
      if (!s.doc) return;
      const d = s.doc;
      const sig = JSON.stringify([s.lang, s.branch, d.generated_at, d.risks.length, d.cash.pending_total, d.cash.collected_today]);
      if (sig === key) return;
      key = sig;
      const L = (k, v) => t(s.lang, k, v);
      const n = d.risks.length;
      const low = d.inventory.filter((i) => i.status !== "ok").length;
      const open = d.promises.filter((p) => !p.done).length;
      const f = d.forecast.find((x) => x.festival_date) || null;
      let days = null;
      if (f) { const [y, m, dd] = f.festival_date.split("-").map(Number); days = Math.round((new Date(y, m - 1, dd) - new Date(new Date().setHours(0, 0, 0, 0))) / 86400000); }
      const festLine = f && days != null ? (days <= 0 ? L("hero_festival_today", { name: f.festival_name }) : L("hero_festival", { name: f.festival_name, n: days })) : L("hero_no_festival");
      const money_ = (v) => money(v, d.currency, s.lang);
      replace(el,
        h("p", { class: "hero-date" }, `${s.branch} · ${dateTime(d.generated_at, s.lang)}`),
        h("h2", { id: "hero-h" }, rich(n === 0 ? L("hero_calm") : n === 1 ? L("hero_one") : L("hero_many", { n }))),
        h("p", { class: "hero-sub" }, festLine),
        h("div", { class: "kpis" },
          h("div", { class: "kpi" }, h("b", {}, money_(d.cash.pending_total)), h("span", {}, L("kpi_collect"))),
          h("div", { class: "kpi" }, h("b", {}, money_(d.cash.collected_today)), h("span", {}, L("kpi_today"))),
          h("div", { class: `kpi ${low ? "alert" : ""}` }, h("b", {}, String(low)), h("span", {}, L("kpi_low"))),
          h("div", { class: "kpi" }, h("b", {}, String(open)), h("span", {}, L("kpi_promises")))),
        h("div", { class: "hero-actions" },
          h("button", { class: "btn haldi", type: "button", id: "hero-note", onclick: () => actions.focusNote() }, "✍️ " + L("hero_cta_note")),
          h("a", { class: "btn", href: "#/forecast", id: "hero-forecast" }, L("hero_cta_forecast"))));
    },
  };
}
