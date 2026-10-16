// "Trust ledger & promises" section: ledger (both sides' figures + consent), promise cash flow, proof without exposure.
// All data comes from /api/trust, /api/cashflow/promises and /api/proofs. User text is only ever inserted as text nodes.
import { api } from "../api.js";
import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { money, shortDate } from "../format.js";
import { toast } from "../toast.js";
import { cashChart } from "../charts.js";

const TABS = ["ledger", "cash", "proof"];
const KINDS = ["owed_to_us", "we_owe", "favour_given", "favour_owed", "word"];
const ROLES = ["customer", "supplier", "worker", "neighbour", "other"];
const pad = (n) => String(n).padStart(2, "0");
const isoDay = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export function claimText(L, lang, c) {
  const v = c.unit === "INR" ? money(c.value, "₹", lang) : c.unit === "share" ? `${Math.round(c.value * 100)}%` : String(c.value);
  return L(`tl_cl_${c.id}`, { v });
}

export function createTrust() {
  const heading = h("h2", { id: "tl-h" });
  const intro = h("p", { class: "banner info", id: "tl-intro" });
  const tabBar = h("div", { class: "seg tl-tabs", role: "tablist" });
  const panel = h("div", { class: "fp-panel tl-panel", role: "tabpanel", tabindex: "0" });
  const el = h("section", { "aria-labelledby": "tl-h", id: "tl-section" }, heading, intro, tabBar, panel);

  const S = { lang: "en", branch: "", tab: "ledger", busy: false, cf: { horizon: 60, opening: "", sales: false }, issued: null, verifyOut: null };
  let started = false, gen = 0, key = "";
  const L = (k, v) => t(S.lang, k, v);
  const m = (n) => money(n, "₹", S.lang);

  async function show(tab = S.tab) {
    S.tab = tab; renderTabs();
    const g = ++gen;
    replace(panel, h("p", { class: "muted", role: "status" }, L("tl_loading")));
    try {
      const nodes = await build(tab);
      if (g === gen) replace(panel, nodes);
    } catch (err) { if (g === gen) replace(panel, h("p", { class: "card", role: "alert" }, `${L("tl_error")}: ${err.message}`)); }
  }
  async function act(fn, okMsg) {
    if (S.busy) return null;
    S.busy = true;
    try { const r = await fn(); if (okMsg) toast(okMsg); return r ?? true; }
    catch (err) { toast(err.message, "error"); return null; }
    finally { S.busy = false; }
  }
  const fld = (label, input) => h("label", { class: "field" }, label, input);
  const btn = (label, onclick, cls = "") => h("button", { class: `btn ${cls}`, type: "button", onclick }, label);
  const stat = (label, val, sub) => h("div", { class: "stat" }, h("b", {}, val), h("span", {}, label), sub ? h("span", { class: "muted", style: "display:block" }, sub) : null);
  const block = (title, ...kids) => h("div", { class: "fp-block" }, h("h3", {}, title), ...kids);
  function renderTabs() {
    replace(tabBar, TABS.map((id) => h("button", { type: "button", role: "tab", id: `tl-tab-${id}`, "data-tab": id, "aria-pressed": String(S.tab === id), "aria-selected": String(S.tab === id),
      onclick: () => { if (S.tab !== id) show(id); } }, L(`tl_tab_${id}`))));
  }
  const build = (tab) => (tab === "ledger" ? buildLedger() : tab === "cash" ? buildCash() : buildProof());

  // ---------------------------------------------------------------- ledger
  async function buildLedger() {
    const d = await api.tlLedger(S.branch);
    const sm = d.summary;
    const stats = h("div", { class: "stats" }, stat(L("tl_sum_receivable"), m(sm.receivable)), stat(L("tl_sum_payable"), m(sm.payable)), stat(L("tl_sum_overdue"), String(sm.overdue_count)),
      stat(L("tl_sum_disputed"), String(sm.disputed)), stat(L("tl_sum_inproofs"), String(sm.in_proofs)), stat(L("tl_sum_private"), String(sm.private)));

    const kind = h("select", { id: "tl-kind" }, KINDS.map((k) => h("option", { value: k }, L(`tl_k_${k}`))));
    const who = h("input", { id: "tl-who", maxLength: 80, required: true, list: "tl-people-list" });
    const people = h("datalist", { id: "tl-people-list" }, d.parties.map((p) => h("option", { value: p.name })));
    const role = h("select", { id: "tl-role" }, ROLES.map((r) => h("option", { value: r }, L(`tl_r_${r}`))));
    const amount = h("input", { id: "tl-amount", type: "number", min: "0", step: "any" });
    const due = h("input", { id: "tl-due", type: "date" });
    const desc = h("input", { id: "tl-desc", maxLength: 300 });
    const allow = h("input", { id: "tl-allow", type: "checkbox" });
    const form = h("form", { class: "fp-form", id: "tl-form", onsubmit: async (e) => {
      e.preventDefault();
      if (!who.value.trim()) return;
      const ok = await act(() => api.tlAdd(S.branch, { kind: kind.value, counterparty: who.value.trim(), role: role.value, description: desc.value.trim(),
        amount: amount.value === "" ? null : Number(amount.value), due_on: due.value || null, proof_owner: allow.checked }), L("tl_added"));
      if (ok) show("ledger");
    } }, people, fld(L("tl_kind"), kind), fld(L("tl_who"), who), fld(L("tl_role"), role), fld(L("tl_amount"), amount), fld(L("tl_due"), due), fld(L("tl_desc"), desc),
      h("label", { class: "check" }, allow, " ", L("tl_allow_proof")), h("button", { class: "btn primary", type: "submit", id: "tl-add" }, L("tl_add")));

    const consentCell = (e) => {
      const state = e.counts_in_proofs ? ["ok", L("tl_c_counted")] : (e.proof_owner && e.proof_cp === 0) ? ["out", L("tl_c_vetoed")] : ["info", L("tl_c_private")];
      return h("td", {}, h("span", { class: `chip ${state[0]}` }, state[1]), " ",
        btn(e.proof_owner ? L("tl_c_private") : L("tl_c_allow"), async () => { if (await act(() => api.tlPatch(S.branch, e.id, { proof_owner: !e.proof_owner }))) show("ledger"); }, "small ghost tl-consent"));
    };
    const rows = d.entries.map((e) => {
      const fig = e.amount == null ? "-" : m(e.amount);
      const theirs = e.cp_amount == null ? "-" : m(e.cp_amount);
      const flags = [];
      if (e.disputed_effective) flags.push(h("span", { class: "chip out" }, L("tl_disputed_tag")));
      if (e.overdue_days > 0) flags.push(h("span", { class: "chip low" }, L("tl_overdue_days", { n: e.overdue_days })));
      if (e.derived) flags.push(h("span", { class: "chip info" }, L("tl_mirrored")));
      const act1 = e.status === "open"
        ? [["kept", "tl_mark_kept"], ["broken", "tl_mark_broken"], ["forgiven", "tl_mark_forgiven"]].map(([s, k]) => btn(L(k), async () => { if (await act(() => api.tlResolve(S.branch, e.id, s))) show("ledger"); }, "small"))
        : [btn(L("tl_reopen"), async () => { if (await act(() => api.tlResolve(S.branch, e.id, "open"))) show("ledger"); }, "small ghost")];
      if (!e.derived) act1.push(btn(L("tl_delete"), async () => { if (confirm(L("tl_confirm_delete")) && await act(() => api.tlDelete(S.branch, e.id))) show("ledger"); }, "small ghost"));
      return h("tr", { "data-id": e.id },
        h("td", {}, e.counterparty, h("br"), h("span", { class: `chip ${e.party_label === "shaky" ? "out" : e.party_label === "mixed" ? "low" : e.party_label === "reliable" ? "ok" : "info"}` }, L(`tl_l_${e.party_label}`))),
        h("td", {}, h("b", {}, L(`tl_k_${e.kind}`)), e.description ? ` · ${e.description}` : "", h("div", { class: "tl-flags" }, flags),
          e.worth_low != null && e.worth_high != null && e.worth_low !== e.worth_high ? h("div", { class: "muted", style: "font-size:.78rem" }, L("tl_worth_range", { lo: m(e.worth_low), hi: m(e.worth_high) })) : null,
          e.cp_note ? h("div", { class: "muted", style: "font-size:.78rem" }, `“${e.cp_note}”`) : null),
        h("td", { class: "num" }, fig, e.settled ? h("div", { class: "muted", style: "font-size:.75rem" }, L("tl_open_amount", { n: m(e.open_amount) })) : null),
        h("td", { class: "num" }, theirs),
        h("td", {}, e.due_effective ? shortDate(e.due_effective, S.lang) : "-"),
        h("td", {}, L(`tl_s_${e.status}`)), consentCell(e), h("td", { class: "tl-actions" }, act1));
    });
    const table = rows.length ? h("div", { class: "table-wrap" }, h("table", { id: "tl-table" },
      h("thead", {}, h("tr", {}, ["tl_col_who", "tl_col_what", "tl_col_amount", "tl_col_theirs", "tl_col_due", "tl_col_status", "tl_col_consent", "tl_col_actions"].map((k) => h("th", {}, L(k))))),
      h("tbody", {}, rows))) : h("p", { class: "muted" }, L("tl_no_entries"));

    const linkOut = h("div", { id: "tl-link-out" });
    const peopleList = h("ul", { class: "tl-people" }, d.parties.map((p) => h("li", {},
      h("b", {}, p.name), " ", h("span", { class: `chip ${p.label === "shaky" ? "out" : p.label === "mixed" ? "low" : p.label === "reliable" ? "ok" : "info"}` }, `${L(`tl_l_${p.label}`)} ${p.score.toFixed(2)}`), " ",
      p.avg_delay_days != null ? h("span", { class: "muted" }, `⌀ ${p.avg_delay_days.toFixed(1)}d`) : null, " ",
      btn(L("tl_link_btn"), async () => {
        const r = await act(() => api.tlLink(S.branch, p.name)); if (!r) return;
        const url = `${location.origin}${r.path}`;
        replace(linkOut, h("div", { class: "card" }, h("b", {}, L("tl_link_for", { name: p.name })), h("input", { class: "tl-url", readOnly: true, value: url, "aria-label": L("tl_link_for", { name: p.name }), onfocus: (e) => e.target.select() }), " ",
          btn(L("tl_pf_copy"), async () => { try { await navigator.clipboard.writeText(url); toast(L("tl_pf_copied")); } catch { /* user can select the field */ } }, "small"), " ",
          btn(L("tl_link_revoke"), async () => { if (await act(() => api.tlUnlink(S.branch, p.name), L("tl_link_revoked"))) replace(linkOut); }, "small ghost")));
      }, "small tl-link"))));
    return [stats, block(L("tl_add_title"), form), table, h("p", { class: "muted", style: "font-size:.8rem" }, L("tl_score_hint")),
      block(L("tl_people"), h("p", { class: "muted", style: "font-size:.85rem" }, L("tl_link_hint")), peopleList, linkOut)];
  }

  // ---------------------------------------------------------------- cash flow
  async function buildCash() {
    const c = S.cf;
    const horizon = h("input", { id: "tl-horizon", type: "number", min: "7", max: "120", value: c.horizon });
    const opening = h("input", { id: "tl-opening", type: "number", step: "any", value: c.opening });
    const sales = h("input", { id: "tl-sales", type: "checkbox", checked: c.sales });
    const out = h("div", { id: "tl-cf-out" });
    const run = async () => {
      c.horizon = Number(horizon.value) || 60; c.opening = opening.value; c.sales = sales.checked;
      replace(out, h("p", { class: "muted", role: "status" }, L("tl_loading")));
      try {
        const r = await api.tlCashflow(S.branch, { horizon: c.horizon, opening_cash: c.opening === "" ? undefined : c.opening, include_sales: c.sales });
        replace(out, renderCash(r));
      } catch (err) { replace(out, h("p", { class: "card", role: "alert" }, `${L("tl_error")}: ${err.message}`)); }
    };
    const form = h("form", { class: "fp-form", id: "tl-cf-form", onsubmit: (e) => { e.preventDefault(); run(); } }, fld(L("tl_cf_horizon"), horizon), fld(L("tl_cf_opening"), opening),
      h("label", { class: "check" }, sales, " ", L("tl_cf_sales")), h("button", { class: "btn primary", type: "submit", id: "tl-cf-run" }, L("tl_cf_run")));
    run();
    return [block(L("tl_cf_title"), form), out];
  }
  function warnText(w) {
    if (w.code === "shortfall") return L("tl_w_shortfall", { date: shortDate(w.date, S.lang), p: `${Math.round(w.p * 100)}%` });
    if (w.code === "concentration") return L("tl_w_concentration", { who: w.who, share: `${Math.round(w.share * 100)}%` });
    return L(`tl_w_${w.code}`, { n: w.n ?? w.count ?? "" });
  }
  function renderCash(r) {
    const s = r.summary;
    const stats = h("div", { class: "stats" }, stat(L("tl_cf_expected"), m(s.expected_in)), stat(L("tl_cf_out"), m(s.committed_out)), stat(L("tl_cf_risk"), m(s.at_risk)),
      stat(L("tl_cf_end"), m(s.end_p50), L("tl_cf_range", { lo: m(s.end_p10), hi: m(s.end_p90) })));
    const chart = h("div", { class: "chart-wrap" }, cashChart({ days: r.days, lang: S.lang, labels: { ariaLabel: L("tl_cf_chart") } }),
      h("ul", { class: "legend" }, h("li", {}, h("i", { class: "sw line" }), L("tl_cf_leg_mid")), h("li", {}, h("i", { class: "sw b80" }), L("tl_cf_leg_band"))));
    const warns = r.warnings.map((w) => h("p", { class: "banner warn", role: "alert" }, "⚠️ ", warnText(w)));
    const rows = r.items.map((i) => h("tr", {}, h("td", {}, i.counterparty), h("td", {}, L(`tl_k_${i.kind}`)), h("td", { class: "num" }, m(i.amount)),
      h("td", { class: "num" }, `${Math.round(i.p_kept * 100)}%`), h("td", {}, i.expected_date ? shortDate(i.expected_date, S.lang) : "-"),
      h("td", {}, (i.flags || []).map((f) => h("span", { class: "chip info" }, L(`tl_f_${f}`))))));
    const table = r.items.length ? h("div", { class: "table-wrap" }, h("table", { id: "tl-cf-table" }, h("thead", {}, h("tr", {}, [L("tl_col_who"), L("tl_col_what"), L("tl_cf_amount"), L("tl_cf_p"), L("tl_cf_when"), ""].map((x) => h("th", {}, x)))), h("tbody", {}, rows)))
      : h("p", { class: "muted" }, L("tl_cf_none"));
    return [stats, ...warns, chart, table, h("details", {}, h("summary", {}, L("tl_cf_assump_title")), h("p", { class: "muted" }, L("tl_cf_assump")))];
  }

  // ---------------------------------------------------------------- proofs
  async function buildProof() {
    const [pv, pl] = await Promise.all([api.tlPreview(S.branch), api.tlProofs(S.branch)]);
    const picked = new Set(pv.claims.map((c) => c.id));
    const claimBoxes = pv.claims.map((c) => {
      const cb = h("input", { type: "checkbox", checked: true, value: c.id, class: "tl-claim" });
      cb.addEventListener("change", () => (cb.checked ? picked.add(c.id) : picked.delete(c.id)));
      return h("li", {}, h("label", { class: "check" }, cb, " ", claimText(L, S.lang, c)));
    });
    const valid = h("input", { id: "tl-valid", type: "number", min: "1", max: "90", value: "7" });
    const issuedBox = h("div", { id: "tl-issued" });
    if (S.issued) issuedBox.append(...renderIssued(S.issued));
    const issue = btn(L("tl_pf_issue"), async () => {
      const r = await act(() => api.tlIssue(S.branch, { claims: [...picked], valid_days: Number(valid.value) || 7 }), L("tl_pf_issued"));
      if (r) { S.issued = r; replace(issuedBox, renderIssued(r)); refreshList(); }
    }, "primary");
    issue.id = "tl-issue";
    const reveal = block(L("tl_pf_preview"),
      h("p", { id: "tl-counted" }, L("tl_pf_counted", { n: pv.consenting, m: pv.excluded })),
      pv.claims.length ? h("ul", { class: "tl-claims" }, claimBoxes) : h("p", { class: "muted" }, L("tl_pf_none_claims")),
      pv.withheld.length ? h("p", { class: "muted", style: "font-size:.82rem" }, L("tl_pf_not_claimed", { names: pv.withheld.map((w) => `${L(`tl_cl_${w.id}`, { v: "…" })}`).join(" · ") })) : null,
      h("p", { class: "muted", style: "font-size:.82rem" }, L("tl_pf_reveals")), h("p", { class: "banner info" }, "ℹ️ ", L("tl_pf_scope")),
      pv.claims.length ? h("div", { class: "row" }, fld(L("tl_pf_valid"), valid), issue) : null, issuedBox);

    const listBox = h("div", { id: "tl-proof-list" });
    const drawList = (data) => replace(listBox, data.proofs.length ? h("ul", { class: "tl-proofs" }, data.proofs.map((p) => h("li", {},
      h("code", {}, p.id), " ", p.revoked ? h("span", { class: "chip out" }, L("tl_pf_revoked")) : p.expired ? h("span", { class: "chip low" }, L("tl_pf_expired")) : h("span", { class: "chip ok" }, L("tl_pf_valid_until", { d: shortDate(p.valid_until, S.lang) })),
      " ", p.claims.map((c) => claimText(L, S.lang, c)).join("; "), " ",
      p.revoked ? null : btn(L("tl_pf_revoke"), async () => { if (await act(() => api.tlRevoke(S.branch, p.id))) refreshList(); }, "small ghost")))) : h("p", { class: "muted" }, L("tl_pf_none")));
    const refreshList = async () => { try { drawList(await api.tlProofs(S.branch)); } catch { /* shown on next load */ } };
    drawList(pl);

    return [h("p", { class: "muted" }, L("tl_pf_intro")), reveal, block(L("tl_pf_list"), listBox), verifier()];
  }
  function renderIssued(r) {
    const text = JSON.stringify(r.packet, null, 2);
    return [h("p", { class: "banner info", role: "status" }, "✅ ", L("tl_pf_issued")),
      h("label", { class: "field" }, L("tl_pf_packet"), h("textarea", { readOnly: true, rows: 8, id: "tl-packet-out" }, text)),
      btn(L("tl_pf_copy"), async () => { try { await navigator.clipboard.writeText(text); toast(L("tl_pf_copied")); } catch { /* select manually */ } }, "small"),
      h("p", {}, h("b", {}, `${L("tl_pf_open_key")}: `), h("code", { id: "tl-open-key" }, r.open_key), " · id ", h("code", { id: "tl-proof-id" }, r.packet.id))];
  }

  function verifier() {
    const packet = h("textarea", { id: "tl-vf-packet", rows: 6, placeholder: "{ … }", spellcheck: false });
    const out = h("div", { id: "tl-vf-out", "aria-live": "polite" });
    const parse = () => { try { return JSON.parse(packet.value); } catch { return null; } };
    const check = btn(L("tl_vf_check"), async () => {
      const p = parse();
      if (!p) { replace(out, h("p", { class: "banner warn" }, L("tl_vf_bad"))); return; }
      const r = await act(() => api.tlVerify(p)); if (!r) return;
      const msg = !r.signature_valid ? ["out", L("tl_vf_bad")] : r.expired ? ["low", L("tl_vf_expired")] : r.revoked ? ["out", L("tl_vf_revoked")] : ["ok", L("tl_vf_valid")];
      replace(out, h("p", { class: `banner ${msg[0] === "ok" ? "info" : "warn"}`, id: "tl-vf-msg", "data-ok": String(!!r.valid) }, msg[1]),
        r.signature_valid && r.issued_by_this_shop == null ? h("p", { class: "muted" }, L("tl_vf_unknown")) : null,
        r.signature_valid ? h("div", {}, h("b", {}, L("tl_vf_claims")), h("ul", {}, r.claims.map((c) => h("li", {}, claimText(L, S.lang, c))))) : null);
    }, "primary"); check.id = "tl-vf-check";

    const nonce = h("input", { id: "tl-nonce", minLength: 8 }), pid = h("input", { id: "tl-ch-pid" }), okey = h("input", { id: "tl-ch-key" });
    const openings = h("textarea", { id: "tl-openings", rows: 6, spellcheck: false });
    const chOut = h("div", { id: "tl-ch-out", "aria-live": "polite" });
    const rnd = btn(L("tl_ch_random"), () => { const a = new Uint8Array(12); crypto.getRandomValues(a); nonce.value = [...a].map((x) => x.toString(16).padStart(2, "0")).join(""); }, "small"); rnd.id = "tl-ch-random";
    const open = btn(L("tl_ch_open"), async () => {
      const r = await act(() => api.tlOpen(pid.value.trim(), { open_key: okey.value.trim(), nonce: nonce.value.trim() })); if (r) openings.value = JSON.stringify(r.openings, null, 2);
    }, "small"); open.id = "tl-ch-open";
    const chk = btn(L("tl_ch_check"), async () => {
      const p = parse(); let o; try { o = JSON.parse(openings.value); } catch { o = null; }
      if (!p || !o) { replace(chOut, h("p", { class: "banner warn" }, L("tl_ch_bad"))); return; }
      const r = await act(() => api.tlCheck({ packet: p, nonce: nonce.value.trim(), openings: o })); if (!r) return;
      replace(chOut, h("p", { class: `banner ${r.ok ? "info" : "warn"}`, id: "tl-ch-msg", "data-ok": String(!!r.ok) }, r.ok ? L("tl_ch_ok") : L("tl_ch_bad")));
    }, "primary"); chk.id = "tl-ch-check";
    return block(L("tl_vf_title"), fld(L("tl_vf_paste"), packet), check, out,
      h("h4", {}, L("tl_ch_title")), h("p", { class: "muted", style: "font-size:.85rem" }, L("tl_ch_hint")),
      h("div", { class: "fp-form" }, fld(L("tl_ch_nonce"), nonce), rnd, fld(L("tl_ch_pid"), pid), fld(L("tl_ch_key"), okey), open), fld(L("tl_ch_openings"), openings), chk, chOut);
  }

  return {
    el,
    update(s) {
      if (!s.doc || !s.branch) return;
      S.lang = s.lang;
      heading.textContent = L("tl_title"); intro.textContent = L("tl_intro");
      const sig = `${s.lang}|${s.branch}`;
      if (S.branch !== s.branch) { S.branch = s.branch; S.issued = null; started = false; }
      if (sig !== key || !started) { key = sig; started = true; renderTabs(); show(S.tab); }
    },
  };
}
