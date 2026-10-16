import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { qty, shortDate } from "../format.js";

export function createForecast() {
  const heading = h("h2", { id: "fc-h" });
  const body = h("div", { class: "table-wrap" });
  const el = h("section", { "aria-labelledby": "fc-h" }, heading, body);
  let key = "";
  return {
    el,
    update(s) {
      const sig = JSON.stringify([s.lang, s.doc?.forecast]);
      if (sig === key) return;
      key = sig;
      const L = (k) => t(s.lang, k);
      heading.textContent = L("forecast");
      const rows = s.doc?.forecast || [];
      replace(body, rows.length ? h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, L("item")), h("th", {}, L("festival")), h("th", {}, L("order_by")), h("th", { class: "num" }, L("order_qty")), h("th", {}, L("urgency")))),
        h("tbody", {}, rows.map((r) => h("tr", { "data-forecast": r.item },
          h("td", {}, r.item,
            h("details", {}, h("summary", {}, L("why")), h("div", { class: "muted", style: "font-size:.85rem;max-width:46ch" }, r.alert))),
          h("td", {}, r.festival_name || L("regular")),
          h("td", {}, shortDate(r.must_order_by, s.lang)),
          h("td", { class: "num" }, r.recommended_order_qty == null ? "-" : qty(r.recommended_order_qty, s.lang)),
          h("td", {}, h("span", { class: `chip ${r.urgency}` }, L(r.urgency)))))))
        : h("p", { class: "empty" }, L("no_forecast")));
    },
  };
}
