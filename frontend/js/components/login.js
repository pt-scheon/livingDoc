import { h, replace } from "../dom.js";
import { t, LANGS } from "../i18n.js";
import { api } from "../api.js";
import { brandMark } from "./shell.js";

/** Full-screen owner sign-in. onDone() is called after a successful login. */
export function showLogin(root, lang, onDone, onLang) {
  const pw = h("input", { type: "password", id: "login-pw", autocomplete: "current-password", required: true, "aria-describedby": "login-msg" });
  const msg = h("p", { id: "login-msg", role: "alert", class: "muted" });
  const L = (k) => t(lang, k);
  const seg = h("div", { class: "seg", role: "group" }, Object.entries(LANGS).map(([c, n]) => h("button", { type: "button", lang: c, "aria-pressed": String(c === lang), onclick: () => onLang(c) }, n)));
  const form = h("form", { class: "login-card", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "";
    try { await api.login(pw.value); onDone(); }
    catch (err) { msg.textContent = err.status === 429 ? L("login_wait") : L("login_bad"); pw.select(); }
  } }, brandMark(), h("h1", {}, L("login_title")), h("p", { class: "muted" }, L("login_sub")),
    h("label", { class: "field" }, L("login_pw"), pw), msg, h("button", { class: "btn primary", type: "submit", id: "login-btn" }, L("login_btn")), seg);
  replace(root, h("div", { class: "login-wrap" }, form));
  pw.focus();
}
