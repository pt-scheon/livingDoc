// Tiny hyperscript helper. Text is always inserted as text nodes (never innerHTML), so user data cannot inject markup.
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, val] of Object.entries(props || {})) {
    if (val == null || val === false) continue;
    if (key === "class") el.className = val;
    else if (key === "for") el.htmlFor = val;
    else if (key === "dataset") Object.assign(el.dataset, val);
    else if (key.startsWith("on") && typeof val === "function") el.addEventListener(key.slice(2).toLowerCase(), val);
    else if (key in el && !key.includes("-")) { try { el[key] = val; } catch { el.setAttribute(key, val); } }
    else el.setAttribute(key, val === true ? "" : val);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
export const clear = (el) => el.replaceChildren();
export function replace(el, ...children) { el.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false)); }
