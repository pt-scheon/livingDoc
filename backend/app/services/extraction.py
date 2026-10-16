"""LLM extraction of structured JSON deltas, strict validation, rule-based fallback, and the
deterministic code that applies deltas to SQLite."""
import hashlib
import json
import re
import time
import urllib.request
from datetime import date

from ..config import settings, now_dt, now_str, parse_ts
from ..database import add_risk, db, ensure_branch
from ..textutil import fmt_money, fmt_qty
from . import ledger
from .inventory import apply_movement, resolve_item

add_cash_event = ledger.add_cash_event
add_promise = ledger.add_promise
_LLM_DOWN_UNTIL = 0.0


# ------------------------------------------------------------ extraction ---
SYSTEM_PROMPT = """You extract structured business events from a shopkeeper's messy notes.
The notes may be English, Hindi, Gujarati or a mix (Hinglish). Reply with ONE JSON object ONLY, no prose:
{
  "inventory_deltas": [{"item": "str", "change": -2}],
  "cash_events": [{"type": "collected|owed", "entity": "str", "amount": 50.0, "desc": "str"}],
  "promises": [{"person": "str", "task": "str", "completed": false}],
  "quiet_risk": "str"
}
Rules:
- inventory_deltas: negative for sold/used/wasted/given away, positive for bought/received/restocked. Use the exact
  names from KNOWN_ITEMS when an item matches; otherwise a short singular English name. Never invent quantities.
- cash_events: "collected" = money actually received now; "owed" = a customer owes the business money (credit/udhar).
  amount is a positive number in plain digits (no currency symbols). entity = person or company.
- promises: favours, reminders and commitments ("remind me to order beans", "I told Dave I'd deliver Friday").
  completed=true only if the note says it was done.
- quiet_risk: one short sentence for any hidden problem (supplier trouble, running out, tired owner, unpaid dues,
  things only one person knows). Empty string if none.
- Use empty lists when nothing applies. Do not repeat the same event twice."""


def _http_chat(messages):
    body = {"model": settings.llm_model, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        settings.llm_base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.llm_api_key}",
                 "User-Agent": "LivingDoc/1.0"})
    with urllib.request.urlopen(req, timeout=settings.llm_timeout) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def parse_json_loose(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def _to_float(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(v or ""))
        if not m:
            return None
        x = float(m.group(0).replace(",", ""))
    return x if x == x and abs(x) < 1e9 else None


CASH_ALIASES = {"collected": "collected", "paid": "collected", "received": "collected", "income": "collected",
                "payment": "collected", "cash": "collected", "owed": "owed", "owe": "owed", "credit": "owed",
                "due": "owed", "pending": "owed", "udhar": "owed", "unpaid": "owed"}


def sanitize_deltas(obj):
    """Validate untrusted LLM output into the exact delta schema; drop anything malformed."""
    out = {"inventory_deltas": [], "cash_events": [], "promises": [], "quiet_risk": ""}
    if not isinstance(obj, dict):
        return out
    for d in obj.get("inventory_deltas") or []:
        if not isinstance(d, dict):
            continue
        item, ch = str(d.get("item") or "").strip(), _to_float(d.get("change"))
        if item and ch and abs(ch) > 1e-9:
            out["inventory_deltas"].append({"item": item[:80], "change": ch})
    for d in obj.get("cash_events") or []:
        if not isinstance(d, dict):
            continue
        t = CASH_ALIASES.get(str(d.get("type") or "").strip().lower())
        amt = _to_float(d.get("amount"))
        if t and amt and abs(amt) > 0:
            out["cash_events"].append({"type": t, "entity": str(d.get("entity") or "").strip()[:80] or "Walk-in",
                                       "amount": abs(amt), "desc": str(d.get("desc") or "")[:200]})
    for d in obj.get("promises") or []:
        if not isinstance(d, dict):
            continue
        task = str(d.get("task") or "").strip()
        if task:
            comp = d.get("completed")
            if isinstance(comp, str):
                comp = comp.strip().lower() in ("true", "yes", "1", "done")
            out["promises"].append({"person": str(d.get("person") or "").strip()[:80] or "Me",
                                    "task": task[:200], "completed": bool(comp)})
    qr = obj.get("quiet_risk")
    out["quiet_risk"] = qr.strip()[:300] if isinstance(qr, str) else ""
    return out


NUMWORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "fifteen": 15, "twenty": 20}
UNITS = {"kg", "kgs", "g", "gm", "l", "ltr", "litre", "litres", "liter", "liters", "pack", "packs", "packet",
         "packets", "box", "boxes", "pcs", "pc", "piece", "pieces", "unit", "units", "bottle", "bottles",
         "bag", "bags", "cup", "cups", "tray", "trays"}
ITEM_STOP = {"and", "to", "for", "from", "today", "yesterday", "at", "with", "on", "in", "by", "also", "so", "this",
             "that", "morning", "evening", "tonight", "after", "before", "because", "when", "as", "while"}
OUT_VERBS = r"sold|sell|used|use|consumed|wasted|spoiled|spoilt|damaged|expired|dispatched|issued|gave away|threw away"
IN_VERBS = r"bought|buy|received|restocked|purchased|stocked|added|got|delivered"
MONEY_RE = re.compile(r"(?:\b(?:rs\.?|inr|usd)|[₹$])\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:rs\b\.?|rupees|inr\b|dollars|bucks)", re.I)
OWED_KW = re.compile(r"\b(owes?|owed|due|pending|credit|udhar|baki|unpaid|pay later|pays later)\b", re.I)
PAID_KW = re.compile(r"\b(paid|pays|collected|received|gave|settled|deposited|cash)\b", re.I)
PROMISE_RE = re.compile(
    r"\b(?:remind(?:ed|s)?\s+me\s+to|remind(?:ed|s)?\s+me\s+about|remember\s+to|need(?:s)?\s+to|(?:have|has)\s+to|must|"
    r"should|promised\s+to|promise(?:s|d)?\s+to|will\s+(?=(?:send|bring|call|pay|deliver|return|give)\b))\s*(.+)$", re.I)
RISK_RE = re.compile(r"\b(running low|ran out|out of|short of|delayed|delay|late|broke|broken|spoil|expired|complain|"
                     r"can't|cannot|no one|only i|alone|forgot|behind|unpaid|bounced|leak|closed|shut|price (?:hike|increase)|"
                     r"increased the price|exhausted|tired)\b", re.I)
CAP_STOP = {"I", "Sold", "Used", "Remind", "Reminded", "Paid", "Got", "Bought", "Received", "Rs", "Need", "Also",
            "Today", "Yesterday", "The", "We", "He", "She", "They", "Cash", "Remember", "Must", "Should", "Will",
            "Gave", "Collected", "Settled", "Used", "Sell", "Use", "Have", "Has", "My", "Our"}
CAP_RE = re.compile(r"[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)*")


def _first_name(clause: str):
    for m in CAP_RE.finditer(clause):
        words = [w for w in m.group(0).split() if w not in CAP_STOP]
        if words:
            return " ".join(words)
    return None


def rule_based_extract(text: str):
    """Best-effort deterministic English fallback used when no LLM is reachable."""
    out = {"inventory_deltas": [], "cash_events": [], "promises": [], "quiet_risk": ""}
    risks, last_entity = [], None
    clauses = [c.strip() for c in re.split(r",(?!\d{3}\b)|;|\n|(?<!\d)\.(?!\d)|\bbut\b|\bthen\b", text) if c.strip()]
    for clause in clauses:
        name = _first_name(clause)
        work = clause
        m_money = MONEY_RE.search(clause)
        if m_money:
            amt = float((m_money.group(1) or m_money.group(2)).replace(",", ""))
            ctype = "owed" if OWED_KW.search(clause) else ("collected" if PAID_KW.search(clause) else None)
            if ctype:
                out["cash_events"].append({"type": ctype, "entity": name or "Walk-in", "amount": amt, "desc": clause[:200]})
            work = clause[:m_money.start()] + " " + clause[m_money.end():]
        if name:
            last_entity = name
        m_inv = re.search(rf"\b({OUT_VERBS}|{IN_VERBS})\b(.*)$", work, re.I)
        if m_inv and not (m_money and PAID_KW.search(clause) and not re.search(r"\d", work)):
            sign = -1 if re.fullmatch(OUT_VERBS, m_inv.group(1), re.I) else 1
            toks = re.findall(r"\d[\d,]*(?:\.\d+)?|[A-Za-z']+", m_inv.group(2))
            i = 0
            while i < len(toks):
                t = toks[i].lower()
                num = None
                if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", t):
                    num = float(t.replace(",", ""))
                elif t in NUMWORDS and i + 1 < len(toks):
                    num = float(NUMWORDS[t])
                if num is None:
                    i += 1
                    continue
                j, words = i + 1, []
                while j < len(toks) and len(words) < 3:
                    w = toks[j].lower()
                    if w in ITEM_STOP or re.fullmatch(r"\d[\d,]*(?:\.\d+)?", w) or (w in NUMWORDS and w not in ("a", "an")):
                        break
                    words.append(w)
                    j += 1
                if words and words[0] in UNITS and len(words) > 1:
                    words = words[1:]
                    if words and words[0] == "of":
                        words = words[1:]
                words = [w for w in words if w != "of"]
                if words:
                    out["inventory_deltas"].append({"item": " ".join(words), "change": sign * num})
                i = max(j, i + 1)
        m_prom = PROMISE_RE.search(clause)
        if m_prom:
            out["promises"].append({"person": name or last_entity or "Me", "task": m_prom.group(1).strip(),
                                    "completed": bool(re.search(r"\b(done|finished|completed|already)\b", clause, re.I))})
        if RISK_RE.search(clause):
            risks.append(clause)
    out["quiet_risk"] = "; ".join(risks)[:300]
    return out


def extract_deltas(text, known_items):
    """LLM first (structured JSON only); deterministic rules if the model is unreachable or returns nothing."""
    global _LLM_DOWN_UNTIL
    reason = None
    if time.time() >= _LLM_DOWN_UNTIL:
        try:
            msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"TODAY: {date.today().isoformat()}\nKNOWN_ITEMS: {json.dumps(known_items, ensure_ascii=False)}\n\nNOTE:\n{text}"}]
            d = sanitize_deltas(parse_json_loose(_http_chat(msgs)))
            if d["inventory_deltas"] or d["cash_events"] or d["promises"] or d["quiet_risk"]:
                return d, "llm"
            reason = "LLM returned no events"
        except Exception as e:  # network, HTTP, JSON - never crash the shop
            _LLM_DOWN_UNTIL = time.time() + 60
            reason = f"LLM unavailable ({type(e).__name__})"
    return sanitize_deltas(rule_based_extract(text)), f"rules - {reason}" if reason else "rules"


def apply_deltas(branch, deltas, raw, extractor):
    """Execute validated deltas in ONE transaction: stock math, cash settlement, promises, risks."""
    lines = []
    with db() as c:
        ensure_branch(c, branch)
        for d in deltas["inventory_deltas"]:
            name, created = resolve_item(c, branch, d["item"])
            r = apply_movement(c, branch, name, d["change"], "note", raw[:120])
            sign = "+" if d["change"] > 0 else ""
            lines.append(f"📦 {name}: {sign}{fmt_qty(d['change'])} → {fmt_qty(r['qty'])}" + (" (new item)" if created else ""))
            if r["short"] > 0:
                add_risk(c, branch, f"{name}: note said {fmt_qty(abs(d['change']))} left stock but the shelf only had "
                                    f"{fmt_qty(abs(d['change']) - r['short'])} - a delivery or purchase was probably never entered.", "auto")
                lines.append(f"⚠️ {name}: {fmt_qty(r['short'])} more went out than were in stock; stock set to 0 and flagged")
        for e in deltas["cash_events"]:
            _, settled = add_cash_event(c, branch, e["type"], e["entity"], e["amount"], e["desc"])
            tag = "collected" if e["type"] == "collected" else "owed"
            extra = f" (settled {fmt_money(settled)} of their debt)" if settled > 0 else ""
            lines.append(f"💰 {e['entity']}: {fmt_money(e['amount'])} {tag}{extra}")
        for p in deltas["promises"]:
            res = add_promise(c, branch, p["person"], p["task"], p["completed"])
            lines.append(f"🤝 {p['person']}: {p['task']} [{res}]")
        if deltas["quiet_risk"]:
            add_risk(c, branch, deltas["quiet_risk"], "note")
            lines.append(f"🚨 {deltas['quiet_risk']}")
        c.execute("INSERT INTO notes(ts,branch,raw,digest,extractor,deltas_json) VALUES(?,?,?,?,?,?)",
                  (now_str(), branch, raw, hashlib.sha1((branch + raw.strip()).encode()).hexdigest(), extractor,
                   json.dumps(deltas, ensure_ascii=False)))
    return lines


def process_note(text, branch):
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty"}
    digest = hashlib.sha1((branch + text).encode()).hexdigest()
    with db() as c:
        recent = c.execute("SELECT ts FROM notes WHERE digest=? ORDER BY id DESC LIMIT 1", (digest,)).fetchone()
        if recent and (now_dt() - parse_ts(recent["ts"])).total_seconds() < 60:
            return {"ok": False, "error": "duplicate"}
        known = [r["name"] for r in c.execute("SELECT name FROM items WHERE branch=?", (branch,))]
    deltas, extractor = extract_deltas(text, known)
    lines = apply_deltas(branch, deltas, text, extractor)
    return {"ok": True, "lines": lines, "extractor": extractor, "deltas": deltas}


_STATUS_CACHE = {"at": 0.0, "value": None}


def llm_status(max_age=30.0):
    """Cheap reachability probe for the UI badge (cached). Extraction falls back to rules when offline."""
    if _STATUS_CACHE["value"] is not None and time.time() - _STATUS_CACHE["at"] < max_age:
        return _STATUS_CACHE["value"]
    online = False
    try:
        req = urllib.request.Request(settings.llm_base_url.rstrip("/") + "/models",
                                     headers={"Authorization": f"Bearer {settings.llm_api_key}",
                                              "User-Agent": "LivingDoc/1.0"})
        with urllib.request.urlopen(req, timeout=2) as r:
            online = 200 <= r.status < 300
    except Exception:
        online = False
    value = {"online": online, "model": settings.llm_model, "base_url": settings.llm_base_url,
             "mode": "llm" if online else "rules"}
    _STATUS_CACHE.update(at=time.time(), value=value)
    return value
