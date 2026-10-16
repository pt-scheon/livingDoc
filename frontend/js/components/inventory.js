import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { qty } from "../format.js";

export function createInventory(actions) {
  const body = h("div", { class: "table-wrap" });
  const f = {
    name: h("input", { id: "f-name", required: true, maxLength: 80 }),
    sku: h("input", { id: "f-sku", maxLength: 64 }),
    unit: h("input", { id: "f-unit", maxLength: 16, value: "pcs" }),
    min: h("input", { id: "f-min", type: "number", min: 0, step: "any" }),
    use: h("input", { id: "f-use", type: "number", min: 0, step: "any" }),
    shelf: h("input", { id: "f-shelf", type: "number", min: 0, step: 1 }),
    count: h("input", { id: "f-count", type: "number", min: 0, step: "any" }),
  };
  const labels = {};
  const field = (key, extra) => { labels[key] = h("span"); return h("label", { class: "field", for: f[key].id }, labels[key], f[key], extra || null); };
  const hint = h("span", { class: "muted", style: "font-size:.75rem" });
  const saveBtn = h("button", { class: "btn primary small", type: "submit", id: "item-save" });
  const summary = h("summary");
  const details = h("details", { style: "margin-top:12px", id: "item-details" }, summary,
    h("form", { style: "margin-top:10px;display:grid;gap:10px", onsubmit: async (e) => {
      e.preventDefault();
      const num = (el) => (el.value === "" ? null : Number(el.value));
      const ok = await actions.saveItem({
        name: f.name.value.trim(), sku: f.sku.value.trim() || null, unit: f.unit.value.trim() || null,
        min_stock: num(f.min), daily_use: num(f.use), shelf_life_days: num(f.shelf), counted: num(f.count),
      });
      if (ok) { f.count.value = ""; }
    } }, h("div", { class: "form-grid" }, field("name"), field("sku"), field("unit"), field("min"), field("use"), field("shelf"), field("count", hint)), h("div", {}, saveBtn)));
  const heading = h("h2", { id: "inv-h" });
  const el = h("section", { "aria-labelledby": "inv-h" }, heading, body, details);
  let key = "";

  return {
    el,
    update(s) {
      const L = (k) => t(s.lang, k);
      const sig = JSON.stringify([s.lang, s.doc?.inventory]);
      if (sig === key) return;
      key = sig;
      heading.textContent = L("inventory");
      summary.textContent = "➕ " + L("add_item");
      const names = { name: "item_name", sku: "sku", unit: "unit", min: "min", use: "daily_use", shelf: "shelf_life", count: "counted" };
      for (const [k, v] of Object.entries(names)) labels[k].textContent = L(v);
      hint.textContent = L("counted_hint");
      saveBtn.textContent = L("save");
      const rows = s.doc?.inventory || [];
      replace(body, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, L("item")), h("th", { class: "num" }, L("qty")), h("th", {}, L("unit")),
          h("th", { class: "num" }, L("min")), h("th", { class: "num" }, L("days_left")), h("th", {}, L("status")), h("th", {}))),
        h("tbody", {}, rows.map((r) => h("tr", { class: `is-${r.status}`, "data-item": r.name },
          h("td", {}, r.name, r.needs_review ? h("div", { class: "chip info", style: "margin-left:6px" }, L("needs_review")) : null),
          h("td", { class: "num" }, qty(r.qty, s.lang)), h("td", {}, r.unit),
          h("td", { class: "num" }, qty(r.min_stock, s.lang)),
          h("td", { class: "num" }, r.days_left == null ? "-" : qty(r.days_left, s.lang)),
          h("td", {}, h("span", { class: `chip ${r.status}` }, L(r.status))),
          h("td", {}, h("button", { class: "btn small ghost", type: "button", "aria-label": `${L("edit")} ${r.name}`, onclick: () => {
            f.name.value = r.name; f.sku.value = r.sku || ""; f.unit.value = r.unit; f.min.value = r.min_stock;
            f.use.value = r.daily_burn || ""; f.shelf.value = ""; f.count.value = r.qty;
            details.open = true; f.count.focus();
          } }, L("edit"))))))));
    },
  };
}
