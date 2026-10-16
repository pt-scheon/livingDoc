import { api, ApiError } from "./api.js";
import { getState, setState, subscribe, prefs } from "./store.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { uuid } from "./format.js";
import { toast } from "./toast.js";
import { createHeader } from "./components/header.js";
import { createNav, createHero, VIEWS } from "./components/shell.js";
import { showLogin } from "./components/login.js";
import { createNotes } from "./components/notes.js";
import { createScanner } from "./components/scanner.js";
import { createInventory } from "./components/inventory.js";
import { createCash } from "./components/cash.js";
import { createPromises } from "./components/promises.js";
import { createForecast } from "./components/forecast.js";
import { createForesight } from "./components/foresight.js";
import { createTrust } from "./components/trust.js";
import { createPresence } from "./components/presence.js";
import { createRisks } from "./components/risks.js";
import { createSettings } from "./components/settings.js";

const POLL_MS = 10000;
let inflight = null;
let pollTimer = null;

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
      if (err.status === 401) return;
      if (getState().online) toast(t(getState().lang, "offline"), "error");
      setState({ online: false, loading: false, lastError: err.message });
    } finally { inflight = null; }
  })();
  return inflight;
}

// ---------- routing: one screen per area, chosen by the URL hash ----------
const viewFromHash = () => { const v = location.hash.replace(/^#\/?/, ""); return VIEWS.includes(v) ? v : "overview"; };
window.addEventListener("hashchange", () => { setState({ view: viewFromHash() }); window.scrollTo({ top: 0 }); });

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
  focusNote() {
    if (getState().view !== "overview") location.hash = "#/overview";
    setTimeout(() => { const n = document.getElementById("note-text"); if (n) { n.scrollIntoView({ block: "center", behavior: "smooth" }); n.focus(); } }, 60);
  },
  async signOut() { try { await api.logout(); } catch { /* cookie may already be gone */ } location.reload(); },
  openSettings: () => settings.open(),
};

// ---------- build the page ----------
const header = createHeader(actions);
const nav = createNav(actions);
const hero = createHero(actions);
const notes = createNotes(actions);
const scanner = createScanner(actions);
const settings = createSettings(actions);
const inventory = createInventory(actions);
const cash = createCash();
const promises = createPromises(actions);
const forecast = createForecast();
const foresight = createForesight();
const trust = createTrust();
const presence = createPresence();
const risks = createRisks(actions);

const card = (el) => (el.classList.contains("card") ? el : h("div", { class: "card" }, el));
const skeleton = h("div", { class: "card" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
const views = {
  overview: h("div", { class: "view", id: "view-overview" }, hero.el, notes.el, card(risks.el), header.status),
  stock: h("div", { class: "view", id: "view-stock" }, card(inventory.el), scanner.el),
  money: h("div", { class: "view cols-2", id: "view-money" }, card(cash.el), card(promises.el)),
  forecast: h("div", { class: "view", id: "view-forecast" }, card(forecast.el), card(foresight.el)),
  trust: h("div", { class: "view", id: "view-trust" }, card(trust.el)),
  found: h("div", { class: "view", id: "view-found" }, card(presence.el)),
};
const doc = h("main", { class: "main", id: "doc", tabindex: "-1" }, header.el, skeleton, ...Object.values(views));

const app = document.getElementById("app");
function mount() {
  app.className = "app";
  app.replaceChildren(nav.el, doc, settings.el);
  app.removeAttribute("aria-busy");
}

const parts = [header, nav, hero, notes, scanner, inventory, cash, promises, forecast, foresight, trust, presence, risks, settings];
subscribe((s) => {
  if (!app.contains(doc)) return;
  parts.forEach((p) => p.update(s));
  skeleton.hidden = !s.loading || !!s.doc;
  for (const [name, el] of Object.entries(views)) el.hidden = !s.doc || s.view !== name;
  const skip = document.querySelector(".skip"); if (skip) skip.textContent = t(s.lang, "skip");
});

// ---------- boot ----------
async function start() {
  const [config, br] = await Promise.all([api.config(), api.branches()]);
  const savedLang = prefs.get("lang", "en");
  const lang = config.languages[savedLang] ? savedLang : "en";
  const savedBranch = prefs.get("branch", "");
  const branch = br.branches.includes(savedBranch) ? savedBranch : (br.branches.includes(config.default_branch) ? config.default_branch : br.branches[0]);
  mount();
  setState({ config, branches: br.branches, branch, lang, view: viewFromHash() });
  await refresh();
  if (!pollTimer) {
    pollTimer = setInterval(() => { if (!document.hidden && app.contains(doc)) refresh(); }, POLL_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && app.contains(doc)) refresh(); });
    // keep the AI badge honest without hammering the server
    setInterval(async () => { if (!app.contains(doc)) return; try { const config = await api.config(); setState({ config }); } catch { /* offline banner handled by refresh */ } }, 60000);
  }
}

function signIn() {
  const lang = prefs.get("lang", "en");
  showLogin(app, lang, () => location.reload(), (c) => { prefs.set("lang", c); signIn(); });
  app.className = ""; app.removeAttribute("aria-busy");
}
window.addEventListener("ld:unauth", () => { if (app.contains(doc)) signIn(); });

async function boot() {
  try {
    const a = await api.authStatus();
    setState({ auth: a });
    if (a.required && !a.authed) { signIn(); return; }
    await start();
  } catch (err) {
    app.removeAttribute("aria-busy");
    app.replaceChildren(h("div", { class: "main" }, h("p", { class: "card", role: "alert" },
      err instanceof ApiError ? err.message : String(err), " ", h("button", { class: "btn", onclick: () => location.reload() }, "Retry"))));
  }
}
boot();
