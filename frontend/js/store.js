// Minimal observable store: one state object, subscribers notified on every change.
const state = {
  config: null, branches: [], branch: "", lang: "en",
  doc: null, movements: [], notes: [], syncStatus: null,
  loading: true, online: true, lastError: null,
};
const subscribers = new Set();
export const getState = () => state;
export function setState(patch) {
  Object.assign(state, patch);
  subscribers.forEach((fn) => fn(state));
}
export function subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn); }

// localStorage can throw (private mode); preferences are a convenience only.
export const prefs = {
  get(key, fallback) { try { return localStorage.getItem("livingdoc." + key) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem("livingdoc." + key, value); } catch { /* ignore */ } },
};
