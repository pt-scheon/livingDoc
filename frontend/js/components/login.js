import { h, replace } from "../dom.js";
import { t, LANGS } from "../i18n.js";
import { api } from "../api.js";
import { brandMark } from "./shell.js";

/**
 * Full-screen sign in / create account.
 * st is the /api/auth/status answer: st.setup (no account yet), st.needs_setup_code, st.deployment_password.
 * opts: { mode: "in" | "up", onCancel } . onDone() runs after success.
 */
export function showLogin(root, lang, st, onDone, onLang, opts = {}) {
  const L = (k, v) => t(lang, k, v);
  let mode = opts.mode || (st.setup && !st.deployment_password ? "up" : "in");
  let useDeploy = false;
  const msg = h("p", { id: "login-msg", role: "alert", class: "muted" });
  const field = (id, label, attrs = {}) => { const i = h("input", { id, required: true, ...attrs }); return [h("label", { class: "field", for: id }, label, i), i]; };

  function draw() {
    msg.textContent = "";
    const tabs = h("div", { class: "seg", role: "tablist" },
      h("button", { type: "button", role: "tab", id: "au-tab-in", "aria-pressed": String(mode === "in"), onclick: () => { mode = "in"; draw(); } }, L("au_tab_in")),
      h("button", { type: "button", role: "tab", id: "au-tab-up", "aria-pressed": String(mode === "up"), onclick: () => { mode = "up"; draw(); } }, L("au_tab_up")));
    const seg = h("div", { class: "seg", role: "group" }, Object.entries(LANGS).map(([c, n]) => h("button", { type: "button", lang: c, "aria-pressed": String(c === lang), onclick: () => onLang(c) }, n)));
    const cancel = opts.onCancel ? h("button", { class: "btn ghost", type: "button", id: "login-cancel", onclick: opts.onCancel }, L("au_close")) : null;
    let body, title, sub;
    if (mode === "in") {
      title = L("au_signin_title"); sub = L("au_signin_sub");
      const [fe, email] = field("login-email", L("au_email"), { type: "email", autocomplete: "username", required: !useDeploy });
      const [fp, pw] = field("login-pw", useDeploy ? L("au_deploy_pw") : L("au_password"), { type: "password", autocomplete: "current-password" });
      if (useDeploy) fe.hidden = true;
      const toggle = st.deployment_password ? h("button", { class: "btn ghost small", type: "button", id: "login-toggle", onclick: () => { useDeploy = !useDeploy; draw(); } }, useDeploy ? L("au_use_email") : L("au_use_deploy")) : null;
      body = h("form", { class: "login-card", onsubmit: async (e) => {
        e.preventDefault(); msg.textContent = "";
        try { await api.login(useDeploy ? "" : email.value, pw.value); onDone(); }
        catch (err) { msg.textContent = err.status === 429 ? L("au_wait") : useDeploy ? L("au_bad_pw") : L("au_bad"); pw.select(); }
      } }, brandMark(), h("h1", {}, title), h("p", { class: "muted" }, sub), fe, fp, msg, h("button", { class: "btn primary", type: "submit", id: "login-btn" }, L("au_signin_btn")), toggle);
    } else {
      const first = st.setup;
      title = first ? L("au_su_title_first") : L("au_su_title_join"); sub = first ? L("au_su_sub_first") : L("au_su_sub_join");
      const [fn, name] = field("su-name", L("au_name"), { maxLength: 60, autocomplete: "name" });
      const [fe, email] = field("su-email", L("au_email"), { type: "email", maxLength: 120, autocomplete: "email" });
      const [fp, pw] = field("su-pw", L("au_password"), { type: "password", minLength: 8, maxLength: 200, autocomplete: "new-password", "aria-describedby": "su-hint" });
      const [fc, pw2] = field("su-pw2", L("au_confirm"), { type: "password", maxLength: 200, autocomplete: "new-password" });
      const needCode = !first || st.needs_setup_code;
      const [fcode, code] = needCode ? field("su-code", first ? L("au_code_setup") : L("au_code_invite"), { maxLength: 200, autocomplete: "off" }) : [null, null];
      body = h("form", { class: "login-card", onsubmit: async (e) => {
        e.preventDefault(); msg.textContent = "";
        if (pw.value !== pw2.value) { msg.textContent = L("au_mismatch"); return; }
        try { await api.signup({ name: name.value, email: email.value, password: pw.value, code: code ? code.value : "" }); onDone(); }
        catch (err) { msg.textContent = err.status === 429 ? L("au_wait") : err.message; }
      } }, brandMark(), h("h1", {}, title), h("p", { class: "muted" }, sub), fn, fe, fp, h("small", { class: "muted", id: "su-hint" }, L("au_pw_hint")), fc, fcode, msg,
        h("button", { class: "btn primary", type: "submit", id: "su-btn" }, L("au_su_btn")));
    }
    body.append(tabs, seg);
    if (cancel) body.append(cancel);
    replace(root, h("div", { class: "login-wrap" }, body));
    (body.querySelector("input:not([hidden])") || body).focus?.();
  }
  draw();
}
