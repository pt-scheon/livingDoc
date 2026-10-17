// "Account" dialog: who I am, change my password, and (owners) invite or remove people.
import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { shortDate } from "../format.js";

export function createAccount(actions) {
  let lang = "en", me = null, data = { users: [], invites: [] }, newCode = "", role = "staff";
  const L = (k, v) => t(lang, k, v);
  const body = h("div", { class: "dialog-body" });
  const dlg = h("dialog", { id: "account-dialog", "aria-label": "Account" }, body);
  const date = (iso) => (iso ? shortDate(iso.slice(0, 10), lang) : L("au_never"));

  function pwForm() {
    const cur = h("input", { id: "ac-cur", type: "password", autocomplete: "current-password", required: true, maxLength: 200 });
    const nw = h("input", { id: "ac-new", type: "password", autocomplete: "new-password", required: true, minLength: 8, maxLength: 200 });
    return h("form", { class: "form-grid", onsubmit: async (e) => {
      e.preventDefault();
      try { await api.changePassword(cur.value, nw.value); actions.toast(L("au_pw_saved")); cur.value = ""; nw.value = ""; }
      catch (err) { actions.toast(err.message, "error"); }
    } }, h("label", { class: "field" }, L("au_current"), cur), h("label", { class: "field" }, L("au_new"), nw),
      h("div", { style: "align-self:end" }, h("button", { class: "btn small primary", type: "submit", id: "ac-pw-save" }, L("au_change_pw"))));
  }

  async function reload() {
    try { data = await api.authUsers(); } catch { data = { users: [], invites: [] }; }
    draw();
  }

  function team() {
    const sel = h("select", { id: "ac-role", "aria-label": L("au_invite_role"), onchange: (e) => { role = e.target.value; } },
      h("option", { value: "staff", selected: role === "staff" }, L("au_role_staff_l")), h("option", { value: "owner", selected: role === "owner" }, L("au_role_owner_l")));
    const make = h("button", { class: "btn small primary", type: "button", id: "ac-invite", onclick: async () => {
      try { const r = await api.makeInvite(role); newCode = r.code; actions.toast(L("au_invite_made")); await reload(); } catch (err) { actions.toast(err.message, "error"); }
    } }, L("au_invite_make"));
    return [h("h3", {}, L("au_team")),
      h("div", { class: "table-wrap" }, h("table", { id: "ac-users" }, h("tbody", {}, data.users.map((u) => h("tr", {},
        h("td", {}, u.name, u.id === me.id ? ` (${L("au_you")})` : ""), h("td", {}, u.email), h("td", {}, L(`au_role_${u.role}`)), h("td", { class: "muted" }, `${L("au_last")}: ${date(u.last_login)}`),
        h("td", {}, u.id === me.id ? null : h("button", { class: "btn small ghost", type: "button", onclick: async () => {
          try { await api.removeUser(u.id); actions.toast(L("au_removed")); await reload(); } catch (err) { actions.toast(err.message, "error"); }
        } }, L("au_remove")))))))),
      h("div", { class: "row" }, h("label", { class: "field" }, L("au_invite_role"), sel), h("div", { style: "align-self:end" }, make)),
      newCode ? h("p", { class: "banner info", id: "ac-newcode", role: "status" }, h("b", { class: "mono" }, newCode), " ", L("au_invite_note")) : null,
      data.invites.length ? [h("h3", {}, L("au_pending")), h("ul", {}, data.invites.map((i) => inviteRow(i)))] : null];
  }

  function inviteRow(i) {
    const cancel = h("button", { class: "btn small ghost", type: "button", onclick: async () => { await api.revokeInvite(i.id); await reload(); } }, L("au_revoke"));
    return h("li", {}, `…${i.hint} · ${L(`au_role_${i.role}`)} `, cancel);
  }

  function draw() {
    if (!me) return;
    replace(body, h("h2", {}, L("au_account")), h("p", { id: "ac-who" }, L("au_signed_as", { name: me.name, role: L(`au_role_${me.role}`) }), " · ", me.email),
      h("h3", {}, L("au_change_pw")), pwForm(), me.role === "owner" ? team() : null,
      h("div", { class: "row", style: "justify-content:flex-end" }, h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, L("au_close"))));
  }

  return {
    el: dlg,
    update(s) { lang = s.lang; me = s.auth.user; if (dlg.open) draw(); },
    async open() { newCode = ""; if (!me) return; draw(); dlg.showModal(); if (me.role === "owner") await reload(); },
  };
}
