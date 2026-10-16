import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { dateTime, qty } from "../format.js";

const ICON = { scanner: "📷", note: "🎙️", count: "🧮", seed: "🌱", sync: "🔄" };

export function createScanner(actions) {
  const heading = h("h2", { id: "scan-h" });
  const itemSel = h("select", { id: "scan-item", class: "input" });
  const qtyIn = h("input", { id: "scan-qty", type: "number", min: 1, step: "any", value: 1 });
  const dirSel = h("select", { id: "scan-dir", class: "input" });
  const btn = h("button", { class: "btn small primary", type: "submit", id: "scan-btn" });
  const lItem = h("span"), lQty = h("span"), lDir = h("span");
  const sumEl = h("summary");
  const feedH = h("h3", { class: "muted", style: "font-size:.9rem;margin:14px 0 6px" });
  const feed = h("ul", { class: "feed list", id: "move-feed" });
  const form = h("form", { class: "form-grid", style: "margin-top:10px", onsubmit: (e) => {
    e.preventDefault();
    if (itemSel.value) actions.scan(itemSel.value, Number(qtyIn.value) || 1, dirSel.value);
  } },
    h("label", { class: "field", for: "scan-item" }, lItem, itemSel),
    h("label", { class: "field", for: "scan-qty" }, lQty, qtyIn),
    h("label", { class: "field", for: "scan-dir" }, lDir, dirSel),
    h("div", { style: "align-self:end" }, btn));
  const el = h("section", { class: "card", "aria-labelledby": "scan-h" }, heading, h("details", {}, sumEl, form), feedH, feed);
  let key = "";
  return {
    el,
    update(s) {
      const sig = JSON.stringify([s.lang, s.doc?.inventory?.map((i) => i.name), s.movements]);
      if (sig === key) return;
      key = sig;
      const L = (k) => t(s.lang, k);
      heading.textContent = L("scanner");
      sumEl.textContent = L("scan_sim");
      lItem.textContent = L("item"); lQty.textContent = L("qty"); lDir.textContent = L("direction");
      btn.textContent = L("scan_btn");
      const prev = itemSel.value, prevDir = dirSel.value || "out";
      replace(itemSel, (s.doc?.inventory || []).map((i) => h("option", { value: i.name, selected: i.name === prev }, i.name)));
      replace(dirSel, [h("option", { value: "out", selected: prevDir === "out" }, L("out_dir")), h("option", { value: "in", selected: prevDir === "in" }, L("in"))]);
      feedH.textContent = L("movements");
      const mv = s.movements || [];
      replace(feed, mv.length ? mv.map((m) => h("li", {},
        h("span", {}, `${ICON[m.source] || "•"} ${m.item}`),
        h("span", {}, h("span", { class: m.change >= 0 ? "delta-pos" : "delta-neg" }, (m.change >= 0 ? "+" : "") + qty(m.change, s.lang)), " ",
          h("span", { class: "muted", style: "font-size:.75rem" }, dateTime(m.ts, s.lang)))))
        : [h("li", { class: "empty" }, L("no_movements"))]);
    },
  };
}
