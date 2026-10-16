// The other person's private page: exactly what the shop recorded about them, and their right to answer.
import { api } from "./api.js";
import { h, replace } from "./dom.js";
import { t, LANGS } from "./i18n.js";
import { money, shortDate } from "./format.js";
import { toast } from "./toast.js";

const token = new URLSearchParams(location.search).get("t") || "";
let lang = (() => { try { return localStorage.getItem("ld_party_lang") || "en"; } catch { return "en"; } })();
if (!LANGS[lang]) lang = "en";
let data = null, error = "";
const L = (k, v) => t(lang, k, v);
const m = (n) => money(n, "₹", lang);
const app = document.getElementById("app");

async function load() {
  try { data = await api.tlParty(token); error = ""; } catch (err) { data = null; error = err.status === 404 || err.status === 403 ? L("tl_p_bad_link") : err.message; }
  draw();
}

function entryCard(e) {
  const mine = h("input", { type: "number", min: "0", step: "any", value: e.cp_amount ?? "", id: `p-amt-${e.id}` });
  const note = h("input", { maxLength: 300, value: e.cp_note || "", id: `p-note-${e.id}` });
  const disp = h("input", { type: "checkbox", checked: e.disputed, id: `p-disp-${e.id}` });
  const cons = h("input", { type: "checkbox", checked: e.my_consent === 1, id: `p-cons-${e.id}` });
  const save = h("button", { class: "btn primary", type: "button", id: `p-save-${e.id}`, onclick: async () => {
    try {
      data = await api.tlPartyRespond(token, e.id, { cp_amount: mine.value === "" ? null : Number(mine.value), cp_note: note.value, disputed: disp.checked, proof_consent: cons.checked });
      toast(L("tl_p_saved")); draw();
    } catch (err) { toast(err.message, "error"); }
  } }, L("tl_p_save"));
  return h("article", { class: "card tl-party-entry", "data-id": e.id },
    h("h3", {}, L(`tl_k_${e.kind}`), e.description ? ` · ${e.description}` : ""),
    h("p", { class: "muted" }, `${L("tl_p_shop_figure")}: ${e.amount == null ? "-" : m(e.amount)} · ${L("tl_p_status")}: ${L(`tl_s_${e.status}`)}${e.due_on ? ` · ${L("tl_col_due")}: ${shortDate(e.due_on, lang)}` : ""}`),
    h("div", { class: "fp-form" }, h("label", { class: "field" }, L("tl_p_my_figure"), mine), h("label", { class: "field" }, L("tl_p_note"), note),
      h("label", { class: "check" }, disp, " ", L("tl_p_dispute")), h("label", { class: "check" }, cons, " ", L("tl_p_consent")),
      h("p", { class: "muted", style: "font-size:.82rem" }, `${L("tl_p_owner_wants")}: ${e.owner_wants_included ? L("tl_yes") : L("tl_no")} · ${L("tl_p_counted")}: ${e.included_in_proofs ? L("tl_yes") : L("tl_no")}`), save));
}

function draw() {
  document.documentElement.lang = lang;
  const langBar = h("div", { class: "seg", role: "group" }, Object.entries(LANGS).map(([c, n]) => h("button", { type: "button", lang: c, "aria-pressed": String(c === lang),
    onclick: () => { lang = c; try { localStorage.setItem("ld_party_lang", c); } catch { /* optional */ } draw(); } }, n)));
  let body;
  if (error) body = h("p", { class: "card", role: "alert", id: "p-error" }, error);
  else if (!data) body = h("p", { class: "muted" }, L("tl_loading"));
  else {
    const sc = data.score;
    body = [h("p", { class: "banner info" }, L("tl_p_intro")),
      sc ? h("div", { class: "card", id: "p-score" }, h("h3", {}, L("tl_p_score")), h("p", {}, L("tl_p_score_line", { score: sc.score.toFixed(2), label: L(`tl_l_${sc.label}`), resolved: sc.resolved, on_time: sc.on_time, late: sc.late, broken: sc.broken })),
        h("p", { class: "muted", style: "font-size:.82rem" }, L("tl_score_hint"))) : null,
      data.entries.length ? data.entries.map(entryCard) : h("p", { class: "muted" }, L("tl_p_none"))];
  }
  replace(app, h("header", { class: "card" }, h("h1", { class: "doc-title" }, data ? `${L("tl_p_title")}: ${data.name}` : L("tl_p_title")), langBar), h("main", { class: "fp-panel" }, body));
  app.removeAttribute("aria-busy");
}
load();
