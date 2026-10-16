// Thin client for the LivingDoc REST API. Every call has a timeout and throws ApiError with a readable message.
const BASE = (window.LIVINGDOC_API || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(method, path, { query, body, timeout = 30000 } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  for (const [k, v] of Object.entries(query || {})) if (v != null) url.searchParams.set(k, v);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, {
      method, signal: ctrl.signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const isJson = (res.headers.get("content-type") || "").includes("json");
    const data = isJson ? await res.json() : await res.text();
    if (!res.ok) {
      let msg = (data && data.detail) || res.statusText;
      if (Array.isArray(msg)) msg = msg.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
      if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new CustomEvent("ld:unauth"));
      throw new ApiError(String(msg), res.status);
    }
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(err.name === "AbortError" ? "The server took too long to answer." : "Cannot reach the server.", 0);
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  authStatus: () => request("GET", "/api/auth/status"),
  login: (password) => request("POST", "/api/auth/login", { body: { password } }),
  logout: () => request("POST", "/api/auth/logout", { body: {} }),
  config: () => request("GET", "/api/config"),
  branches: () => request("GET", "/api/branches"),
  document: (branch, lang) => request("GET", "/api/document", { query: { branch, lang } }),
  markdownUrl: (branch, lang) => `${BASE}/api/document.md?branch=${encodeURIComponent(branch)}&lang=${lang}`,
  postNote: (branch, text) => request("POST", "/api/notes", { body: { branch, text }, timeout: 90000 }),
  notes: (branch) => request("GET", "/api/notes", { query: { branch, limit: 8 } }),
  movements: (branch) => request("GET", "/api/movements", { query: { branch, limit: 20 } }),
  putItem: (item) => request("PUT", "/api/items", { body: item }),
  scan: (branch, events) => request("POST", "/api/scanner/events", { body: { branch, events } }),
  sync: () => request("POST", "/api/sync"),
  syncStatus: () => request("GET", "/api/sync/status"),
  festivals: () => request("GET", "/api/festivals"),
  addFestival: (f) => request("POST", "/api/festivals", { body: f }),
  deleteFestival: (name, date) => request("DELETE", "/api/festivals", { query: { name, date } }),
  setLeadDays: (days) => request("PUT", "/api/settings/lead-days", { body: { days } }),
  setPromise: (id, done) => request("PATCH", `/api/promises/${id}`, { body: { done } }),
  fpForecast: (branch, horizon = 28) => request("GET", "/api/forecast", { query: { branch, horizon, history: 28 }, timeout: 90000 }),
  fpPricing: (branch, date, days) => request("GET", "/api/pricing", { query: { branch, date, days }, timeout: 90000 }),
  fpExplain: (branch, date) => request("GET", "/api/explain", { query: { branch, date }, timeout: 60000 }),
  fpActuals: (branch) => request("GET", "/api/actuals", { query: { branch } }),
  fpLogActual: (branch, body) => request("POST", "/api/actuals", { query: { branch }, body, timeout: 90000 }),
  fpDeleteActual: (branch, date) => request("DELETE", `/api/actuals/${date}`, { query: { branch }, timeout: 90000 }),
  fpImport: (branch) => request("POST", "/api/actuals/import", { query: { branch, days: 30 }, timeout: 180000 }),
  fpClearSource: (branch, source) => request("DELETE", "/api/actuals", { query: { branch, source }, timeout: 90000 }),
  fpFactors: (branch) => request("GET", "/api/factors", { query: { branch } }),
  fpSuggest: (text) => request("GET", "/api/factors/suggest", { query: { text } }),
  fpAddFactor: (branch, body) => request("POST", "/api/factors", { query: { branch }, body, timeout: 90000 }),
  fpDeleteFactor: (branch, id) => request("DELETE", `/api/factors/${id}`, { query: { branch }, timeout: 90000 }),
  fpRivals: (branch) => request("GET", "/api/rival-promos", { query: { branch } }),
  fpAddRival: (branch, body) => request("POST", "/api/rival-promos", { query: { branch }, body, timeout: 90000 }),
  fpDeleteRival: (branch, id) => request("DELETE", `/api/rival-promos/${id}`, { query: { branch }, timeout: 90000 }),
  fpScorecard: (branch) => request("GET", "/api/scorecard", { query: { branch }, timeout: 90000 }),
  fpTrends: (branch) => request("GET", "/api/trends", { query: { branch } }),
  fpRefreshTrends: (branch) => request("POST", "/api/trends/refresh", { query: { branch, force: true }, timeout: 120000 }),
  fpLearned: (branch) => request("GET", "/api/foresight/learned", { query: { branch } }),
  fpProfile: (branch) => request("GET", "/api/foresight/profile", { query: { branch } }),
  fpSaveProfile: (branch, body) => request("PUT", "/api/foresight/profile", { query: { branch }, body, timeout: 90000 }),
  fpSaveProduct: (branch, name, body) => request("PUT", `/api/foresight/products/${encodeURIComponent(name)}`, { query: { branch }, body, timeout: 90000 }),
  fpFestivals: (branch) => request("GET", "/api/foresight/festivals", { query: { branch } }),
  fpSaveFestivals: (branch, rows) => request("PUT", "/api/foresight/festivals", { query: { branch }, body: rows, timeout: 90000 }),
  fpResetFestivals: (branch) => request("POST", "/api/foresight/festivals/reset", { query: { branch } }),
  fpLoadDemo: (branch) => request("POST", "/api/foresight/demo", { query: { branch }, body: { days: 21 }, timeout: 180000 }),
  fpClearDemo: (branch) => request("DELETE", "/api/foresight/demo", { query: { branch }, timeout: 90000 }),
  tlLedger: (branch) => request("GET", "/api/trust/ledger", { query: { branch } }),
  tlAdd: (branch, body) => request("POST", "/api/trust/entries", { query: { branch }, body }),
  tlPatch: (branch, id, body) => request("PATCH", `/api/trust/entries/${id}`, { query: { branch }, body }),
  tlResolve: (branch, id, status) => request("POST", `/api/trust/entries/${id}/resolve`, { query: { branch }, body: { status } }),
  tlDelete: (branch, id) => request("DELETE", `/api/trust/entries/${id}`, { query: { branch } }),
  tlLink: (branch, name) => request("POST", "/api/trust/parties/link", { query: { branch }, body: { name } }),
  tlUnlink: (branch, name) => request("DELETE", "/api/trust/parties/link", { query: { branch, name } }),
  tlParty: (token) => request("GET", `/api/trust/party/${encodeURIComponent(token)}`),
  tlPartyRespond: (token, id, body) => request("POST", `/api/trust/party/${encodeURIComponent(token)}/entries/${id}`, { body }),
  tlCashflow: (branch, q) => request("GET", "/api/cashflow/promises", { query: { branch, ...q }, timeout: 90000 }),
  tlPreview: (branch) => request("GET", "/api/proofs/preview", { query: { branch } }),
  tlProofs: (branch) => request("GET", "/api/proofs", { query: { branch } }),
  tlIssue: (branch, body) => request("POST", "/api/proofs", { query: { branch }, body }),
  tlRevoke: (branch, id) => request("POST", `/api/proofs/${id}/revoke`, { query: { branch } }),
  tlVerify: (packet) => request("POST", "/api/proofs/verify", { body: packet }),
  tlOpen: (id, body) => request("POST", `/api/proofs/${id}/open`, { body }),
  tlCheck: (body) => request("POST", "/api/proofs/check-openings", { body }),
  prGet: (branch) => request("GET", "/api/presence", { query: { branch } }),
  prPut: (branch, body) => request("PUT", "/api/presence", { query: { branch }, body }),
  prSuggest: (branch, lang) => request("POST", "/api/presence/suggest", { query: { branch }, body: { lang } }),
  prDrafts: (branch) => request("GET", "/api/presence/drafts", { query: { branch } }),
  prEdit: (branch, id, text) => request("PATCH", `/api/presence/drafts/${id}`, { query: { branch }, body: { text } }),
  prDecide: (branch, id, action) => request("POST", `/api/presence/drafts/${id}/${action}`, { query: { branch } }),
  prBoost: (branch, id, amount) => request("POST", `/api/presence/drafts/${id}/boost`, { query: { branch }, body: { amount } }),
  prLog: (branch) => request("GET", "/api/presence/log", { query: { branch } }),
  prPublic: (slug) => request("GET", `/api/presence/public/${encodeURIComponent(slug)}`),
  resolveRisk: (id) => request("POST", `/api/risks/${id}/resolve`),
};
