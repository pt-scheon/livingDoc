import { h, replace } from "../dom.js";
import { t, LANGS } from "../i18n.js";
import { api } from "../api.js";
import { dateTime } from "../format.js";

const SVG = "http://www.w3.org/2000/svg";
function brandMark() {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 32 32"); svg.setAttribute("class", "brand-mark"); svg.setAttribute("aria-hidden", "true");
  const parts = [["rect", { width: 32, height: 32, rx: 8, fill: "#b83a0a" }], ["path", { d: "M9 7h10l5 5v13H9z", fill: "#fff" }],
    ["path", { d: "M13 16h7M13 20h7", stroke: "#b83a0a", "stroke-width": 2, "stroke-linecap": "round" }]];
  for (const [tag, attrs] of parts) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    svg.append(n);
  }
  return svg;
}

export function createHeader(actions) {
  const branchSel = h("select", { class: "input", id: "branch", "aria-label": "Branch", onchange: (e) => actions.setBranch(e.target.value) });
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Language" });
  const badge = h("span", { class: "badge", id: "ai-badge" });
  const syncBadge = h("span", { class: "badge", id: "sync-badge" });
  const syncBtn = h("button", { class: "btn small", type: "button", id: "sync-btn", onclick: () => actions.syncNow() });
  const settingsBtn = h("button", { class: "btn small", type: "button", id: "settings-btn", onclick: () => actions.openSettings() });
  const download = h("a", { class: "btn small ghost", id: "download-md", download: "livingdoc.md" });
  const title = h("h1");
  const sub = h("small");

  const el = h("header", { class: "topbar" },
    h("div", { class: "brand" },
      brandMark(),
      h("div", {}, title, sub)),
    h("div", { class: "controls" }, branchSel, seg, badge, syncBadge, syncBtn, download, settingsBtn));
  let key = "";
  return {
    el,
    update(s) {
      const sig = JSON.stringify([s.lang, s.branch, s.branches, s.config?.llm, s.syncStatus, s.busySync]);
      if (sig === key) return;
      key = sig;
      const L = (k, v) => t(s.lang, k, v);
      title.textContent = L("title"); sub.textContent = L("brand_sub");
      branchSel.setAttribute("aria-label", L("branch"));
      replace(branchSel, s.branches.map((b) => h("option", { value: b, selected: b === s.branch }, b)));
      replace(seg, Object.entries(LANGS).map(([code, name]) =>
        h("button", { type: "button", "aria-pressed": String(code === s.lang), lang: code, onclick: () => actions.setLang(code) }, name)));
      const llm = s.config?.llm;
      replace(badge, h("span", { class: `dot ${llm?.online ? "on" : "off"}` }), llm?.online ? L("ai_online", { model: llm.model }) : L("ai_offline"));
      const last = s.syncStatus?.last_sync;
      replace(syncBadge, `${L("last_sync")}: ${last ? dateTime(last, s.lang) : L("never")}`);
      syncBtn.textContent = s.busySync ? L("syncing") : L("sync_now");
      syncBtn.disabled = !!s.busySync;
      settingsBtn.textContent = "⚙ " + L("settings");
      download.textContent = "⬇ " + L("download");
      if (s.branch) download.href = api.markdownUrl(s.branch, s.lang);
      document.documentElement.lang = s.lang;
      document.title = `${L("title")} · ${s.branch}`;
    },
  };
}
