import { h } from "./dom.js";
export function toast(message, kind = "info", ms = 4500) {
  const host = document.getElementById("toasts");
  if (!host) return;
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  host.append(el);
  setTimeout(() => el.remove(), ms);
}
