import { h, replace } from "../dom.js";
import { t } from "../i18n.js";

export function createRisks(actions) {
  const heading = h("h2", { id: "risk-h" });
  const body = h("div");
  const el = h("section", { "aria-labelledby": "risk-h" }, heading, body);
  let key = "";
  return {
    el,
    update(s) {
      const sig = JSON.stringify([s.lang, s.doc?.risks]);
      if (sig === key) return;
      key = sig;
      const L = (k) => t(s.lang, k);
      heading.textContent = L("risks");
      const risks = s.doc?.risks || [];
      replace(body, risks.length ? h("ul", { class: "list" }, risks.map((r) => h("li", { class: "risk" },
        h("div", { class: "row" }, h("span", {}, "⚠️ ", r.text),
          r.kind === "noted" ? h("button", { class: "btn small", type: "button", onclick: () => actions.resolveRisk(r.id) }, L("resolve")) : null))))
        : h("p", { class: "empty" }, L("no_risks")));
    },
  };
}
