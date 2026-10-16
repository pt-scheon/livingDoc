import { api, ApiError } from "./api.js";
import { getState, setState, subscribe, prefs } from "./store.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { uuid } from "./format.js";
import { toast } from "./toast.js";
import { createHeader } from "./components/header.js";
import { createNotes } from "./components/notes.js";
import { createScanner } from "./components/scanner.js";
import { createInventory } from "./components/inventory.js";
import { createCash } from "./components/cash.js";
import { createPromises } from "./components/promises.js";
import { createForecast } from "./components/forecast.js";
import { createForesight } from "./components/foresight.js";
import { createRisks } from "./components/risks.js";
import { createSettings } from "./components/settings.js";
import { dateTime } from "./format.js";

const POLL_MS = 10000;
let inflight = null;

// ---------- data loading ----------
async function refresh() {
  if (inflight) return inflight;
  const { branch, lang } = getState();
  if (!branch) return;
  inflight = (async () => {
    try {
      const [doc, movements, notes, syncStatus] = await Promise.all([
        api.document(branch, lang), api.movements(branch), api.notes(branch), api.syncStatus()]);
      setState({ doc, movements: movements.movements, notes: notes.notes, syncStatus, online: true, loading: false });
    } catch (err) {
      if (getState().online) toast(t(getState().lang, "offline"), "error");
      setState({ online: false, loading: false, lastError: err.message });
    } finally { inflight = null; }
  })();
  return inflight;
}

// ---------- actions shared by components ----------
const actions = {
  refresh,
  toast,
  async setBranch(branch) { prefs.set("branch", branch); setState({ branch, doc: null }); await refresh(); },
  async setLang(lang) { prefs.set("lang", lang); setState({ lang }); await refresh(); },
  async submitNote(text) {
    const { branch, lang } = getState();
    try {
      const res = await api.postNote(branch, text);
      await refresh();
      return res;
    } catch (err) {
      toast(err.status === 409 ? t(lang, "duplicate_note") : err.message, err.status === 409 ? "info" : "error");
      return null;
    }
  },
  async saveItem(item) {
    const { branch, lang } = getState();
    try { await api.putItem({ ...item, branch }); toast(t(lang, "saved")); await refresh(); return true; }
    catch (err) { toast(err.message, "error"); return false; }
  },
  async scan(itemName, qty, direction) {
    const { branch, lang } = getState();
    try {
      const r = await api.scan(branch, [{ event_id: uuid(), item: itemName, qty, direction, branch }]);
      toast(r.applied ? t(lang, "scanned") : t(lang, "error_generic"), r.applied ? "info" : "error");
      await refresh();
    } catch (err) { toast(err.message, "error"); }
  },
  async setPromise(id, done) {
    try { await api.setPromise(id, done); await refresh(); } catch (err) { toast(err.message, "error"); await refresh(); }
  },
  async resolveRisk(id) {
    try { await api.resolveRisk(id); await refresh(); } catch (err) { toast(err.message, "error"); }
  },
  async syncNow() {
    setState({ busySync: true });
    try { const r = await api.sync(); toast(`↑ ${r.pushed}  ↓ ${r.pulled}`); }
    catch (err) { toast(err.message, "error"); }
    setState({ busySync: false });
    await refresh();
  },
  openSettings: () => settings.open(),
};

// ---------- build the page ----------
const header = createHeader(actions);
const notes = createNotes(actions);
const scanner = createScanner(actions);
const settings = createSettings(actions);
const inventory = createInventory(actions);
const cash = createCash();
const promises = createPromises(actions);
const forecast = createForecast();
const foresight = createForesight();
const risks = createRisks(actions);

const docTitle = h("h1", { class: "doc-title", id: "doc-title" });
const docSub = h("p", { class: "doc-sub" });
const skeleton = h("div", {}, h("div", { class: "skeleton" }), h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
const paper = h("article", { class: "card paper", id: "doc", tabindex: "-1", "aria-labelledby": "doc-title" },
  docTitle, docSub, skeleton, inventory.el, cash.el, promises.el, forecast.el, foresight.el, risks.el);

const app = document.getElementById("app");
app.append(h("div", { class: "shell" }, header.el,
  h("main", { class: "grid" }, h("div", { class: "col-left" }, notes.el, scanner.el), paper)), settings.el);

const parts = [header, notes, scanner, inventory, cash, promises, forecast, foresight, risks, settings];
subscribe((s) => {
  parts.forEach((p) => p.update(s));
  const L = (k) => t(s.lang, k);
  docTitle.textContent = `📄 ${s.branch ? s.branch + " · " : ""}${L("doc_title")}`;
  docSub.textContent = s.doc ? `${L("updated")}: ${dateTime(s.doc.generated_at, s.lang)}` : "";
  skeleton.hidden = !s.loading || !!s.doc;
  [inventory.el, cash.el, promises.el, forecast.el, foresight.el, risks.el].forEach((el) => { el.hidden = !s.doc; });
  const skip = document.querySelector(".skip"); if (skip) skip.textContent = L("skip");
  app.removeAttribute("aria-busy");
});

// ---------- boot ----------
async function boot() {
  try {
    const [config, br] = await Promise.all([api.config(), api.branches()]);
    const savedLang = prefs.get("lang", "en");
    const lang = config.languages[savedLang] ? savedLang : "en";
    const savedBranch = prefs.get("branch", "");
    const branch = br.branches.includes(savedBranch) ? savedBranch : (br.branches.includes(config.default_branch) ? config.default_branch : br.branches[0]);
    setState({ config, branches: br.branches, branch, lang });
    await refresh();
  } catch (err) {
    app.removeAttribute("aria-busy");
    app.replaceChildren(h("div", { class: "shell" }, h("p", { class: "card", role: "alert" },
      err instanceof ApiError ? err.message : String(err), " ", h("button", { class: "btn", onclick: () => location.reload() }, "Retry"))));
    return;
  }
  setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  // keep the AI badge honest without hammering the server
  setInterval(async () => { try { const config = await api.config(); setState({ config }); } catch { /* offline banner handled by refresh */ } }, 60000);
}
boot();
