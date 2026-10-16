const LOCALES = { en: "en-IN", hi: "hi-IN", gu: "gu-IN" };

export function money(amount, currency = "₹", lang = "en") {
  const n = Number(amount) || 0;
  const frac = Math.abs(n - Math.round(n)) < 0.005 ? 0 : 2;
  return currency + n.toLocaleString(LOCALES[lang] || "en-IN", { minimumFractionDigits: frac, maximumFractionDigits: frac });
}
export function qty(n, lang = "en") {
  return Number(n).toLocaleString(LOCALES[lang] || "en-IN", { maximumFractionDigits: 2 });
}
// "2026-10-17" or "2026-10-17 10:20:00" -> local Date (avoids the UTC off-by-one of new Date("YYYY-MM-DD")).
export function parseDate(s) {
  if (!s) return null;
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0)) : null;
}
export function shortDate(s, lang = "en") {
  const d = parseDate(s);
  return d ? new Intl.DateTimeFormat(LOCALES[lang] || "en-IN", { day: "numeric", month: "short" }).format(d) : "-";
}
export function dateTime(s, lang = "en") {
  const d = parseDate(s);
  return d ? new Intl.DateTimeFormat(LOCALES[lang] || "en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(d) : "-";
}
export const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
