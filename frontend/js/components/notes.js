import { h, replace } from "../dom.js";
import { t, SPEECH_LANG } from "../i18n.js";
import { dateTime } from "../format.js";

export function createNotes(actions) {
  const heading = h("h2", { id: "notes-h" });
  const label = h("label", { class: "visually-hidden", for: "note-text" });
  const area = h("textarea", { id: "note-text", rows: 7, maxLength: 5000, "aria-describedby": "notes-h" });
  const submit = h("button", { class: "btn primary", type: "submit", id: "note-submit" });
  const mic = h("button", { class: "btn", type: "button", id: "mic-btn" });
  const result = h("div", { id: "note-result", "aria-live": "polite" });
  const historyH = h("h3", { class: "muted", style: "font-size:.9rem;margin:16px 0 6px" });
  const history = h("ul", { class: "list", id: "note-history" });
  let busy = false, listening = false, recognition = null, baseText = "", current = null, resultState = null;

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  const form = h("form", { onsubmit: async (e) => {
    e.preventDefault();
    const text = area.value.trim();
    if (!text || busy) return;
    busy = true; render();
    try {
      resultState = await actions.submitNote(text);
      if (resultState) area.value = "";
    } finally { busy = false; render(); }
  } }, h("div", { class: "field" }, label, area), h("div", { class: "row", style: "margin-top:10px" }, submit, SR ? mic : null));
  area.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") form.requestSubmit(); });

  mic.addEventListener("click", () => {
    if (!SR) return actions.toast(t(current.lang, "mic_unsupported"), "error");
    if (listening) { recognition.stop(); return; }
    recognition = new SR();
    recognition.lang = SPEECH_LANG[current.lang] || "en-IN";
    recognition.interimResults = true; recognition.continuous = true;
    baseText = area.value ? area.value.trimEnd() + " " : "";
    recognition.onresult = (ev) => {
      let txt = "";
      for (const r of ev.results) txt += r[0].transcript;
      area.value = baseText + txt;
    };
    recognition.onend = () => { listening = false; render(); };
    recognition.onerror = () => { listening = false; render(); };
    recognition.start(); listening = true; render();
  });

  const el = h("section", { class: "card", "aria-labelledby": "notes-h" }, heading, form, result, historyH, history);

  function renderResult(lang) {
    if (!resultState) return replace(result);
    const lines = resultState.lines || [];
    replace(result, h("div", { class: "result" },
      h("strong", {}, t(lang, "applied")), " ",
      h("span", { class: "muted", style: "color:inherit;opacity:.8" }, `(${t(lang, "extractor")}: ${resultState.extractor?.startsWith("llm") ? t(lang, "extractor_llm") : t(lang, "extractor_rules")})`),
      lines.length ? h("ul", {}, lines.map((l) => h("li", {}, l))) : h("p", { style: "margin:6px 0 0" }, t(lang, "nothing_recorded")),
      h("details", { style: "margin-top:8px" }, h("summary", {}, t(lang, "deltas_view")),
        h("pre", { class: "json" }, JSON.stringify(resultState.deltas, null, 2)))));
  }

  function render() {
    if (!current) return;
    const L = (k) => t(current.lang, k);
    heading.textContent = L("notes_header");
    label.textContent = L("notes_label");
    area.placeholder = L("notes_hint");
    submit.textContent = busy ? L("processing") : L("process_btn");
    submit.disabled = busy;
    mic.textContent = "🎤 " + (listening ? L("mic_stop") : L("mic_start"));
    mic.setAttribute("aria-pressed", String(listening));
    renderResult(current.lang);
    historyH.textContent = L("notes_history");
    const notes = current.notes || [];
    replace(history, notes.length ? notes.map((n) => h("li", {}, h("div", {},
      h("div", { class: "muted", style: "font-size:.78rem" }, `${dateTime(n.ts, current.lang)} · ${n.extractor?.startsWith("llm") ? L("extractor_llm") : L("extractor_rules")}`),
      h("div", {}, n.raw.length > 140 ? n.raw.slice(0, 140) + "…" : n.raw))))
      : [h("li", { class: "empty" }, L("no_notes"))]);
  }

  return { el, update(s) { current = s; render(); } };
}
