// "Be found, stay in control": the owner builds a public page field by field, and an AI helper that only drafts.
import { api } from "../api.js";
import { h, replace } from "../dom.js";
import { t, LANGS } from "../i18n.js";
import { money, shortDate } from "../format.js";
import { toast } from "../toast.js";

const TABS = ["page", "helper", "feedback", "log"];

export function createPresence() {
  const heading = h("h2", { id: "pr-h" });
  const intro = h("p", { class: "banner info", id: "pr-intro" });
  const tabBar = h("div", { class: "seg pr-tabs", role: "tablist" });
  const panel = h("div", { class: "fp-panel pr-panel", role: "tabpanel", tabindex: "0" });
  const el = h("section", { "aria-labelledby": "pr-h", id: "pr-section" }, heading, intro, tabBar, panel);

  const S = { lang: "en", branch: "", tab: "page", busy: false, draftLang: "en" };
  let started = false, gen = 0, key = "";
  const L = (k, v) => t(S.lang, k, v);

  async function show(tab = S.tab) {
    S.tab = tab; renderTabs();
    const g = ++gen;
    replace(panel, h("p", { class: "muted", role: "status" }, L("pr_loading")));
    try { const n = await build(tab); if (g === gen) replace(panel, n); }
    catch (err) { if (g === gen) replace(panel, h("p", { class: "card", role: "alert" }, `${L("pr_error")}: ${err.message}`)); }
  }
  async function act(fn, okMsg) {
    if (S.busy) return null;
    S.busy = true;
    try { const r = await fn(); if (okMsg) toast(okMsg); return r ?? true; }
    catch (err) { toast(err.message, "error"); return null; }
    finally { S.busy = false; }
  }
  const fld = (label, input) => h("label", { class: "field" }, label, input);
  const chk = (label, input) => h("label", { class: "check" }, input, h("span", {}, label));
  const btn = (label, onclick, cls = "") => h("button", { class: `btn ${cls}`, type: "button", onclick }, label);
  const block = (title, ...kids) => h("div", { class: "fp-block" }, h("h3", {}, title), ...kids);
  function renderTabs() {
    replace(tabBar, TABS.map((id) => h("button", { type: "button", role: "tab", id: `pr-tab-${id}`, "aria-pressed": String(S.tab === id), "aria-selected": String(S.tab === id),
      onclick: () => { if (S.tab !== id) show(id); } }, L(`pr_tab_${id}`))));
  }
  const build = (tab) => (tab === "page" ? buildPage() : tab === "helper" ? buildHelper() : tab === "feedback" ? buildFeedback() : buildLog());

  // ------------------------------------------------------------- page
  async function buildPage() {
    const [d, pf] = await Promise.all([api.prGet(S.branch), api.tlProofs(S.branch)]);
    const p = d.profile;
    const txt = (id, v, max) => h("input", { id, value: v, maxLength: max });
    const name = txt("pr-name", p.name, 80), tag = txt("pr-tagline", p.tagline, 120), area = txt("pr-area", p.area, 80), hours = txt("pr-hours", p.hours, 120);
    const about = h("textarea", { id: "pr-about", rows: 3, maxLength: 600 }, p.about);
    const langs = Object.entries(LANGS).map(([c, n]) => { const i = h("input", { type: "checkbox", value: c, checked: p.languages.includes(c), class: "pr-lang" }); return chk(n, i); });
    const showProd = h("input", { id: "pr-show-products", type: "checkbox", checked: p.show_products });
    const prods = d.items.map((n) => { const i = h("input", { type: "checkbox", value: n, checked: p.product_names.includes(n), class: "pr-prod" }); return chk(n, i); });
    const showTrust = h("input", { id: "pr-show-trust", type: "checkbox", checked: p.show_trust });
    const usable = pf.proofs.filter((x) => !x.revoked && !x.expired);
    const proof = h("select", { id: "pr-proof" }, h("option", { value: "" }, L("pr_no_proof")),
      usable.map((x) => h("option", { value: x.id, selected: x.id === p.proof_id }, `${x.id} · ${L("sh_valid_until", { d: shortDate(x.valid_until, S.lang) })}`)));
    const pub = h("input", { id: "pr-published", type: "checkbox", checked: p.published });
    const save = btn(L("pr_save"), async () => {
      const body = { name: name.value, tagline: tag.value, about: about.value, area: area.value, hours: hours.value,
        languages: [...panel.querySelectorAll(".pr-lang:checked")].map((x) => x.value), show_products: showProd.checked,
        product_names: [...panel.querySelectorAll(".pr-prod:checked")].map((x) => x.value), show_trust: showTrust.checked, proof_id: proof.value || "", published: pub.checked };
      if (await act(() => api.prPut(S.branch, body), L("pr_saved"))) show("page");
    }, "primary"); save.id = "pr-save";
    const link = p.published ? h("a", { class: "btn", id: "pr-open", href: `shop.html?s=${encodeURIComponent(p.slug)}`, target: "_blank", rel: "noopener" }, L("pr_open_page")) : null;
    return [h("div", { class: "fp-form" }, fld(L("pr_name"), name), fld(L("pr_tagline"), tag), fld(L("pr_about"), about), fld(L("pr_area"), area), fld(L("pr_hours"), hours),
      h("div", {}, h("b", {}, L("pr_langs")), h("div", { class: "pr-checks" }, langs))),
      block(L("pr_show_products"), chk(L("pr_show_products"), showProd), h("b", {}, L("pr_pick_products")), h("div", { class: "pr-checks" }, prods)),
      block(L("pr_show_trust"), chk(L("pr_show_trust"), showTrust), fld(L("pr_pick_proof"), proof), h("p", { class: "muted", style: "font-size:.82rem" }, L("pr_proof_hint"))),
      h("p", { class: "muted", style: "font-size:.82rem" }, "🔒 ", L("pr_never_shown")),
      block(L("pr_published"), chk(L("pr_published"), pub), h("p", { class: "muted", style: "font-size:.82rem" }, L("pr_publish_hint"))),
      h("div", { class: "row" }, save, link)];
  }

  // ------------------------------------------------------------- helper
  async function buildHelper() {
    const [d, dr] = await Promise.all([api.prGet(S.branch), api.prDrafts(S.branch)]);
    const p = d.profile, b = d.budget;
    const auto = h("select", { id: "pr-autonomy", onchange: async (e) => { if (await act(() => api.prPut(S.branch, { autonomy: e.target.value }), L("pr_saved"))) show("helper"); } },
      ["suggest", "off"].map((v) => h("option", { value: v, selected: p.autonomy === v }, L(`pr_a_${v}`))));
    const lang = h("select", { id: "pr-draft-lang", "aria-label": L("pr_suggest_lang"), onchange: (e) => { S.draftLang = e.target.value; } },
      Object.entries(LANGS).map(([c, n]) => h("option", { value: c, selected: c === S.draftLang }, n)));
    const go = btn(L("pr_suggest"), async () => {
      const r = await act(() => api.prSuggest(S.branch, S.draftLang));
      if (r) { toast(r.drafts.length ? L("pr_made", { n: r.drafts.length }) : L("pr_none_new")); show("helper"); }
    }, "primary"); go.id = "pr-suggest"; go.disabled = p.autonomy === "off";
    const cap = h("input", { id: "pr-cap", type: "number", min: "0", step: "any", value: b.cap });
    const budget = block(L("pr_budget"), h("div", { class: "row" }, fld(L("pr_cap"), cap), h("button", { class: "btn small", type: "button", id: "pr-cap-save", onclick: async () => { if (await act(() => api.prPut(S.branch, { budget_cap: Number(cap.value) || 0 }), L("pr_saved"))) show("helper"); } }, L("pr_save"))),
      h("p", {}, `${L("pr_planned")}: ${money(b.planned, "₹", S.lang)} · ${L("pr_remaining")}: ${money(b.remaining, "₹", S.lang)}`), h("p", { class: "muted", style: "font-size:.82rem" }, L("pr_budget_note")));
    const cards = dr.drafts.map(card);
    return [block(L("pr_h_autonomy"), auto, h("p", { class: "muted", style: "font-size:.82rem" }, L("pr_a_note")), h("div", { class: "row" }, fld(L("pr_suggest_lang"), lang), go)),
      block(L("pr_drafts"), cards.length ? cards : h("p", { class: "muted" }, L("pr_no_drafts"))), budget];
  }
  function card(d) {
    const ta = h("textarea", { rows: 3, class: "pr-text", "aria-label": L(`pr_k_${d.kind}`), disabled: d.status === "published", maxLength: 600 }, d.text);
    const go = (action) => async () => { if (await act(() => api.prDecide(S.branch, d.id, action))) show("helper"); };
    const acts = [];
    if (d.status !== "published" && d.status !== "rejected") acts.push(btn(L("pr_edit"), async () => { if (await act(() => api.prEdit(S.branch, d.id, ta.value), L("pr_saved"))) show("helper"); }, "small ghost"));
    if (d.status === "draft") acts.push(btn(L("pr_approve"), go("approve"), "small pr-approve"));
    if (d.status === "approved") acts.push(btn(L("pr_publish"), go("publish"), "small primary pr-publish"));
    if (d.status === "published") acts.push(btn(L("pr_unpublish"), go("unpublish"), "small"));
    if (d.status !== "published" && d.status !== "rejected") acts.push(btn(L("pr_reject"), go("reject"), "small ghost"));
    let boost = null;
    if (d.status === "published") {
      const amt = h("input", { type: "number", min: "1", step: "any", "aria-label": L("pr_boost"), class: "pr-amt" });
      boost = h("div", { class: "row" }, fld(L("pr_boost"), amt), btn(L("pr_boost_btn"), async () => { if (await act(() => api.prBoost(S.branch, d.id, Number(amt.value)), L("pr_saved"))) show("helper"); }, "small"));
    }
    const w = d.why || {};
    return h("article", { class: "card pr-draft", "data-id": d.id, "data-status": d.status, "data-kind": d.kind },
      h("div", {}, h("b", {}, L(`pr_k_${d.kind}`)), " ", h("span", { class: `chip ${d.status === "published" ? "ok" : d.status === "rejected" ? "out" : "info"}` }, L(`pr_s_${d.status}`)), " ", h("span", { class: "muted" }, LANGS[d.lang] || d.lang)),
      ta, h("details", {}, h("summary", {}, L("pr_why")), h("ul", {},
        h("li", {}, `${L("pr_why_source")}: ${w.source || ""}`), (w.uses?.length ? h("li", {}, `${L("pr_why_uses")}: ${w.uses.join(", ")}`) : null), h("li", {}, `${L("pr_why_invented")}: ${w.invented || ""}`))),
      h("div", { class: "row" }, acts), boost);
  }

  // ------------------------------------------------------------- feedback
  async function buildFeedback() {
    const [mine, cust] = await Promise.all([api.fbList(S.branch, "owner"), api.fbList(S.branch, "customer")]);
    const cat = h("select", { id: "fb-category" }, ["idea", "bug", "confusing", "praise"].map((c) => h("option", { value: c }, L(`fb_c_${c}`))));
    const text = h("textarea", { id: "fb-text", rows: 3, maxLength: 600 });
    const send = btn(L("fb_send"), async () => {
      if (await act(() => api.fbSuggest(S.branch, { text: text.value, category: cat.value, lang: S.lang, screen: "found" }), L("fb_sent"))) show("feedback");
    }, "primary"); send.id = "fb-send";
    const chipOf = (st) => h("span", { class: `chip ${st === "done" ? "ok" : st === "dismissed" ? "out" : "info"}` }, L(`fb_s_${st}`));
    const myRows = mine.items.map((r) => h("article", { class: "card fb-item", "data-id": r.id },
      h("div", {}, h("b", {}, L(`fb_c_${r.category}`)), " ", chipOf(r.status), " ", h("span", { class: "muted" }, shortDate(r.created_at, S.lang))),
      h("p", {}, r.text), r.dev_note ? h("p", { class: "muted" }, `${L("fb_dev_note")}: ${r.dev_note}`) : null));
    const sm = cust.summary;
    const custRows = cust.items.map((r) => h("article", { class: "card fb-cust", "data-id": r.id },
      h("div", {}, r.rating ? h("b", { "aria-label": `${r.rating}/5` }, "★".repeat(r.rating) + "☆".repeat(5 - r.rating)) : null, " ", h("span", { class: "muted" }, `${r.name || L("fb_anon")} · ${shortDate(r.created_at, S.lang)}`),
        r.status === "new" ? [" ", h("span", { class: "chip info" }, L("fb_s_new"))] : null),
      r.text ? h("p", {}, r.text) : null, r.contact ? h("p", { class: "muted" }, `${L("fb_contact")}: ${r.contact}`) : null,
      r.status === "new" ? btn(L("fb_seen"), async () => { if (await act(() => api.fbStatus(S.branch, r.id, { status: "seen" }))) show("feedback"); }, "small ghost") : null));
    return [block(L("fb_suggest_h"), h("p", { class: "muted" }, L("fb_suggest_intro")), fld(L("fb_category"), cat), fld(L("fb_text"), text), h("div", { class: "row" }, send)),
      block(L("fb_mine"), myRows.length ? myRows : h("p", { class: "muted" }, L("fb_none"))),
      block(L("fb_cust_h"), h("p", { class: "muted" }, L("fb_cust_intro")),
        sm.average_rating ? h("p", { id: "fb-avg" }, h("b", {}, `${L("fb_avg")}: ${sm.average_rating} / 5`), " ", h("span", { class: "muted" }, L("fb_of", { n: sm.rated }))) : null,
        custRows.length ? custRows : h("p", { class: "muted" }, L("fb_cust_none")))];
  }

  // ------------------------------------------------------------- log
  async function buildLog() {
    const r = await api.prLog(S.branch);
    if (!r.log.length) return h("p", { class: "muted" }, L("pr_log_empty"));
    return block(L("pr_log"), h("div", { class: "table-wrap" }, h("table", { id: "pr-log" }, h("tbody", {}, r.log.map((x) => h("tr", {},
      h("td", {}, shortDate(x.at, S.lang)), h("td", {}, h("span", { class: `chip ${x.actor === "helper" ? "info" : "ok"}` }, L(`pr_actor_${x.actor}`))), h("td", {}, x.action), h("td", {}, x.detail)))))));
  }

  return {
    el,
    update(s) {
      if (!s.doc || !s.branch) return;
      S.lang = s.lang;
      heading.textContent = L("pr_title"); intro.textContent = L("pr_intro");
      const sig = `${s.lang}|${s.branch}`;
      if (S.branch !== s.branch) { S.branch = s.branch; started = false; }
      if (sig !== key || !started) { key = sig; started = true; renderTabs(); show(S.tab); }
    },
  };
}
