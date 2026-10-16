import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { shortDate } from "../format.js";

export function createSettings(actions) {
  let lang = "en", festivals = [], leadDays = 3;
  const title = h("h2");
  const listEl = h("div", { class: "table-wrap" });
  const lead = h("input", { id: "lead-days", type: "number", min: 0, max: 90, step: 1 });
  const leadLabel = h("span");
  const leadBtn = h("button", { class: "btn small", type: "button", id: "lead-save" });
  const inputs = {
    name: h("input", { id: "fe-name", required: true, maxLength: 80 }),
    date: h("input", { id: "fe-date", type: "date", required: true }),
    mult: h("input", { id: "fe-mult", type: "number", min: 1, max: 20, step: "0.1", value: 2, required: true }),
    black: h("input", { id: "fe-black", type: "number", min: 0, max: 60, step: 1, value: 3, required: true }),
  };
  const lbls = { name: h("span"), date: h("span"), mult: h("span"), black: h("span") };
  const addBtn = h("button", { class: "btn primary small", type: "submit", id: "fe-add" });
  const closeBtn = h("button", { class: "btn", type: "button", onclick: () => dlg.close() });
  const addForm = h("form", { class: "form-grid", onsubmit: async (e) => {
    e.preventDefault();
    try {
      const res = await api.addFestival({ name: inputs.name.value.trim(), date: inputs.date.value,
        surge_multiplier: Number(inputs.mult.value), supplier_blackout_days: Number(inputs.black.value) });
      festivals = res.festivals; inputs.name.value = ""; render(); actions.refresh();
    } catch (err) { actions.toast(err.message, "error"); }
  } }, ...Object.keys(inputs).map((k) => h("label", { class: "field", for: inputs[k].id }, lbls[k], inputs[k])), h("div", { style: "align-self:end" }, addBtn));
  const dlg = h("dialog", { id: "settings-dialog", "aria-labelledby": "settings-title" },
    h("div", { class: "dialog-body" }, h("div", { id: "settings-title" }, title), listEl,
      h("div", { class: "row" }, h("label", { class: "field", for: "lead-days", style: "min-width:240px" }, leadLabel, lead), h("div", { style: "align-self:end" }, leadBtn)),
      addForm, h("div", { class: "row", style: "justify-content:flex-end" }, closeBtn)));
  leadBtn.addEventListener("click", async () => {
    try { await api.setLeadDays(Number(lead.value)); actions.toast(t(lang, "lead_saved")); actions.refresh(); }
    catch (err) { actions.toast(err.message, "error"); }
  });

  function render() {
    const L = (k) => t(lang, k);
    title.textContent = L("settings_title");
    replace(listEl, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, L("fest_name")), h("th", {}, L("fest_date")), h("th", { class: "num" }, L("fest_mult")), h("th", { class: "num" }, L("fest_blackout")), h("th", {}))),
      h("tbody", {}, festivals.map((f) => h("tr", {},
        h("td", {}, f.name), h("td", {}, shortDate(f.date, lang) + " " + f.date.slice(0, 4)), h("td", { class: "num" }, f.surge_multiplier), h("td", { class: "num" }, f.supplier_blackout_days),
        h("td", {}, h("button", { class: "btn small ghost", type: "button", onclick: async () => {
          try { festivals = (await api.deleteFestival(f.name, f.date)).festivals; render(); actions.refresh(); } catch (err) { actions.toast(err.message, "error"); }
        } }, L("remove"))))))));
    leadLabel.textContent = L("lead_days"); lead.value = leadDays; leadBtn.textContent = L("save");
    lbls.name.textContent = L("fest_name"); lbls.date.textContent = L("fest_date"); lbls.mult.textContent = L("fest_mult"); lbls.black.textContent = L("fest_blackout");
    addBtn.textContent = L("add"); closeBtn.textContent = L("close");
  }

  return {
    el: dlg,
    update(s) { lang = s.lang; if (dlg.open) render(); },
    async open() {
      try { const r = await api.festivals(); festivals = r.festivals; leadDays = r.lead_days; } catch (err) { actions.toast(err.message, "error"); return; }
      render(); dlg.showModal();
    },
  };
}
