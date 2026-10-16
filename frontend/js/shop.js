// The public shop page: only what the owner chose to publish. No login, no tracking, no stock, customers or debts.
import { api } from "./api.js";
import { h, replace } from "./dom.js";
import { t, LANGS } from "./i18n.js";
import { shortDate } from "./format.js";

const slug = new URLSearchParams(location.search).get("s") || "";
let lang = (() => { try { return localStorage.getItem("ld_shop_lang") || "en"; } catch { return "en"; } })();
if (!LANGS[lang]) lang = "en";
let data = null, failed = false, verdict = null;
const L = (k, v) => t(lang, k, v);
const app = document.getElementById("app");

function claimText(c) {
  const v = c.unit === "INR" ? Number(c.value).toLocaleString("en-IN") : c.unit === "share" ? `${Math.round(c.value * 100)}%` : c.value;
  return L(`sh_claim_${c.id}`, { v });
}

async function load() {
  try { data = await api.prPublic(slug); } catch { failed = true; }
  if (data) {
    document.title = data.name;
    const ld = document.createElement("script"); ld.type = "application/ld+json"; ld.textContent = JSON.stringify(data.jsonld); document.head.append(ld);
  }
  draw();
}

function draw() {
  document.documentElement.lang = lang;
  const bar = h("div", { class: "seg", role: "group" }, Object.entries(LANGS).map(([c, n]) => h("button", { type: "button", lang: c, "aria-pressed": String(c === lang),
    onclick: () => { lang = c; try { localStorage.setItem("ld_shop_lang", c); } catch { /* optional */ } draw(); } }, n)));
  if (failed) { replace(app, h("p", { class: "card", role: "alert", id: "sh-missing" }, L("sh_not_found"))); app.removeAttribute("aria-busy"); return; }
  if (!data) return;
  const posts = data.posts.filter((p) => p.lang === lang);
  const pr = data.proof;
  replace(app,
    h("header", { class: "card" }, h("h1", { class: "doc-title", id: "sh-name" }, data.name), data.tagline ? h("p", { id: "sh-tagline" }, data.tagline) : null,
      h("p", { class: "muted" }, [data.area, data.hours].filter(Boolean).join(" · ")), bar),
    data.about ? h("section", { class: "card" }, h("h2", {}, L("sh_about")), h("p", {}, data.about)) : null,
    data.products.length ? h("section", { class: "card", id: "sh-products" }, h("h2", {}, L("sh_products")), h("ul", { class: "pr-chips" }, data.products.map((n) => h("li", { class: "chip info" }, n)))) : null,
    posts.length ? h("section", { class: "card", id: "sh-posts" }, h("h2", {}, L("sh_news")), posts.map((p) => h("p", {}, p.text, " ", h("span", { class: "muted" }, shortDate(p.published_on, lang))))) : null,
    pr ? h("section", { class: "card", id: "sh-trust" }, h("h2", {}, "🛡️ ", L("sh_trust")), h("p", { class: "muted" }, L("sh_trust_hint")),
      h("ul", {}, pr.claims.map((c) => h("li", {}, claimText(c)))), h("p", { class: "muted", style: "font-size:.82rem" }, `${L("sh_valid_until", { d: shortDate(pr.valid_until, lang) })} · ${L("sh_scope")}`),
      h("button", { class: "btn", type: "button", id: "sh-verify", onclick: async () => { try { const r = await api.tlVerify(pr); verdict = r.valid; } catch { verdict = false; } draw(); } }, L("sh_verify")),
      verdict == null ? null : h("p", { class: `banner ${verdict ? "info" : "warn"}`, id: "sh-verdict", role: "status" }, verdict ? L("sh_ok") : L("sh_bad"))) : null,
    h("p", { class: "muted", style: "font-size:.8rem" }, L("sh_by_owner")));
  app.removeAttribute("aria-busy");
}
load();
