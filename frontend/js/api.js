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
  resolveRisk: (id) => request("POST", `/api/risks/${id}/resolve`),
};
