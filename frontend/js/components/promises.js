import { h, replace } from "../dom.js";
import { t } from "../i18n.js";

export function createPromises(actions) {
  const heading = h("h2", { id: "prom-h" });
  const body = h("div");
  const el = h("section", { "aria-labelledby": "prom-h" }, heading, body);
  let key = "";
  return {
    el,
    update(s) {
      const sig = JSON.stringify([s.lang, s.doc?.promises]);
      if (sig === key) return;
      key = sig;
      const L = (k) => t(s.lang, k);
      heading.textContent = L("promises");
      const list = s.doc?.promises || [];
      replace(body, list.length ? h("ul", { class: "list" }, list.map((p) => h("li", {},
        h("label", { class: `check ${p.done ? "done" : ""}` },
          h("input", { type: "checkbox", checked: p.done, onchange: (e) => actions.setPromise(p.id, e.target.checked) }),
          h("span", {}, h("strong", {}, p.person), ": ", p.task))))) : h("p", { class: "empty" }, L("no_promises")));
    },
  };
}
