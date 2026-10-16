import { h, replace } from "../dom.js";
import { t } from "../i18n.js";
import { money, shortDate } from "../format.js";

export function createCash() {
  const heading = h("h2", { id: "cash-h" });
  const body = h("div");
  const el = h("section", { "aria-labelledby": "cash-h" }, heading, body);
  let key = "";
  return {
    el,
    update(s) {
      const sig = JSON.stringify([s.lang, s.doc?.cash]);
      if (sig === key) return;
      key = sig;
      const L = (k) => t(s.lang, k);
      const c = s.doc?.cash, cur = s.doc?.currency || "₹";
      heading.textContent = L("cash");
      if (!c) return replace(body);
      const stat = (label, val) => h("div", { class: "stat" }, h("b", {}, money(val, cur, s.lang)), h("span", {}, label));
      replace(body,
        h("div", { class: "stats" }, stat(L("total_collected"), c.total_collected), stat(L("collected_today"), c.collected_today), stat(L("pending"), c.pending_total)),
        c.debts.length ? h("ul", { class: "list" }, c.debts.map((d) => h("li", {},
          h("span", {}, h("strong", {}, d.entity), ` · ${money(d.balance, cur, s.lang)} `, h("span", { class: "muted" }, `(${L("since")} ${shortDate(d.since, s.lang)})`)))))
          : h("p", { class: "empty" }, L("no_pending")));
    },
  };
}
