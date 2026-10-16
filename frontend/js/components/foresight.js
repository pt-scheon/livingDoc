// "Forecast & Pricing" section: demand forecast, price plan, owner inputs, scorecard, setup.
// All numbers come from the /api/forecast family of routes; assumptions are labelled wherever they are used.
import { api } from "../api.js";
import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { money, qty, shortDate } from "../format.js";
import { toast } from "../toast.js";
import { forecastChart, scoreChart } from "../charts.js";

const TABS = ["forecast", "pricing", "owner", "score", "setup"];
const pad = (n) => String(n).padStart(2, "0");
const isoDay = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (iso, n) => { const [y, m, d] = iso.split("-").map(Number); return isoDay(new Date(y, m - 1, d + n)); };
const ord = (n, lang) => Number(n).toLocaleString({ en: "en-IN", hi: "hi-IN", gu: "gu-IN" }[lang] || "en-IN", { maximumFractionDigits: 0 });
const one = (n, lang) => Number(n).toLocaleString({ en: "en-IN", hi: "hi-IN", gu: "gu-IN" }[lang] || "en-IN", { maximumFractionDigits: 1 });
const pctText = (v, signed = false, digits = 0) => `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

export function createForesight() {
  const heading = h("h2", { id: "fp-h" });
  const banners = h("div", { class: "fp-banners" });
  const tabBar = h("div", { class: "seg fp-tabs", role: "tablist" });
  const panel = h("div", { class: "fp-panel", role: "tabpanel", tabindex: "0" });
  const el = h("section", { "aria-labelledby": "fp-h", id: "fp-section" }, heading, banners, tabBar, panel);

  let S = { lang: "en", branch: "", tab: "forecast", horizon: 28, pricingDays: 1, explainDate: null, data: {}, busy: false, error: "", note: "" };
  let started = false, gen = 0, key = "";

  const L = (k, v) => t(S.lang, k, v);
  const cur = () => "₹";

  // ---------------- data ----------------
  function invalidate() { S.data = {}; gen++; }
  async function ensure(name, loader) {
    if (S.data[name] !== undefined) return S.data[name];
    const g = gen;
    const v = await loader();
    if (g === gen) S.data[name] = v;
    return v;
  }
  async function show(tab = S.tab) {
    S.tab = tab; S.error = "";
    renderTabs();
    const g = gen;
    replace(panel, h("p", { class: "muted", role: "status" }, L("fp_loading")));
    try {
      const nodes = await build(tab);
      if (g !== gen || tab !== S.tab) return;
      replace(panel, nodes);
      renderBanners();
    } catch (err) {
      if (g !== gen) return;
      replace(panel, h("p", { class: "card", role: "alert" }, `${L("fp_error")}: ${err.message}`));
    }
  }
  async function act(fn, okMsg) {
    if (S.busy) return;
    S.busy = true;
    try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
    catch (err) { toast(err.message, "error"); return null; }
    finally { S.busy = false; }
  }
  async function mutated(tab = S.tab) { invalidate(); await show(tab); }

  // ---------------- small ui helpers ----------------
  const fld = (label, input, hint) => h("label", { class: "field" }, label, input, hint ? h("span", { class: "muted", style: "font-size:.75rem" }, hint) : null);
  const num = (v, o = {}) => h("input", { type: "number", step: "any", value: v ?? "", ...o });
  const btn = (label, onclick, cls = "") => h("button", { class: `btn ${cls}`, type: "button", onclick }, label);
  const stat = (label, val, sub) => h("div", { class: "stat" }, h("b", {}, val), h("span", {}, label), sub ? h("span", { class: "muted", style: "display:block" }, sub) : null);
  const srcLabel = (s) => L(`fp_src_${s}`);
  const section = (title, ...kids) => h("div", { class: "fp-block" }, h("h3", {}, title), ...kids);

  function renderTabs() {
    replace(tabBar, TABS.map((id) => h("button", {
      type: "button", role: "tab", id: `fp-tab-${id}`, "aria-pressed": String(S.tab === id), "aria-selected": String(S.tab === id), "data-tab": id,
      onclick: () => { if (S.tab !== id) show(id); },
    }, L(`fp_tab_${id}`))));
  }
  function renderBanners() {
    const fcst = S.data.forecast;
    const demo = fcst?.meta?.actuals?.demo || 0;
    replace(banners,
      h("p", { class: "banner info", id: "fp-assumed" }, "ℹ️ ", L("fp_assumed_banner")),
      demo ? h("p", { class: "banner warn", id: "fp-demo-banner", role: "alert" }, "🧪 ", L("fp_demo_banner", { n: demo }), " ",
        btn(L("fp_clear_demo"), () => act(() => api.fpClearDemo(S.branch), L("fp_saved")).then(() => mutated()), "small")) : null);
  }

  function reasonText(r) {
    const p = r.reason_params || {};
    const base = L(`fp_r_${r.reason_code}`, {
      demand: Math.round(p.demand ?? 0), cap: Math.round(p.cap ?? 0), idx: (p.idx ?? 1).toFixed(2),
      pct: pctText(p.pct ?? 0), score: (p.score ?? 0).toFixed(1), name: p.name ?? r.product });
    return [base, ...(r.reason_flags || []).map((f) => L(`fp_f_${f}`))].join(" ");
  }
  const driverName = (d) => (d.startsWith("You: ") ? L("fp_drv_you", { name: d.slice(5) }) : L(`fp_drv_${d}`));

  // ---------------- tab builders ----------------
  async function build(tab) {
    if (tab === "forecast") return buildForecast();
    if (tab === "pricing") return buildPricing();
    if (tab === "owner") return buildOwner();
    if (tab === "score") return buildScore();
    return buildSetup();
  }

  async function loadForecast() { return ensure("forecast", () => api.fpForecast(S.branch, S.horizon)); }

  async function buildForecast() {
    const f = await loadForecast();
    const m = f.meta, fut = f.days.filter((d) => d.is_future);
    const w = m.weather;
    const wtxt = w.live_days ? L("fp_weather_live", { n: w.live_days, total: w.total_days }) : L("fp_weather_assumed");
    S.explainDate = S.explainDate && fut.some((d) => d.date === S.explainDate) ? S.explainDate : fut[0].date;
    const b = f.brief;
    const explainBox = h("div", { id: "fp-explain" });
    const pick = h("select", { class: "input", id: "fp-explain-day", "aria-label": L("fp_pick_day"), onchange: (e) => { S.explainDate = e.target.value; loadExplain(explainBox); } },
      fut.map((d) => h("option", { value: d.date, selected: d.date === S.explainDate }, `${shortDate(d.date, S.lang)}${d.fest_name ? " · " + d.fest_name : ""}`)));
    const chart = forecastChart({ days: f.days, festivals: f.festivals, lang: S.lang, labels: { today: L("fp_today"), ariaLabel: L("fp_chart_title") } });
    const legend = h("ul", { class: "legend" },
      h("li", {}, h("i", { class: "sw line" }), L("fp_leg_forecast")), h("li", {}, h("i", { class: "sw b80" }), L("fp_leg_band80")),
      h("li", {}, h("i", { class: "sw b50" }), L("fp_leg_band50")), h("li", {}, h("i", { class: "sw real" }), L("fp_leg_actual")),
      h("li", {}, h("i", { class: "sw hollow" }), L("fp_leg_assumed")), h("li", {}, h("i", { class: "sw fest" }), L("fp_leg_festival")));
    const seg = h("div", { class: "seg", role: "group", "aria-label": L("fp_horizon") }, [14, 28, 56].map((n) =>
      h("button", { type: "button", "aria-pressed": String(S.horizon === n), onclick: () => { S.horizon = n; S.data.forecast = undefined; gen++; show("forecast"); } }, `${n}`)));
    const table = h("details", {}, h("summary", {}, L("fp_chart_table")), h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, [L("fp_col_date"), L("fp_col_expected"), L("fp_col_low"), L("fp_col_high"), L("fp_col_actual")].map((c, i) => h("th", { class: i ? "num" : "" }, c)))),
      h("tbody", {}, f.days.map((d) => h("tr", {}, h("td", {}, shortDate(d.date, S.lang), d.fest_name ? ` · ${d.fest_name}` : ""),
        h("td", { class: "num" }, ord(d.point, S.lang)), h("td", { class: "num" }, ord(d.lo80, S.lang)), h("td", { class: "num" }, ord(d.hi80, S.lang)),
        h("td", { class: "num" }, d.actual == null ? "-" : `${ord(d.actual, S.lang)}${d.actual_kind === "real" ? "" : " *"}`)))))));
    loadExplain(explainBox);
    return [
      h("p", { class: "muted fp-meta", id: "fp-meta" },
        h("span", {}, `${L("fp_weather")}: ${wtxt}`), " · ",
        h("span", {}, L("fp_model_line", { real: m.model.n_real, assumed: m.model.n_assumed, sigma: pctText(m.model.sigma) })), " · ",
        h("span", {}, `${L("fp_trends_src")}: ${srcLabel(m.trends.source)}`), " · ", h("span", {}, m.location)),
      h("div", { class: "stats" },
        stat(L("fp_today_orders"), ord(b.today_orders, S.lang), `${L("fp_range80")}: ${ord(b.lo80, S.lang)}–${ord(b.hi80, S.lang)} · ${L("fp_vs_typical", { pct: pctText(b.today_vs_typical, true) })}`),
        stat(L("fp_peak"), shortDate(b.peak_day, S.lang), `${ord(b.peak_orders, S.lang)} · ${L("fp_vs_typical", { pct: pctText(b.peak_vs_typical, true) })}`),
        stat(L("fp_surges"), String(b.surges)), stat(L("fp_sales"), String(b.sales))),
      h("div", { class: "fp-chart-head" }, h("h3", {}, L("fp_chart_title")), seg),
      h("div", { class: "chart-wrap" }, chart), legend, table,
      section(L("fp_why_day"), pick, explainBox),
    ];
  }

  async function loadExplain(box) {
    replace(box, h("p", { class: "muted" }, L("fp_loading")));
    try {
      const key2 = `explain:${S.explainDate}`;
      const e = await ensure(key2, () => api.fpExplain(S.branch, S.explainDate));
      const maxAbs = Math.max(0.05, ...e.drivers.map((d) => Math.abs(d.effect)));
      replace(box,
        h("p", {}, L("fp_expected_on", { date: shortDate(e.date, S.lang), n: ord(e.expected_orders, S.lang) })),
        h("ul", { class: "drivers" }, e.drivers.filter((d) => Math.abs(d.effect) >= 0.005).map((d) =>
          h("li", { class: d.kind }, h("span", { class: "dname" }, driverName(d.driver)),
            h("span", { class: "dbar" }, h("i", { class: d.effect >= 0 ? "pos" : "neg", style: `width:${Math.min(100, (Math.abs(d.effect) / maxAbs) * 100)}%` })),
            h("span", { class: "dval" }, pctText(d.effect, true))))));
    } catch (err) { replace(box, h("p", { role: "alert" }, err.message)); }
  }

  async function buildPricing() {
    const days = S.pricingDays;
    const [p, tr] = await Promise.all([
      ensure(`pricing:${days}`, () => api.fpPricing(S.branch, undefined, days)),
      ensure("trends", () => api.fpTrends(S.branch))]);
    const a = p.assumptions;
    const rows = p.rows;
    const seg = h("div", { class: "seg", role: "group", "aria-label": L("fp_p_days") }, [[1, "fp_p_today"], [7, "fp_p_week"]].map(([n, k]) =>
      h("button", { type: "button", "aria-pressed": String(days === n), onclick: () => { S.pricingDays = n; show("pricing"); } }, L(k))));
    const multi = days > 1;
    const table = rows.length ? h("div", { class: "table-wrap" }, h("table", { id: "fp-price-table" },
      h("thead", {}, h("tr", {}, multi ? h("th", {}, L("fp_p_day")) : null, h("th", {}, L("fp_p_product")), h("th", {}, L("fp_p_action")), h("th", { class: "num" }, L("fp_p_price")),
        h("th", { class: "num" }, L("fp_p_units")), h("th", { class: "num" }, L("fp_p_prep")), h("th", { class: "num" }, L("fp_p_stock")), h("th", {}, L("fp_p_why")))),
      h("tbody", {}, rows.map((r) => h("tr", { "data-product": r.product, "data-label": r.label },
        multi ? h("td", {}, shortDate(r.date, S.lang)) : null,
        h("td", {}, r.product, r.essential ? h("span", { class: "chip info", style: "margin-left:6px" }, L("fp_p_essential")) : null,
          r.assumed_prices ? h("span", { class: "chip MEDIUM", style: "margin-left:6px", title: L("fp_s_placeholder") }, L("fp_s_placeholder")) : null),
        h("td", {}, h("span", { class: `chip act-${r.label}` }, L(`fp_${r.label}`))),
        h("td", { class: "num" }, money(r.price, cur(), S.lang), r.price !== r.base_price ? h("span", { class: "muted" }, ` (${L("fp_p_normal")} ${money(r.base_price, cur(), S.lang)})`) : null),
        h("td", { class: "num" }, one(r.units, S.lang)), h("td", { class: "num" }, one(r.prep, S.lang)),
        h("td", { class: "num" }, `${qty(r.supply, S.lang)} ${r.unit || ""}`),
        h("td", {}, h("details", {}, h("summary", {}, L("fp_p_why")), h("div", { class: "muted", style: "font-size:.85rem;max-width:46ch" }, reasonText(r)))))))))
      : h("p", { class: "empty" }, L("fp_no_plan"));
    const trendsBlock = section(L("fp_trends_title"),
      h("p", { class: "muted" }, `${L("fp_trends_src")}: ${srcLabel(tr.source)}`, tr.day ? ` (${shortDate(tr.day, S.lang)})` : ""),
      h("ul", { class: "list", id: "fp-trends" }, tr.scores.slice(0, 6).map((x) => h("li", {}, h("strong", {}, x.product), ` · ${x.score.toFixed(2)} · ${L("fp_trend_boost")} ${x.boost_pct >= 0 ? "+" : ""}${x.boost_pct.toFixed(1)}%`))),
      tr.headlines?.length ? h("details", {}, h("summary", {}, `${tr.headlines.length} ↗`), h("ul", { class: "list" }, tr.headlines.map((x) => h("li", {}, h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, x.title))))) : null,
      btn(L("fp_trends_refresh"), async () => {
        const r = await act(() => api.fpRefreshTrends(S.branch));
        if (r) { toast(L("fp_trends_refreshed", { src: srcLabel(r.source) })); await mutated("pricing"); }
      }, "small"));
    return [
      a.prices_assumed ? h("p", { class: "banner warn", id: "fp-prices-assumed" }, "⚠️ ", L("fp_prices_assumed", { n: a.prices_assumed })) : null,
      h("div", { class: "fp-chart-head" }, h("h3", {}, L("fp_tab_pricing")), seg), table,
      h("p", { class: "muted", style: "font-size:.82rem" }, L("fp_capacity_note")), trendsBlock,
    ];
  }

  async function buildOwner() {
    const [fac, rivals, acts, learned, fcast] = await Promise.all([
      ensure("factors", () => api.fpFactors(S.branch)), ensure("rivals", () => api.fpRivals(S.branch)),
      ensure("actuals", () => api.fpActuals(S.branch)), ensure("learned", () => api.fpLearned(S.branch)), loadForecast()]);
    const today = isoDay();
    const msg = h("div", { id: "fp-log-msg", role: "status", class: "muted" }, S.note);
    // --- log a real day
    const dEl = h("input", { type: "date", value: addDays(today, -1), max: today, required: true, id: "fp-a-date" });
    const oEl = num("", { min: 0, step: 1, required: true, id: "fp-a-orders" });
    const rEl = num("", { min: 0, id: "fp-a-rev" });
    const nEl = h("input", { maxLength: 200, id: "fp-a-note" });
    const logForm = h("form", { class: "fp-form", id: "fp-log-form", onsubmit: async (e) => {
      e.preventDefault();
      const r = await act(() => api.fpLogActual(S.branch, { date: dEl.value, orders: Number(oEl.value), revenue: rEl.value === "" ? null : Number(rEl.value), note: nEl.value }));
      if (!r) return;
      S.note = [L("fp_logged"), ...r.factor_changes.map((c) => L("fp_belief_changed", { name: c.factor, said: Math.round(c.you_said_pct), now: Math.round(c.ai_belief_pct), days: c.days_seen }))].join("\n");
      await mutated("owner");
    } }, h("div", { class: "form-grid" }, fld(L("fp_date"), dEl), fld(L("fp_orders"), oEl), fld(L("fp_revenue"), rEl), fld(L("fp_note"), nEl)),
      h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, L("fp_log_btn")),
        btn(L("fp_import_btn"), async () => { const r = await act(() => api.fpImport(S.branch)); if (r) { toast(L("fp_imported", { n: r.imported })); await mutated("owner"); } }),
        acts.actuals.some((x) => x.source === "livingdoc") ? btn(L("fp_clear_src"), async () => { if (await act(() => api.fpClearSource(S.branch, "livingdoc"))) await mutated("owner"); }, "ghost") : null),
      h("p", { class: "muted", style: "font-size:.8rem;margin:0" }, L("fp_import_hint")), msg);
    msg.style.whiteSpace = "pre-line";
    const recent = acts.actuals.length ? h("div", { class: "table-wrap" }, h("table", { id: "fp-actuals" },
      h("thead", {}, h("tr", {}, h("th", {}, L("fp_date")), h("th", { class: "num" }, L("fp_orders")), h("th", { class: "num" }, L("fp_revenue")), h("th", {}, L("fp_source")), h("th", {}, ""))),
      h("tbody", {}, acts.actuals.slice(0, 14).map((x) => h("tr", {}, h("td", {}, shortDate(x.date, S.lang)), h("td", { class: "num" }, ord(x.orders, S.lang)),
        h("td", { class: "num" }, x.revenue == null ? "-" : money(x.revenue, cur(), S.lang)), h("td", {}, L(`fp_src_${x.source}`)),
        h("td", {}, btn(L("fp_delete"), async () => { if (confirm(L("fp_confirm_delete")) && (await act(() => api.fpDeleteActual(S.branch, x.date)))) await mutated("owner"); }, "small ghost"))))))) : h("p", { class: "empty" }, L("fp_none"));

    // --- owner factor
    const prof = await ensure("profile", () => api.fpProfile(S.branch));
    const cats = [...new Set(prof.products.filter((p) => p.status === "tracked").map((p) => p.category))];
    const tx = h("input", { id: "fp-f-text", placeholder: L("fp_factor_text"), maxLength: 200 });
    const nm = h("input", { id: "fp-f-name", maxLength: 80, required: true });
    const f1 = h("input", { type: "date", id: "fp-f-from", value: today, required: true }), f2 = h("input", { type: "date", id: "fp-f-to", value: today, required: true });
    const ef = num(25, { id: "fp-f-effect", min: -90, max: 300, required: true }), cf = num(60, { id: "fp-f-conf", min: 0, max: 100, required: true });
    const sc = h("select", { id: "fp-f-scope", class: "input" }, h("option", { value: "all" }, L("fp_scope_all")), cats.map((c) => h("option", { value: c }, c)));
    const factorForm = h("form", { class: "fp-form", id: "fp-factor-form", onsubmit: async (e) => {
      e.preventDefault();
      const r = await act(() => api.fpAddFactor(S.branch, { name: nm.value, start: f1.value, end: f2.value, effect_pct: Number(ef.value), confidence: Number(cf.value) / 100, scope: sc.value }), L("fp_factor_added"));
      if (r) { S.note = r.belief_changes.map((c) => L("fp_belief_changed", { name: c.factor, said: Math.round(c.you_said_pct), now: Math.round(c.ai_belief_pct), days: c.days_seen })).join("\n"); await mutated("owner"); }
    } },
      h("div", { class: "row" }, tx, btn(L("fp_suggest"), async () => {
        const r = await act(() => api.fpSuggest(tx.value || nm.value || "x"));
        const sug = r?.suggestions?.[0]; if (!sug) return;
        nm.value = sug.name; ef.value = sug.effect_pct; if ([...sc.options].some((o) => o.value === sug.scope)) sc.value = sug.scope;
        toast(sug.why);
      }, "small")),
      h("div", { class: "form-grid" }, fld(L("fp_f_name"), nm), fld(L("fp_f_from"), f1), fld(L("fp_f_to"), f2), fld(L("fp_f_effect"), ef), fld(L("fp_f_conf"), cf), fld(L("fp_f_scope"), sc)),
      h("div", {}, h("button", { class: "btn primary", type: "submit" }, L("fp_add"))));
    const factorList = fac.factors.length ? h("div", { class: "table-wrap" }, h("table", { id: "fp-factors" },
      h("thead", {}, h("tr", {}, h("th", {}, L("fp_f_name")), h("th", {}, L("fp_f_dates")), h("th", { class: "num" }, L("fp_f_said")), h("th", { class: "num" }, L("fp_f_prior")),
        h("th", { class: "num" }, L("fp_f_belief")), h("th", { class: "num" }, L("fp_f_seen")), h("th", {}, ""))),
      h("tbody", {}, fac.factors.map((x) => h("tr", { "data-factor": x.name }, h("td", {}, x.name), h("td", {}, `${shortDate(x.start, S.lang)}–${shortDate(x.end, S.lang)}`),
        h("td", { class: "num" }, `${x.effect_pct > 0 ? "+" : ""}${Math.round(x.effect_pct)}%`), h("td", { class: "num" }, `${x.prior_pct > 0 ? "+" : ""}${Math.round(x.prior_pct)}%`),
        h("td", { class: "num belief" }, `${x.belief_pct > 0 ? "+" : ""}${Math.round(x.belief_pct)}%`), h("td", { class: "num" }, x.n_obs),
        h("td", {}, btn(L("fp_delete"), async () => { if (await act(() => api.fpDeleteFactor(S.branch, x.id))) await mutated("owner"); }, "small ghost"))))))) : h("p", { class: "empty" }, L("fp_none"));

    // --- rival promo
    const rn = h("input", { id: "fp-r-name", maxLength: 80, value: "" }), r1 = h("input", { type: "date", id: "fp-r-from", value: today, required: true }),
      r2 = h("input", { type: "date", id: "fp-r-to", value: today, required: true }), rd = num(15, { id: "fp-r-disc", min: 1, max: 90, required: true });
    const rivalForm = h("form", { class: "fp-form", id: "fp-rival-form", onsubmit: async (e) => {
      e.preventDefault();
      if (await act(() => api.fpAddRival(S.branch, { rival: rn.value || "Rival", start: r1.value, end: r2.value, discount_pct: Number(rd.value) }), L("fp_rival_added"))) await mutated("owner");
    } }, h("div", { class: "form-grid" }, fld(L("fp_rival_name"), rn), fld(L("fp_f_from"), r1), fld(L("fp_f_to"), r2), fld(L("fp_rival_disc"), rd)),
      h("div", {}, h("button", { class: "btn", type: "submit" }, L("fp_add"))));
    const rivalList = rivals.rival_promos.length ? h("ul", { class: "list" }, rivals.rival_promos.map((x) => h("li", {},
      h("span", {}, h("strong", {}, x.rival), ` · ${shortDate(x.start, S.lang)}–${shortDate(x.end, S.lang)} · ${x.discount_pct}% `),
      btn(L("fp_delete"), async () => { if (await act(() => api.fpDeleteRival(S.branch, x.id))) await mutated("owner"); }, "small ghost")))) : null;

    // --- demo + learned
    const demo = fcast.meta.actuals.demo;
    const demoBox = h("div", { class: "row" }, demo ? btn(L("fp_clear_demo"), async () => { if (await act(() => api.fpClearDemo(S.branch))) await mutated("owner"); })
      : btn(L("fp_load_demo"), async () => { if (await act(() => api.fpLoadDemo(S.branch))) await mutated("owner"); }), h("span", { class: "muted", style: "font-size:.8rem" }, L("fp_demo_hint")));
    const learnedTbl = h("details", {}, h("summary", {}, L("fp_learned_title")), h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, L("fp_l_driver")), h("th", { class: "num" }, L("fp_l_assumed")), h("th", { class: "num" }, L("fp_l_learned")))),
      h("tbody", {}, learned.drivers.map((x) => h("tr", {}, h("td", {}, x.driver), h("td", { class: "num" }, x.assumed.toFixed(3)), h("td", { class: "num" }, x.learned.toFixed(3)))))),
      h("p", { class: "muted", style: "font-size:.8rem" }, L("fp_l_hint"))));
    return [
      section(L("fp_log_title"), logForm, recent),
      section(L("fp_factor_title"), factorForm, factorList, h("p", { class: "muted", style: "font-size:.8rem" }, L("fp_beliefs_hint"))),
      section(L("fp_rival_title"), rivalForm, rivalList),
      section("🧪 / 🧠", demoBox, learnedTbl),
    ];
  }

  async function buildScore() {
    const sc = await ensure("score", () => api.fpScorecard(S.branch));
    const m = sc.metrics || {};
    const stats = m.n ? h("div", { class: "stats" },
      stat(L("fp_m_days"), String(m.n)), stat(L("fp_m_mape"), pctText(m.mape, false, 1)), stat(L("fp_m_cov"), pctText(m.coverage)),
      m.skill != null ? stat(L("fp_m_skill"), pctText(m.skill, true)) : null,
      m.uplift_total != null ? stat(L("fp_m_uplift"), `${m.uplift_total >= 0 ? "+" : ""}${money(m.uplift_total, cur(), S.lang)}`, pctText(m.uplift_pct, true, 1)) : null) : null;
    const vTxt = (v) => L(`fp_v_${v.code}`, {
      n: v.params.n, mape: pctText(v.params.mape ?? 0, false, 1), bias: pctText(v.params.bias ?? 0, true, 1), cov: pctText(v.params.cov ?? 0),
      skill: pctText(Math.abs(v.params.skill ?? 0)), total: `${(v.params.total ?? 0) >= 0 ? "+" : ""}${money(v.params.total ?? 0, cur(), S.lang)}`, pct: pctText(v.params.pct ?? 0, true, 1) });
    const verdict = h("ul", { class: "list verdict", id: "fp-verdict" }, sc.verdict.map((v) => h("li", { "data-status": v.status }, h("span", { class: `chip ${v.status === "good" ? "ok" : v.status === "warn" ? "MEDIUM" : v.status === "bad" ? "out" : "info"}` },
      v.status === "good" ? "✓" : v.status === "info" ? "i" : "!"), " ", vTxt(v))));
    const chart = sc.rows.length ? h("div", { class: "chart-wrap" }, scoreChart({ rows: sc.rows, lang: S.lang, labels: { ariaLabel: L("fp_score_chart") } })) : null;
    return [h("p", { class: "muted" }, L("fp_score_hint")), stats, verdict, sc.rows.length ? h("h3", {}, L("fp_score_chart")) : h("p", { class: "empty" }, L("fp_no_score")), chart,
      sc.rows.length ? h("details", {}, h("summary", {}, L("fp_chart_table")), h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, [L("fp_col_date"), L("fp_col_expected"), L("fp_col_low"), L("fp_col_high"), L("fp_col_actual")].map((c, i) => h("th", { class: i ? "num" : "" }, c)))),
        h("tbody", {}, sc.rows.map((r) => h("tr", {}, h("td", {}, shortDate(r.date, S.lang)), h("td", { class: "num" }, ord(r.point, S.lang)), h("td", { class: "num" }, ord(r.lo80, S.lang)),
          h("td", { class: "num" }, ord(r.hi80, S.lang)), h("td", { class: "num" }, ord(r.actual, S.lang)))))))) : null];
  }

  async function buildSetup() {
    const [pf, fe] = await Promise.all([ensure("profile", () => api.fpProfile(S.branch)), ensure("festivals", () => api.fpFestivals(S.branch))]);
    const p = pf.profile;
    const loc = { name: h("input", { id: "fp-s-loc", value: p.location.name, required: true }), lat: num(p.location.lat, { id: "fp-s-lat" }), lon: num(p.location.lon, { id: "fp-s-lon" }) };
    const inc = h("select", { id: "fp-s-income", class: "input" }, Object.entries(pf.income_levels).map(([k, v]) => h("option", { value: k, selected: k === p.income_key }, v.label)));
    const rv = num(p.n_competitors, { id: "fp-s-rivals", min: 0, step: 1 }), bo = num(p.base_orders, { id: "fp-s-base", min: 1 }), tk = num(p.avg_ticket, { id: "fp-s-ticket", min: 1 });
    const sg = num(Math.round(p.surge_cap * 100), { id: "fp-s-surge", min: 0, max: 50 }), fl = num(Math.round(p.discount_floor * 100), { id: "fp-s-floor", min: 50, max: 100 });
    const gr = num(p.assumptions.growth_pct_month, { id: "fp-s-growth", min: -10, max: 20 });
    const live = h("input", { type: "checkbox", id: "fp-s-live", checked: !!p.use_live_weather, disabled: !pf.live_weather_allowed });
    const profileForm = h("form", { class: "fp-form", id: "fp-profile-form", onsubmit: async (e) => {
      e.preventDefault();
      const r = await act(() => api.fpSaveProfile(S.branch, { location: { name: loc.name.value, lat: Number(loc.lat.value), lon: Number(loc.lon.value) }, income_key: inc.value,
        n_competitors: Number(rv.value), base_orders: Number(bo.value), avg_ticket: Number(tk.value), surge_cap: Number(sg.value) / 100, discount_floor: Number(fl.value) / 100,
        use_live_weather: live.checked, assumptions: { growth_pct_month: Number(gr.value) } }), L("fp_saved"));
      if (r) await mutated("setup");
    } }, h("div", { class: "form-grid" }, fld(L("fp_s_location"), loc.name), fld(L("fp_s_lat"), loc.lat), fld(L("fp_s_lon"), loc.lon), fld(L("fp_s_income"), inc), fld(L("fp_s_rivals"), rv),
      fld(L("fp_s_base"), bo), fld(L("fp_s_ticket"), tk), fld(L("fp_s_surge"), sg), fld(L("fp_s_floor"), fl), fld(L("fp_s_growth"), gr),
      h("label", { class: "check" }, live, " ", L("fp_s_live"), pf.live_weather_allowed ? null : h("span", { class: "muted" }, ` (${L("fp_live_forbidden")})`))),
      h("div", {}, h("button", { class: "btn primary", type: "submit" }, L("fp_save_all"))));

    const catSel = (v) => h("select", { class: "input" }, pf.categories.map((c) => h("option", { value: c, selected: c === v }, c)));
    const prodRows = pf.products.map((x) => {
      const cat = catSel(x.category), cost = num(x.cost, { min: 0.01, "aria-label": L("fp_s_cost") }), price = num(x.price, { min: 0.01, "aria-label": L("fp_s_price") });
      const el = num(Number(x.elasticity).toFixed(2), { min: 0.2, max: 6, "aria-label": L("fp_s_elast") });
      const ess = h("input", { type: "checkbox", checked: x.essential, "aria-label": L("fp_s_essential") }), trk = h("input", { type: "checkbox", checked: x.tracked, "aria-label": L("fp_s_tracked") });
      const save = btn(L("fp_save_all"), async () => {
        const body = { category: cat.value, cost: Number(cost.value), price: Number(price.value), essential: ess.checked, tracked: trk.checked };
        if (Number(el.value).toFixed(2) !== Number(x.elasticity).toFixed(2)) body.elasticity = Number(el.value);
        if (await act(() => api.fpSaveProduct(S.branch, x.name, body), L("fp_saved"))) await mutated("setup");
      }, "small");
      return h("tr", { "data-product": x.name }, h("td", {}, x.name, x.assumed_prices ? h("span", { class: "chip MEDIUM", style: "margin-left:6px" }, L("fp_s_placeholder")) : null,
        x.status === "no_daily_use" ? h("div", { class: "muted", style: "font-size:.75rem" }, L("fp_s_skipped", { names: x.name })) : null),
        h("td", {}, cat), h("td", {}, cost), h("td", {}, price), h("td", {}, el), h("td", {}, ess), h("td", {}, trk), h("td", {}, save));
    });
    const prodTable = h("div", { class: "table-wrap" }, h("table", { id: "fp-products" }, h("thead", {}, h("tr", {}, [L("fp_p_product"), L("fp_s_cat"), L("fp_s_cost"), L("fp_s_price"), L("fp_s_elast"), L("fp_s_essential"), L("fp_s_tracked"), ""].map((c) => h("th", {}, c)))), h("tbody", {}, prodRows)));

    const fRows = fe.festivals.map((f) => ({ ...f }));
    const fBody = h("tbody");
    const drawF = () => replace(fBody, fRows.map((f, i) => {
      const nm = h("input", { value: f.name, "aria-label": L("fp_s_fname"), oninput: (e) => { f.name = e.target.value; } });
      const s1 = h("input", { type: "date", value: f.start, "aria-label": L("fp_s_start"), oninput: (e) => { f.start = e.target.value; } });
      const s2 = h("input", { type: "date", value: f.end, "aria-label": L("fp_s_end"), oninput: (e) => { f.end = e.target.value; } });
      const lf = num(Math.round(f.lift * 100), { "aria-label": L("fp_s_lift"), oninput: (e) => { f.lift = Number(e.target.value) / 100; } });
      return h("tr", {}, h("td", {}, nm), h("td", {}, s1), h("td", {}, s2), h("td", {}, lf), h("td", {}, btn("✕", () => { fRows.splice(i, 1); drawF(); }, "small ghost")));
    }));
    drawF();
    const festTable = h("div", { class: "table-wrap" }, h("table", { id: "fp-festivals" }, h("thead", {}, h("tr", {}, [L("fp_s_fname"), L("fp_s_start"), L("fp_s_end"), L("fp_s_lift"), ""].map((c) => h("th", {}, c)))), fBody));
    const festBtns = h("div", { class: "row" },
      btn(L("fp_s_add_fest"), () => { fRows.push({ name: "", start: isoDay(), end: isoDay(), lift: 0.3, lead: 3, tail: 1, aff: {} }); drawF(); }, "small"),
      btn(L("fp_save_all"), async () => { if (await act(() => api.fpSaveFestivals(S.branch, fRows), L("fp_saved"))) await mutated("setup"); }, "primary small"),
      btn(L("fp_s_reset_fest"), async () => { if (await act(() => api.fpResetFestivals(S.branch), L("fp_saved"))) await mutated("setup"); }, "small ghost"));
    const skipped = pf.skipped?.length ? h("p", { class: "banner warn" }, L("fp_s_skipped", { names: pf.skipped.join(", ") })) : null;
    return [h("p", { class: "muted" }, L("fp_setup_hint")), section(L("fp_s_profile"), profileForm), section(L("fp_s_products"), skipped, prodTable),
      section(L("fp_s_festivals"), festTable, festBtns, fe.livingdoc_festivals?.length ? h("p", { class: "muted", style: "font-size:.8rem" }, L("fp_s_ld_fest", { names: fe.livingdoc_festivals.map((x) => `${x.name} ${shortDate(x.date, S.lang)}`).join(", ") })) : null),
      h("p", { class: "muted", style: "font-size:.8rem" }, L("fp_daily_hint"))];
  }

  return {
    el,
    update(s) {
      const sig = `${s.lang}|${s.branch}`;
      if (!s.doc || !s.branch) return;
      S.lang = s.lang;
      heading.textContent = L("fp_title");
      if (S.branch !== s.branch) { S.branch = s.branch; S.explainDate = null; S.note = ""; invalidate(); started = false; }
      if (sig !== key || !started) { key = sig; started = true; renderTabs(); show(S.tab); }
    },
  };
}
