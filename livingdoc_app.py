"""
LivingDoc: The Self-Updating Business Brain
===========================================
Single-file Streamlit + SQLite app for small businesses.

Run:   pip install streamlit && streamlit run livingdoc_app.py

* An LLM (OpenAI-compatible, default Ollama at http://localhost:11434/v1) ONLY extracts structured JSON deltas.
* Deterministic Python/SQLite code applies them; the Markdown page is re-rendered from database state.
* Scanner feed: drop .json/.jsonl/.csv files into ./scanner_inbox (polled every 10s).
* Multi-branch: stock movements sync hourly through a shared hub database.
* UI languages: English, Hindi, Gujarati.
"""
from __future__ import annotations

import io
import json
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# ============================================================================
#                    Festive inventory prediction engine
# ============================================================================
# ==== ENGINE START ====
SURGE_DAYS = 7              # days of surge before the festival
ARRIVAL_BUFFER_DAYS = 2     # stock must land 48h before the surge starts
SAFETY_FACTOR = 1.10        # 10% buffer on festival demand
HORIZON_DAYS = 400          # simulation horizon for stock-out search
LOOKAHEAD_DAYS = 120        # only festivals within this window are considered
INCLUDE_FESTIVAL_DAY = True # festival day itself is a surge day


def _to_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _surge_window(fd: date):
    start = fd - timedelta(days=SURGE_DAYS)
    end = fd if INCLUDE_FESTIVAL_DAY else fd - timedelta(days=1)
    return start, end


def _rate(day: date, base: float, start: date, end: date, mult: float) -> float:
    return base * mult if start <= day <= end else base


def _days_until_stockout(stock, base, today, start, end, mult) -> Optional[float]:
    """Fractional days from the start of `today` until stock hits zero."""
    if base <= 0:
        return None
    remaining = float(stock)
    if remaining <= 0:
        return 0.0
    for i in range(HORIZON_DAYS):
        r = _rate(today + timedelta(days=i), base, start, end, mult)
        if remaining <= r:
            return i + remaining / r
        remaining -= r
    return None


def _demand(base, first: date, last: date, start, end, mult) -> float:
    total, d = 0.0, first
    while d <= last:
        total += _rate(d, base, start, end, mult)
        d += timedelta(days=1)
    return total


def _floor1(x: float) -> float:
    return math.floor(x * 10 + 1e-9) / 10


def _num(x: float):
    x = float(x)
    return int(x) if x.is_integer() else round(x, 2)


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _urgency(must: Optional[date], today: date) -> str:
    if must is None:
        return "LOW"
    days = (must - today).days
    if days <= 2:
        return "CRITICAL"
    if days <= 5:
        return "HIGH"
    if days <= 10:
        return "MEDIUM"
    return "LOW"


def _analyse(stock, base, fest, lead, today, shelf_life) -> Dict[str, Any]:
    fd, mult, blackout = fest["date"], fest["mult"], fest["blackout"]
    start, end = _surge_window(fd)
    lead_adj = lead + blackout
    arrive_by = start - timedelta(days=ARRIVAL_BUFFER_DAYS)
    by_surge = arrive_by - timedelta(days=lead_adj)

    t_out = _days_until_stockout(stock, base, today, start, end, mult)
    stockout = today + timedelta(days=int(math.floor(t_out))) if t_out is not None else None
    by_stock = stockout - timedelta(days=lead_adj) if stockout else None

    demand_fest = _demand(base, today, fd, start, end, mult)
    post_cover = base * lead
    qty_raw = max(0, math.ceil((demand_fest + post_cover) * SAFETY_FACTOR - stock - 1e-9))
    needs = qty_raw > 0

    if needs:
        must = min([by_surge] + ([by_stock] if by_stock else []))
    else:
        must = by_stock

    qty, overstock, staged_every = qty_raw, False, None
    if shelf_life and needs:
        ref = max(must, today) if must else today
        arrival = ref + timedelta(days=lead_adj)
        age_at_fest = max(0, (fd - arrival).days)
        remaining = shelf_life - age_at_fest
        leftover = stock + qty_raw - demand_fest
        sellable = base * max(remaining, 0)
        if leftover > sellable + 1e-9:
            overstock = True
            need_fest = max(0, math.ceil(demand_fest - stock - 1e-9))
            cap = max(0, math.floor(sellable + demand_fest - stock + 1e-9))
            qty = max(need_fest, min(qty_raw, cap))
        if age_at_fest > shelf_life:
            staged_every = max(1, int(shelf_life) - 1)

    return dict(fest=fest, start=start, end=end, lead_adj=lead_adj, arrive_by=arrive_by,
                by_surge=by_surge, by_stock=by_stock, stockout=stockout, must=must,
                needs=needs, qty=qty, qty_raw=qty_raw, overstock=overstock,
                staged_every=staged_every)


def _record(item, stock, base, lead, today, shelf, a: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    days_normal = stock / base
    normal_reorder = today + timedelta(days=int(math.floor(days_normal))) - timedelta(days=lead)
    rec: Dict[str, Any] = {
        "item": item,
        "current_stock": _num(stock),
        "baseline_burn": _num(base),
    }
    if a is None:
        must = normal_reorder
        rec.update({
            "festive_burn": _num(base),
            "days_left_normal": _floor1(days_normal),
            "days_left_festive": _floor1(days_normal),
            "festival_name": None,
            "supplier_lead_time_adjusted": f"{lead} days ({lead} normal + 0 holiday lag)",
            "must_order_by": must.isoformat(),
            "normal_reorder_date": normal_reorder.isoformat(),
            "recommended_order_qty": None,
            "perishable": bool(shelf),
            "overstock_risk": False,
            "urgency": _urgency(must, today),
            "alert": (f"No upcoming festival. At normal pace stock lasts {_fmt(_floor1(days_normal))} days; "
                      f"reorder by {must.strftime('%A')}, {must.isoformat()}."),
        })
        return rec

    f, mult, blackout = a["fest"], a["fest"]["mult"], a["fest"]["blackout"]
    must = a["must"]
    days_fest = stock / (base * mult)
    parts: List[str] = []
    if mult > 1:
        parts.append(f"{f['name']} surge ({mult:g}x from {a['start'].strftime('%d %b')}) would exhaust stock in "
                     f"{_fmt(_floor1(days_fest))} days instead of {_fmt(_floor1(days_normal))}.")
    if blackout > 0:
        parts.append(f"Suppliers are shut or slow for {blackout} days around the festival, so lead time grows "
                     f"from {lead} to {a['lead_adj']} days.")
    if a["needs"]:
        wd = must.strftime("%A")
        if must < today:
            so = f" and expect shortages from {a['stockout'].strftime('%d %b')}" if a["stockout"] else ""
            parts.append(f"Your last safe order date ({wd} {must.strftime('%d %b')}) has already passed: "
                         f"order TODAY with express delivery{so}.")
        elif must == today:
            parts.append(f"Order TODAY ({wd}): this is your last safe order date.")
        else:
            parts.append(f"Your last chance to order is {wd}, {must.strftime('%d %b %Y')}.")
        parts.append(f"Suggested order quantity: {a['qty']:g}.")
    else:
        parts.append("Current stock covers this festival; no festival order needed.")
    if a["overstock"]:
        parts.append(f"Perishable overstock guard: order reduced from {a['qty_raw']:g} to {a['qty']:g} so "
                     f"leftover stock does not spoil after the festival.")
    if a["staged_every"]:
        parts.append(f"Shelf life ({shelf} days) is shorter than the gap between delivery and the festival: "
                     f"take staged deliveries about every {a['staged_every']} days instead of one big order.")

    rec.update({
        "festive_burn": _num(base * mult),
        "days_left_normal": _floor1(days_normal),
        "days_left_festive": _floor1(days_fest),
        "festival_name": f["name"],
        "festival_date": f["date"].isoformat(),
        "surge_window": f"{a['start'].isoformat()} to {a['end'].isoformat()}",
        "supplier_lead_time_adjusted": f"{a['lead_adj']} days ({lead} normal + {blackout} holiday lag)",
        "must_order_by": must.isoformat() if must else None,
        "must_order_by_weekday": must.strftime("%A") if must else None,
        "normal_reorder_date": normal_reorder.isoformat(),
        "stock_must_arrive_by": a["arrive_by"].isoformat(),
        "projected_stockout_date": a["stockout"].isoformat() if a["stockout"] else None,
        "recommended_order_qty": a["qty"],
        "perishable": bool(shelf),
        "overstock_risk": a["overstock"],
        "staged_delivery_every_days": a["staged_every"],
        "urgency": _urgency(must, today),
        "alert": " ".join(parts),
    })
    return rec


def predict_inventory(stock: Dict[str, float],
                      baseline_burn: Dict[str, float],
                      festivals: List[Dict[str, Any]],
                      lead_time_days: int = 3,
                      today: Any = None,
                      perishables: Optional[Dict[str, int]] = None,
                      lookahead_days: int = LOOKAHEAD_DAYS) -> List[Dict[str, Any]]:
    """Return one prediction record per item (most urgent upcoming festival wins).

    festivals: [{"name","date","surge_multiplier","supplier_blackout_days"}]
    perishables: {item: shelf_life_days}
    """
    today_d = _to_date(today) if today else date.today()
    perishables = perishables or {}
    if lead_time_days < 0:
        raise ValueError("lead_time_days must be >= 0")

    upcoming = []
    for f in festivals or []:
        fd = _to_date(f["date"])
        mult = float(f.get("surge_multiplier", 1.0))
        blackout = int(f.get("supplier_blackout_days", 0))
        if mult <= 0:
            raise ValueError(f"surge_multiplier must be > 0 ({f.get('name')})")
        if blackout < 0:
            raise ValueError(f"supplier_blackout_days must be >= 0 ({f.get('name')})")
        if today_d <= fd <= today_d + timedelta(days=lookahead_days):
            upcoming.append({"name": f["name"], "date": fd, "mult": mult, "blackout": blackout})

    results: List[Dict[str, Any]] = []
    for item, qty in stock.items():
        qty = max(0.0, float(qty))
        base = float(baseline_burn.get(item, 0) or 0)
        shelf = perishables.get(item)
        if base <= 0:
            results.append({"item": item, "current_stock": _num(qty), "baseline_burn": 0,
                            "urgency": "NO_DATA", "festival_name": None, "must_order_by": None,
                            "alert": "No sales history yet, so no prediction is possible."})
            continue
        analyses = [_analyse(qty, base, f, lead_time_days, today_d, shelf) for f in upcoming]
        if analyses:
            best = min(analyses, key=lambda a: (not a["needs"], a["must"] or date.max, a["fest"]["date"]))
        else:
            best = None
        results.append(_record(item, qty, base, lead_time_days, today_d, shelf, best))
    return results
# ==== ENGINE END ====



# ============================================================================
#                         LivingDoc application layer
# ============================================================================
import csv
import difflib
import hashlib
import os
import random
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

try:
    import streamlit as st
except ImportError:  # core logic stays importable (tests) without Streamlit
    st = None

# ----------------------------------------------------------------- config ---
DB_PATH = os.environ.get("LIVINGDOC_DB", "livingdoc.db")
HUB_PATH = os.environ.get("LIVINGDOC_HUB", "livingdoc_hub.db")        # shared by all branches
SCANNER_INBOX = os.environ.get("LIVINGDOC_SCANNER_INBOX", "scanner_inbox")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")   # Ollama; or https://api.openai.com/v1
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.1")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "45"))
SYNC_INTERVAL_SECONDS = int(os.environ.get("LIVINGDOC_SYNC_SECONDS", "3600"))   # hourly branch sync
SUPPLIER_LEAD_DAYS = int(os.environ.get("LIVINGDOC_LEAD_DAYS", "3"))
DEFAULT_BRANCH = "Main Store"
CURRENCY = "₹"
_LLM_DOWN_UNTIL = 0.0


def now_dt() -> datetime:
    return datetime.now().replace(microsecond=0)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(s: str) -> datetime:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")


# --------------------------------------------------------------- database ---
SCHEMA = """
CREATE TABLE IF NOT EXISTS branches(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS items(
    branch TEXT NOT NULL, name TEXT NOT NULL, sku TEXT, unit TEXT NOT NULL DEFAULT 'pcs',
    qty REAL NOT NULL DEFAULT 0, min_stock REAL NOT NULL DEFAULT 0,
    baseline_burn REAL NOT NULL DEFAULT 0, shelf_life_days INTEGER,
    needs_review INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(branch, name));
CREATE TABLE IF NOT EXISTS movements(
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, branch TEXT NOT NULL, item TEXT NOT NULL,
    change REAL NOT NULL, source TEXT NOT NULL, note TEXT, synced INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_mov_item ON movements(branch, item, ts);
CREATE INDEX IF NOT EXISTS idx_mov_sync ON movements(synced);
CREATE TABLE IF NOT EXISTS cash_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('collected','owed')), entity TEXT NOT NULL,
    amount REAL NOT NULL, settled REAL NOT NULL DEFAULT 0, descr TEXT);
CREATE INDEX IF NOT EXISTS idx_cash_branch ON cash_events(branch, type, ts);
CREATE TABLE IF NOT EXISTS promises(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    person TEXT NOT NULL, task TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, done_ts TEXT);
CREATE TABLE IF NOT EXISTS risks(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    text TEXT NOT NULL, source TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    raw TEXT NOT NULL, digest TEXT NOT NULL, extractor TEXT, deltas_json TEXT);
CREATE TABLE IF NOT EXISTS festivals(
    name TEXT NOT NULL, date TEXT NOT NULL, surge_multiplier REAL NOT NULL,
    supplier_blackout_days INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(name, date));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

HUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS hub_movements(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, ts TEXT NOT NULL,
    branch TEXT NOT NULL, item TEXT NOT NULL, change REAL NOT NULL, source TEXT, note TEXT);
"""


@contextmanager
def db(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def meta_get(c, key, default=None):
    r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def meta_set(c, key, value):
    c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, str(value)))


def ensure_branch(c, branch):
    c.execute("INSERT OR IGNORE INTO branches(name) VALUES(?)", (branch,))


def add_risk(c, branch, text, source="auto"):
    """Store a risk once (an identical unresolved risk is not duplicated)."""
    text = text.strip()
    if not text:
        return
    if c.execute("SELECT 1 FROM risks WHERE branch=? AND text=? AND resolved=0", (branch, text)).fetchone():
        return
    c.execute("INSERT INTO risks(ts,branch,text,source) VALUES(?,?,?,?)", (now_str(), branch, text, source))


# ------------------------------------------------------------ name helpers ---
STOP_TOKENS = {"of", "the", "a", "an", "some", "few", "more"}


def stem(w: str) -> str:
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and re.search(r"(s|x|z|ch|sh)es$", w):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def norm_tokens(s: str):
    toks = re.findall(r"[^\W_]+", (s or "").lower(), flags=re.UNICODE)
    return [stem(t) for t in toks if t not in STOP_TOKENS]


def pretty_name(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw.strip())
    return raw.title() if raw.isascii() else raw


def same_entity(a: str, b: str) -> bool:
    ta, tb = set(norm_tokens(a)), set(norm_tokens(b))
    return bool(ta and tb and (ta <= tb or tb <= ta))


def md_esc(s) -> str:
    return re.sub(r"\s+", " ", str(s)).replace("|", "\\|").replace("`", "'").replace("<", "&lt;").strip()


def fmt_qty(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def fmt_money(x: float) -> str:
    return f"{CURRENCY}{x:,.0f}" if abs(x - round(x)) < 0.005 else f"{CURRENCY}{x:,.2f}"


# ---------------------------------------------------- inventory primitives ---
def resolve_item(c, branch, raw, sku=None, create=True):
    """Map a messy name / SKU to an existing item; create a flagged placeholder if nothing fits."""
    raw = (raw or "").strip()
    sku = (sku or "").strip() or None
    if sku:
        r = c.execute("SELECT name FROM items WHERE branch=? AND lower(sku)=lower(?)", (branch, sku)).fetchone()
        if r:
            return r["name"], False
    names = [r["name"] for r in c.execute("SELECT name FROM items WHERE branch=?", (branch,))]
    if raw:
        q = norm_tokens(raw)
        for n in names:
            if norm_tokens(n) == q:
                return n, False
        qj = " ".join(q)
        cands = [n for n in names if q and set(q) <= set(norm_tokens(n))]
        if cands:
            return max(cands, key=lambda n: difflib.SequenceMatcher(None, qj, " ".join(norm_tokens(n))).ratio()), False
        scored = [(difflib.SequenceMatcher(None, qj, " ".join(norm_tokens(n))).ratio(), n) for n in names]
        if scored:
            best = max(scored)
            if best[0] >= 0.82:
                return best[1], False
    if not create:
        return None, False
    name = pretty_name(raw) if raw else f"Unknown SKU {sku}"
    c.execute("INSERT OR IGNORE INTO items(branch,name,sku,unit,needs_review) VALUES(?,?,?,?,1)",
              (branch, name, sku, "pcs"))
    return name, True


def apply_movement(c, branch, item, change, source, note="", ts=None, mov_id=None):
    """Deterministically add/subtract stock. Never lets stock go below zero; shortfalls are reported."""
    change = round(float(change), 6)
    if mov_id and c.execute("SELECT 1 FROM movements WHERE id=?", (mov_id,)).fetchone():
        return {"applied": 0.0, "short": 0.0, "duplicate": True, "qty": None}
    row = c.execute("SELECT qty FROM items WHERE branch=? AND name=?", (branch, item)).fetchone()
    if row is None:
        raise KeyError(f"unknown item {item!r}")
    cur = row["qty"]
    new, short = round(cur + change, 6), 0.0
    if new < 0:
        short, change, new = round(-new, 6), round(-cur, 6), 0.0
    if abs(change) > 1e-9:
        c.execute("INSERT INTO movements(id,ts,branch,item,change,source,note,synced) VALUES(?,?,?,?,?,?,?,0)",
                  (mov_id or uuid.uuid4().hex, ts or now_str(), branch, item, change, source, (note or "")[:200]))
        c.execute("UPDATE items SET qty=? WHERE branch=? AND name=?", (new, branch, item))
    return {"applied": change, "short": short, "duplicate": False, "qty": new}


def burn_info(c, branch, item, seeded=0.0, now=None):
    """Effective daily burn: observed from sales/usage history (30d window); seeded value while history is short."""
    now = now or now_dt()
    since = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    out = c.execute("SELECT COALESCE(SUM(-change),0) s FROM movements WHERE branch=? AND item=? AND change<0 AND ts>=?",
                    (branch, item, since)).fetchone()["s"]
    first = c.execute("SELECT MIN(ts) m FROM movements WHERE branch=? AND item=?", (branch, item)).fetchone()["m"]
    history = (now - parse_ts(first)).days if first else 0
    observed = out / min(30, max(1, history))
    effective = observed if history >= 7 else (seeded if seeded > 0 else observed)
    return {"burn": round(effective, 4), "out30": out, "history_days": history}


def audit_stock(c):
    """Items whose stored qty disagrees with the sum of their movement log."""
    bad = []
    for r in c.execute("""SELECT i.branch, i.name, i.qty, COALESCE(SUM(m.change),0) s
                          FROM items i LEFT JOIN movements m ON m.branch=i.branch AND m.item=i.name
                          GROUP BY i.branch, i.name"""):
        if r["s"] != 0 or r["qty"] != 0:
            if abs(r["qty"] - r["s"]) > 1e-4:
                bad.append((r["branch"], r["name"], r["qty"], r["s"]))
    return bad


# ------------------------------------------------------------- cash/promises --
def add_cash_event(c, branch, ctype, entity, amount, desc="", ts=None):
    """collected = money in; owed = customer owes us. Collected money settles that entity's debt first (FIFO)."""
    ts = ts or now_str()
    entity = (entity or "").strip() or "Walk-in"
    amount = round(float(amount), 2)
    settled_total = 0.0
    cur = c.execute("INSERT INTO cash_events(ts,branch,type,entity,amount,settled,descr) VALUES(?,?,?,?,?,0,?)",
                    (ts, branch, ctype, entity, amount, (desc or "")[:200]))
    if ctype == "collected":
        remaining = amount
        rows = c.execute("""SELECT id, entity, amount, settled FROM cash_events
                            WHERE branch=? AND type='owed' AND amount-settled>0.004 ORDER BY ts, id""", (branch,)).fetchall()
        for r in rows:
            if remaining <= 0.004:
                break
            if not same_entity(r["entity"], entity):
                continue
            use = round(min(remaining, r["amount"] - r["settled"]), 2)
            c.execute("UPDATE cash_events SET settled=? WHERE id=?", (round(r["settled"] + use, 2), r["id"]))
            remaining = round(remaining - use, 2)
            settled_total += use
    return cur.lastrowid, settled_total


def add_promise(c, branch, person, task, completed=False):
    person, task = (person or "").strip() or "Me", task.strip()
    rows = c.execute("SELECT id, person, task, done FROM promises WHERE branch=? AND done=0", (branch,)).fetchall()
    best, best_r = None, 0.0
    for r in rows:
        ratio = difflib.SequenceMatcher(None, " ".join(norm_tokens(task)), " ".join(norm_tokens(r["task"]))).ratio()
        if (same_entity(person, r["person"]) or person == "Me" or r["person"] == "Me") and ratio > best_r:
            best, best_r = r, ratio
    if completed:
        if best is not None and best_r >= 0.6:
            c.execute("UPDATE promises SET done=1, done_ts=? WHERE id=?", (now_str(), best["id"]))
            return "completed"
        c.execute("INSERT INTO promises(ts,branch,person,task,done,done_ts) VALUES(?,?,?,?,1,?)",
                  (now_str(), branch, person, task, now_str()))
        return "logged-done"
    if best is not None and best_r >= 0.85:
        return "duplicate"
    c.execute("INSERT INTO promises(ts,branch,person,task) VALUES(?,?,?,?)", (now_str(), branch, person, task))
    return "added"


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
    body = {"model": LLM_MODEL, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        LLM_BASE_URL.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LLM_API_KEY}"})
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
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


# ------------------------------------------------------------ scanner inbox ---
DIRECTIONS = {"in": 1, "inward": 1, "receive": 1, "received": 1, "restock": 1, "purchase": 1, "+": 1, "1": 1,
              "out": -1, "outward": -1, "sale": -1, "sold": -1, "issue": -1, "dispatch": -1, "-": -1, "-1": -1}


def _read_scan_file(f: Path):
    suffix = f.suffix.lower()
    text = f.read_text(encoding="utf-8-sig")
    if suffix == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    if suffix == ".jsonl":
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    obj = json.loads(text)
    if isinstance(obj, dict) and isinstance(obj.get("events"), list):
        obj = obj["events"]
    return obj if isinstance(obj, list) else [obj]


def _apply_scan_event(c, ev, default_branch, fname):
    if not isinstance(ev, dict):
        return "skipped", "event is not an object"
    branch = str(ev.get("branch") or default_branch).strip() or default_branch
    ensure_branch(c, branch)
    sku = str(ev.get("sku") or ev.get("barcode") or "").strip()
    name = str(ev.get("item") or ev.get("name") or "").strip()
    if not sku and not name:
        return "skipped", "no sku or item name"
    qty = _to_float(ev.get("qty", 1) if ev.get("qty") not in (None, "") else 1)
    if qty is None or qty <= 0:
        return "skipped", "invalid quantity"
    sign = DIRECTIONS.get(str(ev.get("direction", "")).strip().lower())
    if sign is None:
        return "skipped", "direction must be in/out"
    eid = str(ev.get("event_id") or ev.get("id") or "").strip()
    mov_id = f"scan-{branch}-{eid}" if eid else None
    item, created = resolve_item(c, branch, name, sku or None)
    if sku:  # learn barcode -> item mapping the first time a known item is scanned
        cur = c.execute("SELECT sku FROM items WHERE branch=? AND name=?", (branch, item)).fetchone()
        taken = c.execute("SELECT 1 FROM items WHERE branch=? AND lower(sku)=lower(?)", (branch, sku)).fetchone()
        if cur and not cur["sku"] and not taken:
            c.execute("UPDATE items SET sku=? WHERE branch=? AND name=?", (sku, branch, item))
    ts = None
    if ev.get("ts"):
        try:
            ts = parse_ts(str(ev["ts"]).replace("T", " ")).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts = None
    r = apply_movement(c, branch, item, sign * qty, "scanner", fname, ts=ts, mov_id=mov_id)
    if r["duplicate"]:
        return "duplicate", ""
    if r["short"] > 0:
        add_risk(c, branch, f"Scanner: {fmt_qty(qty)} x {item} went out but only {fmt_qty(qty - r['short'])} were on record - "
                            f"an earlier delivery scan is probably missing.", "scanner")
    return "applied", ""


def process_scanner_inbox(default_branch, min_age=1.0):
    """Ingest files dropped by the (already working) scanner: .json / .jsonl / .csv. Idempotent via event_id."""
    inbox = Path(SCANNER_INBOX)
    done, bad = inbox / "processed", inbox / "failed"
    for d in (inbox, done, bad):
        d.mkdir(parents=True, exist_ok=True)
    stats = {"files": 0, "applied": 0, "duplicate": 0, "skipped": 0, "failed_files": 0}
    for f in sorted(inbox.iterdir()):
        if (not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in (".json", ".jsonl", ".csv")
                or time.time() - f.stat().st_mtime < min_age):
            continue
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        try:
            events = _read_scan_file(f)
            with db() as c:
                for ev in events:
                    res, why = _apply_scan_event(c, ev, default_branch, f.name)
                    stats[res] += 1
                    if res == "skipped":
                        add_risk(c, default_branch, f"Scanner event skipped ({why}): {json.dumps(ev, ensure_ascii=False)[:140]}", "scanner")
        except Exception as e:
            stats["failed_files"] += 1
            shutil.move(str(f), str(bad / f"{stamp}_{f.name}"))
            (bad / f"{stamp}_{f.name}.error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
            with db() as c:
                add_risk(c, default_branch, f"Scanner file {f.name} could not be read ({type(e).__name__}); moved to failed/.", "scanner")
            continue
        stats["files"] += 1
        shutil.move(str(f), str(done / f"{stamp}_{f.name}"))
    return stats


# ---------------------------------------------------------- multi-branch sync ---
def sync_with_hub():
    """Push unsynced stock movements to the shared hub and pull other branches' movements (idempotent by id)."""
    with db() as c:
        rows = c.execute("SELECT * FROM movements WHERE synced=0 ORDER BY ts").fetchall()
        last_seq = int(meta_get(c, "hub_seq", "0"))
    pushed = 0
    with db(HUB_PATH) as h:
        h.executescript(HUB_SCHEMA)
        for r in rows:
            cur = h.execute("INSERT OR IGNORE INTO hub_movements(id,ts,branch,item,change,source,note) VALUES(?,?,?,?,?,?,?)",
                            (r["id"], r["ts"], r["branch"], r["item"], r["change"], r["source"], r["note"]))
            pushed += cur.rowcount
        new = h.execute("SELECT * FROM hub_movements WHERE seq>? ORDER BY seq", (last_seq,)).fetchall()
    pulled, max_seq = 0, last_seq
    with db() as c:
        for r in rows:
            c.execute("UPDATE movements SET synced=1 WHERE id=?", (r["id"],))
        for r in new:
            max_seq = max(max_seq, r["seq"])
            if c.execute("SELECT 1 FROM movements WHERE id=?", (r["id"],)).fetchone():
                continue
            ensure_branch(c, r["branch"])
            c.execute("INSERT OR IGNORE INTO items(branch,name,needs_review) VALUES(?,?,1)", (r["branch"], r["item"]))
            c.execute("UPDATE items SET qty=ROUND(qty+?,6) WHERE branch=? AND name=?", (r["change"], r["branch"], r["item"]))
            c.execute("INSERT INTO movements(id,ts,branch,item,change,source,note,synced) VALUES(?,?,?,?,?,?,?,1)",
                      (r["id"], r["ts"], r["branch"], r["item"], r["change"], r["source"], r["note"]))
            pulled += 1
        meta_set(c, "hub_seq", max_seq)
        meta_set(c, "last_sync", now_str())
    return {"pushed": pushed, "pulled": pulled}


def sync_if_due(force=False):
    with db() as c:
        last = meta_get(c, "last_sync")
    if force or not last or (now_dt() - parse_ts(last)).total_seconds() >= SYNC_INTERVAL_SECONDS:
        try:
            return sync_with_hub()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    return None


# ------------------------------------------------------------------- i18n ---
T = {
    "en": {
        "title": "LivingDoc: The Self-Updating Business Brain", "notes_header": "🎙️ Talk or type your day",
        "notes_hint": "Ramble freely: sold 4 coffees, used 2 milks, Dave paid ₹500 cash, remind me to order beans...",
        "process_btn": "Update my business page", "inventory": "📦 Current Inventory", "cash": "💰 Cash & Invoices",
        "promises": "🤝 Handshakes & Promises", "risks": "🚨 Quiet Breakage Warnings",
        "forecast": "🔮 Early Shortage Predictions", "item": "Item", "qty": "Qty", "unit": "Unit", "min": "Min",
        "days_left": "Days left", "status": "Status", "low": "⚠️ LOW STOCK", "ok": "OK", "out": "⛔ OUT",
        "total_collected": "Total collected", "collected_today": "Collected today", "pending": "Pending debts",
        "no_pending": "Nobody owes you money right now.", "no_promises": "No open promises.", "no_risks": "No warnings. All quiet.",
        "no_forecast": "No item needs ordering soon.", "updated": "Updated", "since": "since",
        "festival": "Festival", "order_by": "Order by", "order_qty": "Suggested qty", "urgency": "Urgency", "regular": "Regular",
        "CRITICAL": "🔴 CRITICAL", "HIGH": "🟠 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🟢 LOW",
        "risk_out": "{item} is out of stock.",
        "risk_runout": "{item} will run out in about {days} days, which is shorter than the supplier lead time ({lead} days).",
        "risk_overdue": "{entity} has owed {amount} for {days} days.",
        "risk_conc": "{pct}% of all unpaid money is owed by {entity} alone.",
        "risk_promise": "Promise to {person} \"{task}\" has been open for {days} days.",
        "risk_dead": "{qty} {unit} of {item} is sitting on the shelf with no sales in 30 days.",
        "risk_review": "{item} was added automatically: please check its name, unit and minimum stock.",
        "risk_scan_silent": "The scanner has sent nothing for {hours} hours; stock counts may be drifting.",
        "risk_sync": "Branch sync is behind ({n} updates waiting to upload).",
        "risk_sales_drop": "Money collected this week is {pct}% lower than last week.",
        "risk_noted": "From your notes: {text}",
        "scanner": "📷 Scanner feed", "sync_now": "Sync branches now", "branch": "Branch", "language": "Language",
    },
    "hi": {
        "title": "लिविंगडॉक: खुद अपडेट होने वाला बिज़नेस ब्रेन", "notes_header": "🎙️ अपना दिन बोलें या लिखें",
        "notes_hint": "जैसे मन हो लिखें: 4 कॉफ़ी बिकी, 2 दूध लगा, डेव ने ₹500 कैश दिए, बीन्स मँगाने की याद दिलाना...",
        "process_btn": "मेरा बिज़नेस पेज अपडेट करें", "inventory": "📦 मौजूदा स्टॉक", "cash": "💰 नकद और बकाया",
        "promises": "🤝 वादे और ज़िम्मेदारियाँ", "risks": "🚨 छुपे जोखिम की चेतावनी",
        "forecast": "🔮 कमी की पहले से चेतावनी", "item": "वस्तु", "qty": "मात्रा", "unit": "इकाई", "min": "न्यूनतम",
        "days_left": "बचे दिन", "status": "स्थिति", "low": "⚠️ कम स्टॉक", "ok": "ठीक", "out": "⛔ खत्म",
        "total_collected": "कुल प्राप्त रकम", "collected_today": "आज प्राप्त", "pending": "बकाया रकम",
        "no_pending": "अभी किसी पर बकाया नहीं है।", "no_promises": "कोई खुला वादा नहीं।", "no_risks": "कोई चेतावनी नहीं। सब शांत है।",
        "no_forecast": "जल्द ऑर्डर करने की ज़रूरत किसी वस्तु को नहीं।", "updated": "अपडेट", "since": "से",
        "festival": "त्योहार", "order_by": "ऑर्डर की आख़िरी तारीख़", "order_qty": "सुझाई मात्रा", "urgency": "प्राथमिकता", "regular": "सामान्य",
        "CRITICAL": "🔴 अत्यंत ज़रूरी", "HIGH": "🟠 ज़्यादा", "MEDIUM": "🟡 मध्यम", "LOW": "🟢 कम",
        "risk_out": "{item} का स्टॉक खत्म हो चुका है।",
        "risk_runout": "{item} लगभग {days} दिन में खत्म हो जाएगा, जो सप्लायर के लीड टाइम ({lead} दिन) से कम है।",
        "risk_overdue": "{entity} पर {amount} बकाया है, {days} दिन से।",
        "risk_conc": "कुल बकाया का {pct}% सिर्फ़ {entity} पर है।",
        "risk_promise": "{person} से किया वादा \"{task}\" {days} दिन से खुला है।",
        "risk_dead": "{item} का {qty} {unit} स्टॉक पड़ा है, पर पिछले 30 दिनों में बिक्री नहीं हुई।",
        "risk_review": "{item} अपने-आप जुड़ गया है, कृपया नाम, इकाई और न्यूनतम स्टॉक जाँच लें।",
        "risk_scan_silent": "स्कैनर से {hours} घंटे से कोई डेटा नहीं आया; स्टॉक की गिनती गलत हो सकती है।",
        "risk_sync": "ब्रांच सिंक पिछड़ गया है ({n} अपडेट अपलोड बाकी)।",
        "risk_sales_drop": "इस हफ़्ते की वसूली पिछले हफ़्ते से {pct}% कम है।",
        "risk_noted": "आपके नोट से: {text}",
        "scanner": "📷 स्कैनर फ़ीड", "sync_now": "ब्रांच अभी सिंक करें", "branch": "ब्रांच", "language": "भाषा",
    },
    "gu": {
        "title": "લિવિંગડોક: પોતાની જાતે અપડેટ થતું બિઝનેસ બ્રેઇન", "notes_header": "🎙️ તમારો દિવસ બોલો કે લખો",
        "notes_hint": "જેમ મન થાય તેમ લખો: 4 કોફી વેચાઈ, 2 દૂધ વપરાયું, ડેવે ₹500 રોકડા આપ્યા, બીન્સ મંગાવવાનું યાદ અપાવજો...",
        "process_btn": "મારું બિઝનેસ પેજ અપડેટ કરો", "inventory": "📦 હાલનો સ્ટોક", "cash": "💰 રોકડ અને બાકી લેણાં",
        "promises": "🤝 વચનો અને જવાબદારીઓ", "risks": "🚨 છુપા જોખમની ચેતવણી",
        "forecast": "🔮 અછતની વહેલી ચેતવણી", "item": "વસ્તુ", "qty": "જથ્થો", "unit": "એકમ", "min": "લઘુતમ",
        "days_left": "બાકી દિવસ", "status": "સ્થિતિ", "low": "⚠️ ઓછો સ્ટોક", "ok": "બરાબર", "out": "⛔ ખતમ",
        "total_collected": "કુલ મળેલી રકમ", "collected_today": "આજે મળેલ", "pending": "બાકી રકમ",
        "no_pending": "હાલમાં કોઈના પાસે બાકી નથી.", "no_promises": "કોઈ ખુલ્લું વચન નથી.", "no_risks": "કોઈ ચેતવણી નથી. બધું શાંત છે.",
        "no_forecast": "જલદી ઓર્ડર કરવાની જરૂર કોઈ વસ્તુને નથી.", "updated": "અપડેટ", "since": "થી",
        "festival": "તહેવાર", "order_by": "ઓર્ડરની છેલ્લી તારીખ", "order_qty": "સૂચવેલ જથ્થો", "urgency": "અગ્રતા", "regular": "સામાન્ય",
        "CRITICAL": "🔴 અત્યંત જરૂરી", "HIGH": "🟠 વધુ", "MEDIUM": "🟡 મધ્યમ", "LOW": "🟢 ઓછી",
        "risk_out": "{item}નો સ્ટોક ખતમ થઈ ગયો છે.",
        "risk_runout": "{item} લગભગ {days} દિવસમાં ખતમ થઈ જશે, જે સપ્લાયરના લીડ ટાઇમ ({lead} દિવસ) કરતાં ઓછું છે.",
        "risk_overdue": "{entity} પાસે {amount} બાકી છે, {days} દિવસથી.",
        "risk_conc": "કુલ બાકી રકમના {pct}% માત્ર {entity} પાસે છે.",
        "risk_promise": "{person} સાથેનું વચન \"{task}\" {days} દિવસથી બાકી છે.",
        "risk_dead": "{item}નો {qty} {unit} સ્ટોક પડ્યો છે, પણ છેલ્લા 30 દિવસમાં વેચાણ થયું નથી.",
        "risk_review": "{item} આપોઆપ ઉમેરાયો છે, કૃપા કરીને નામ, એકમ અને લઘુતમ સ્ટોક તપાસો.",
        "risk_scan_silent": "સ્કેનર તરફથી {hours} કલાકથી કોઈ ડેટા આવ્યો નથી; સ્ટોકની ગણતરી ખોટી પડી શકે.",
        "risk_sync": "બ્રાન્ચ સિંક પાછળ છે ({n} અપડેટ અપલોડ બાકી).",
        "risk_sales_drop": "આ અઠવાડિયાની વસૂલાત ગયા અઠવાડિયા કરતાં {pct}% ઓછી છે.",
        "risk_noted": "તમારી નોંધમાંથી: {text}",
        "scanner": "📷 સ્કેનર ફીડ", "sync_now": "બ્રાન્ચ હમણાં સિંક કરો", "branch": "બ્રાન્ચ", "language": "ભાષા",
    },
}


def tr(lang, key, **kw):
    s = T.get(lang, T["en"]).get(key) or T["en"].get(key, key)
    return s.format(**kw) if kw else s


# -------------------------------------------------------------- doc render ---
def gather_burns(c, branch):
    burns = {}
    for it in c.execute("SELECT name, baseline_burn FROM items WHERE branch=?", (branch,)).fetchall():
        burns[it["name"]] = burn_info(c, branch, it["name"], it["baseline_burn"])
    return burns


def forecast_rows(c, branch, burns, today=None):
    items = c.execute("SELECT name, qty, shelf_life_days FROM items WHERE branch=?", (branch,)).fetchall()
    fest = [{"name": f["name"], "date": f["date"], "surge_multiplier": f["surge_multiplier"],
             "supplier_blackout_days": f["supplier_blackout_days"]} for f in c.execute("SELECT * FROM festivals")]
    lead = int(meta_get(c, "lead_days", SUPPLIER_LEAD_DAYS))
    res = predict_inventory({i["name"]: i["qty"] for i in items}, {n: b["burn"] for n, b in burns.items()}, fest,
                            lead, today or date.today(), {i["name"]: i["shelf_life_days"] for i in items if i["shelf_life_days"]})
    return [r for r in res if r["urgency"] in ("CRITICAL", "HIGH", "MEDIUM")], lead


def detect_risks(c, branch, lang, burns, lead):
    out, now = [], now_dt()
    for it in c.execute("SELECT * FROM items WHERE branch=? ORDER BY name", (branch,)).fetchall():
        b = burns[it["name"]]
        if it["qty"] <= 0:
            out.append(tr(lang, "risk_out", item=it["name"]))
        elif b["burn"] > 0 and it["qty"] / b["burn"] < lead:
            out.append(tr(lang, "risk_runout", item=it["name"], days=f"{it['qty'] / b['burn']:.1f}", lead=lead))
        if it["needs_review"]:
            out.append(tr(lang, "risk_review", item=it["name"]))
        if it["qty"] > 0 and b["history_days"] >= 14 and b["out30"] <= 0:
            out.append(tr(lang, "risk_dead", item=it["name"], qty=fmt_qty(it["qty"]), unit=it["unit"]))
    debts = c.execute("SELECT entity, amount-settled AS bal, ts FROM cash_events WHERE branch=? AND type='owed' AND amount-settled>0.004", (branch,)).fetchall()
    by_entity = {}
    for d in debts:
        age = (now - parse_ts(d["ts"])).days
        if age >= 7:
            out.append(tr(lang, "risk_overdue", entity=d["entity"], amount=fmt_money(d["bal"]), days=age))
        by_entity[d["entity"]] = by_entity.get(d["entity"], 0) + d["bal"]
    total = sum(by_entity.values())
    if total >= 1000 and by_entity:
        who, amt = max(by_entity.items(), key=lambda kv: kv[1])
        if amt / total >= 0.6 and len(by_entity) > 1:
            out.append(tr(lang, "risk_conc", pct=round(100 * amt / total), entity=who))
    for p in c.execute("SELECT person, task, ts FROM promises WHERE branch=? AND done=0", (branch,)).fetchall():
        age = (now - parse_ts(p["ts"])).days
        if age >= 3:
            out.append(tr(lang, "risk_promise", person=p["person"], task=p["task"], days=age))
    last_scan = c.execute("SELECT MAX(ts) m FROM movements WHERE source='scanner' AND branch=?", (branch,)).fetchone()["m"]
    if last_scan and (now - parse_ts(last_scan)).total_seconds() > 24 * 3600:
        out.append(tr(lang, "risk_scan_silent", hours=int((now - parse_ts(last_scan)).total_seconds() // 3600)))
    waiting = c.execute("SELECT COUNT(*) n FROM movements WHERE synced=0").fetchone()["n"]
    last_sync = meta_get(c, "last_sync")
    if waiting and last_sync and (now - parse_ts(last_sync)).total_seconds() > 3 * 3600:
        out.append(tr(lang, "risk_sync", n=waiting))
    w1 = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected' AND ts>=?",
                   (branch, (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"))).fetchone()["s"]
    w0 = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected' AND ts>=? AND ts<?",
                   (branch, (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S"),
                    (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"))).fetchone()["s"]
    if w0 > 0 and w1 < 0.7 * w0:
        out.append(tr(lang, "risk_sales_drop", pct=round(100 * (1 - w1 / w0))))
    for r in c.execute("SELECT text FROM risks WHERE branch=? AND resolved=0 ORDER BY id DESC LIMIT 10", (branch,)).fetchall():
        out.append(tr(lang, "risk_noted", text=r["text"]))
    return out


def render_doc(branch, lang="en") -> str:
    """Rebuild the whole Markdown page from SQLite state (no AI involved)."""
    with db() as c:
        burns = gather_burns(c, branch)
        items = c.execute("SELECT * FROM items WHERE branch=? ORDER BY name", (branch,)).fetchall()
        fc, lead = forecast_rows(c, branch, burns)
        risks = detect_risks(c, branch, lang, burns, lead)
        total_col = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected'", (branch,)).fetchone()["s"]
        today_col = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected' AND ts>=?",
                              (branch, date.today().strftime("%Y-%m-%d"))).fetchone()["s"]
        debts = c.execute("""SELECT entity, SUM(amount-settled) bal, MIN(ts) first FROM cash_events
                             WHERE branch=? AND type='owed' AND amount-settled>0.004 GROUP BY lower(entity) ORDER BY bal DESC""", (branch,)).fetchall()
        proms = c.execute("SELECT person, task, done FROM promises WHERE branch=? ORDER BY done, id DESC LIMIT 25", (branch,)).fetchall()
    L = lambda k, **kw: tr(lang, k, **kw)
    md = [f"# 📄 {L('title')}", f"*{md_esc(branch)} · {L('updated')}: {now_dt().strftime('%d %b %Y, %H:%M')}*", ""]
    md += [f"## {L('inventory')}", "",
           f"| {L('item')} | {L('qty')} | {L('unit')} | {L('min')} | {L('days_left')} | {L('status')} |", "|---|---:|---|---:|---:|---|"]
    for it in items:
        b = burns[it["name"]]["burn"]
        dl = f"{it['qty'] / b:.1f}" if b > 0 else "-"
        status = L("out") if it["qty"] <= 0 else (L("low") if it["qty"] <= it["min_stock"] else L("ok"))
        md.append(f"| {md_esc(it['name'])} | {fmt_qty(it['qty'])} | {md_esc(it['unit'])} | {fmt_qty(it['min_stock'])} | {dl} | {status} |")
    md += ["", f"## {L('cash')}", "", f"- **{L('total_collected')}:** {fmt_money(total_col)}",
           f"- **{L('collected_today')}:** {fmt_money(today_col)}",
           f"- **{L('pending')}:** {fmt_money(sum(d['bal'] for d in debts))}"]
    if debts:
        for d in debts:
            md.append(f"  - {md_esc(d['entity'])}: {fmt_money(d['bal'])} ({L('since')} {parse_ts(d['first']).strftime('%d %b')})")
    else:
        md.append(f"  - {L('no_pending')}")
    md += ["", f"## {L('promises')}", ""]
    md += [f"- [{'x' if p['done'] else ' '}] **{md_esc(p['person'])}**: {md_esc(p['task'])}" for p in proms] or [f"*{L('no_promises')}*"]
    md += ["", f"## {L('forecast')}", ""]
    if fc:
        md += [f"| {L('item')} | {L('festival')} | {L('order_by')} | {L('order_qty')} | {L('urgency')} |", "|---|---|---|---:|---|"]
        for r in sorted(fc, key=lambda r: r["must_order_by"])[:10]:
            q = r["recommended_order_qty"]
            md.append(f"| {md_esc(r['item'])} | {md_esc(r['festival_name'] or L('regular'))} | {r['must_order_by']} | "
                      f"{'-' if q is None else fmt_qty(q)} | {L(r['urgency'])} |")
    else:
        md.append(f"*{L('no_forecast')}*")
    md += ["", f"## {L('risks')}", ""]
    md += [f"- ⚠️ {md_esc(r)}" for r in risks] or [f"*{L('no_risks')}*"]
    return "\n".join(md)


# ------------------------------------------------------------------ seeding ---
SEED_ITEMS = [  # name, sku, unit, qty, min, burn, shelf_life_days
    ("Ghee", "ITM-GHEE", "kg", 20, 8, 1.5, None), ("Flour", "ITM-FLOUR", "kg", 50, 20, 4.0, None),
    ("Gift Boxes", "ITM-GIFTBOX", "pcs", 30, 15, 2.0, None), ("Sugar", "ITM-SUGAR", "kg", 14, 15, 3.0, None),
    ("Milk", "ITM-MILK", "L", 12, 10, 8.0, 3), ("Coffee Beans", "ITM-COFFEE", "kg", 4, 3, 0.8, None),
    ("Paper Cups", "ITM-CUPS", "pcs", 300, 200, 60.0, None), ("Fresh Mithai", "ITM-MITHAI", "kg", 6, 4, 3.0, 4)]
SEED_BRANCH2 = [("Ghee", "ITM-GHEE", "kg", 8, 5, 0.9, None), ("Gift Boxes", "ITM-GIFTBOX", "pcs", 12, 10, 1.2, None),
                ("Paper Cups", "ITM-CUPS", "pcs", 120, 100, 30.0, None)]


def _seed_item(c, branch, spec, rng):
    name, sku, unit, qty, mn, burn, shelf = spec
    c.execute("INSERT INTO items(branch,name,sku,unit,qty,min_stock,baseline_burn,shelf_life_days) VALUES(?,?,?,?,?,?,?,?)",
              (branch, name, sku, unit, qty, mn, burn, shelf))
    base = now_dt().replace(hour=12, minute=0, second=0)
    moves = []
    for d in range(21, 0, -1):
        v = max(0.0, rng.gauss(burn, burn * 0.2))
        v = float(round(v)) if unit == "pcs" else round(v, 1)
        if v > 0:
            moves.append((-v, d))
    restock = round(burn * 7) if unit == "pcs" else round(burn * 7, 1)
    inflow = [(restock, 10)]
    opening = round(qty - (sum(m for m, _ in moves) + restock), 6)
    if opening < 0:
        inflow, opening = [], round(qty - sum(m for m, _ in moves), 6)
    rows = [("seed-open-%s-%s" % (branch, name), base - timedelta(days=22), opening)]
    rows += [(uuid.uuid4().hex, base - timedelta(days=d), ch) for ch, d in moves]
    rows += [(uuid.uuid4().hex, base - timedelta(days=d, hours=1), ch) for ch, d in inflow]
    for mid, ts, ch in rows:
        c.execute("INSERT INTO movements(id,ts,branch,item,change,source,note,synced) VALUES(?,?,?,?,?,?,?,1)",
                  (mid, ts.strftime("%Y-%m-%d %H:%M:%S"), branch, name, ch, "seed", "starter data"))
    return name


def init_db():
    with db() as c:
        c.executescript(SCHEMA)
        if meta_get(c, "seeded"):
            return
        rng, n = random.Random(42), now_dt()
        for b in (DEFAULT_BRANCH, "Navrangpura Branch"):
            ensure_branch(c, b)
        for spec in SEED_ITEMS:
            _seed_item(c, DEFAULT_BRANCH, spec, rng)
        for spec in SEED_BRANCH2:
            _seed_item(c, "Navrangpura Branch", spec, rng)
        # a few live scanner events so the feed looks alive
        apply_movement(c, DEFAULT_BRANCH, "Paper Cups", -10, "scanner", "seed", ts=(n - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
        apply_movement(c, DEFAULT_BRANCH, "Gift Boxes", -1, "scanner", "seed", ts=(n - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
        for d in range(14, 0, -1):
            add_cash_event(c, DEFAULT_BRANCH, "collected", "Counter sales", round(rng.uniform(1800, 2600)), "Daily sales",
                           (n - timedelta(days=d)).strftime("%Y-%m-%d 20:00:00"))
        add_cash_event(c, DEFAULT_BRANCH, "owed", "Dave", 1200, "Sweet boxes on credit", (n - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"))
        add_cash_event(c, DEFAULT_BRANCH, "owed", "Mehta Catering", 8500, "Wedding order balance", (n - timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S"))
        add_cash_event(c, DEFAULT_BRANCH, "owed", "Priya", 650, "Birthday mithai", (n - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"))
        for person, task, done, days in [("Mehta Catering", "Deliver 20 gift boxes before Saturday", 0, 4),
                                         ("Ramesh (ghee supplier)", "Call about the price revision", 0, 1),
                                         ("Dave", "Send invoice copy", 1, 6)]:
            c.execute("INSERT INTO promises(ts,branch,person,task,done,done_ts) VALUES(?,?,?,?,?,?)",
                      ((n - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"), DEFAULT_BRANCH, person, task, done,
                       now_str() if done else None))
        add_risk(c, DEFAULT_BRANCH, "Ghee supplier raised prices twice this month and there is no backup supplier.", "note")
        # Festival calendar (dates/multipliers are editable in the sidebar)
        for f in [("Diwali", "2026-11-08", 2.8, 4), ("Christmas", "2026-12-25", 1.6, 2), ("Uttarayan", "2027-01-14", 2.2, 2)]:
            c.execute("INSERT OR IGNORE INTO festivals VALUES(?,?,?,?)", f)
        meta_set(c, "lead_days", SUPPLIER_LEAD_DAYS)
        meta_set(c, "seeded", "1")
        meta_set(c, "last_sync", now_str())


# --------------------------------------------------------------------- UI ---
def main():
    st.set_page_config(page_title="LivingDoc", page_icon="📄", layout="wide")
    init_db()
    lang_names = {"en": "English", "hi": "हिन्दी", "gu": "ગુજરાતી"}
    with st.sidebar:
        lang = st.selectbox("Language / भाषा / ભાષા", list(lang_names), format_func=lang_names.get)
        with db() as c:
            branches = [r["name"] for r in c.execute("SELECT name FROM branches ORDER BY name")]
        branch = st.selectbox(tr(lang, "branch"), branches, index=branches.index(DEFAULT_BRANCH) if DEFAULT_BRANCH in branches else 0)
        with db() as c:
            bad = audit_stock(c)
            last_sync = meta_get(c, "last_sync", "-")
        st.caption(("✅ Stock audit: movement log matches counts" if not bad else f"⚠️ Stock audit: {len(bad)} mismatch(es)")
                   + f"  \n🔄 Last branch sync: {last_sync}")
        if st.button(tr(lang, "sync_now")):
            res = sync_if_due(force=True) or {}
            st.success(f"↑ {res.get('pushed', 0)}  ↓ {res.get('pulled', 0)}") if "error" not in res else st.error(res["error"])
        with st.expander("➕ Item / physical count"):
            with st.form("item_form", clear_on_submit=True):
                n_name = st.text_input("Name")
                n_sku = st.text_input("Barcode / SKU")
                c1, c2 = st.columns(2)
                n_unit = c1.text_input("Unit", "pcs")
                n_min = c2.number_input("Min stock", 0.0, step=1.0)
                n_burn = c1.number_input("Daily use (optional)", 0.0, step=0.5)
                n_shelf = c2.number_input("Shelf life days (0 = none)", 0, step=1)
                n_count = st.number_input("Counted quantity (blank = leave)", min_value=-1.0, value=-1.0, step=1.0,
                                          help="-1 means do not adjust. Any other value logs a correction.")
                if st.form_submit_button("Save") and n_name.strip():
                    with db() as c:
                        name, created = resolve_item(c, branch, n_name)
                        c.execute("UPDATE items SET unit=?, min_stock=?, baseline_burn=CASE WHEN ?>0 THEN ? ELSE baseline_burn END, "
                                  "shelf_life_days=?, sku=COALESCE(NULLIF(?,''), sku), needs_review=0 WHERE branch=? AND name=?",
                                  (n_unit.strip() or "pcs", n_min, n_burn, n_burn, int(n_shelf) or None, n_sku.strip(), branch, name))
                        if n_count >= 0:
                            cur = c.execute("SELECT qty FROM items WHERE branch=? AND name=?", (branch, name)).fetchone()["qty"]
                            apply_movement(c, branch, name, n_count - cur, "count", "physical count")
            st.caption("Saved items appear in the page on the next refresh.")
        with st.expander("🎉 Festival calendar"):
            with db() as c:
                fest = [dict(r) for r in c.execute("SELECT * FROM festivals ORDER BY date")]
                lead_days = int(meta_get(c, "lead_days", SUPPLIER_LEAD_DAYS))
            st.dataframe(fest, hide_index=True)
            with st.form("fest_form", clear_on_submit=True):
                f_name = st.text_input("Festival name")
                f_date = st.date_input("Date", value=date.today() + timedelta(days=30))
                f_mult = st.number_input("Surge multiplier", 1.0, 10.0, 2.0, 0.1)
                f_black = st.number_input("Supplier blackout days", 0, 30, 3)
                f_lead = st.number_input("Standard supplier lead time (days)", 0, 60, lead_days)
                if st.form_submit_button("Save festival / lead time"):
                    with db() as c:
                        if f_name.strip():
                            c.execute("INSERT OR REPLACE INTO festivals VALUES(?,?,?,?)",
                                      (f_name.strip(), f_date.isoformat(), float(f_mult), int(f_black)))
                        meta_set(c, "lead_days", int(f_lead))

    st.title(tr(lang, "title"))
    left, right = st.columns([2, 3], gap="large")

    with left:
        st.subheader(tr(lang, "notes_header"))
        with st.form("note_form", clear_on_submit=True):
            text = st.text_area("note", height=220, placeholder=tr(lang, "notes_hint"), label_visibility="collapsed")
            submitted = st.form_submit_button(tr(lang, "process_btn"), type="primary")
        if submitted and text.strip():
            with st.spinner("..."):
                st.session_state["last_result"] = process_note(text, branch)
        res = st.session_state.get("last_result")
        if res:
            if res.get("error") == "duplicate":
                st.info("This exact note was just processed, so it was not applied twice.")
            elif res.get("ok"):
                st.success("Applied: " + (" · ".join(res["lines"]) if res["lines"] else "nothing to record in that note"))
                st.caption(f"Extractor: {res['extractor']}")
                with st.expander("Structured deltas (what the AI extracted)"):
                    st.json(res["deltas"])
        st.subheader(tr(lang, "scanner"))
        with st.expander("Simulate a scanner event"):
            with db() as c:
                names = [r["name"] for r in c.execute("SELECT name FROM items WHERE branch=? ORDER BY name", (branch,))]
            with st.form("scan_form"):
                s_item = st.selectbox(tr(lang, "item"), names)
                s_qty = st.number_input(tr(lang, "qty"), 1.0, 10000.0, 1.0)
                s_dir = st.radio("Direction", ["out", "in"], horizontal=True)
                if st.form_submit_button("Scan"):
                    Path(SCANNER_INBOX).mkdir(parents=True, exist_ok=True)
                    (Path(SCANNER_INBOX) / f"scan_{uuid.uuid4().hex[:10]}.json").write_text(
                        json.dumps({"event_id": uuid.uuid4().hex, "item": s_item, "qty": s_qty, "direction": s_dir, "branch": branch}))
                    st.session_state["scan_stats"] = process_scanner_inbox(branch, min_age=0)
        if "scan_stats" in st.session_state:
            st.caption(f"Last scan batch: {st.session_state['scan_stats']}")

        def _poll():
            stats = process_scanner_inbox(branch)
            sync_if_due()
            st.caption(f"📡 {SCANNER_INBOX}/ · {datetime.now().strftime('%H:%M:%S')}")
            if stats["applied"] or stats["failed_files"]:
                st.rerun()
        if hasattr(st, "fragment"):
            st.fragment(run_every=10)(_poll)()
        else:
            _poll()

    with right:
        doc = render_doc(branch, lang)
        st.markdown(doc)
        st.download_button("⬇️ Download page (.md)", doc, file_name="livingdoc.md", mime="text/markdown")
        with st.expander("✅ " + tr(lang, "promises")):
            with db() as c:
                rows = c.execute("SELECT id, person, task, done FROM promises WHERE branch=? ORDER BY done, id DESC LIMIT 25", (branch,)).fetchall()

            def _toggle(pid):
                with db() as cc:
                    cc.execute("UPDATE promises SET done=?, done_ts=? WHERE id=?",
                               (1 if st.session_state[f"p{pid}"] else 0, now_str() if st.session_state[f"p{pid}"] else None, pid))
            for r in rows:
                st.checkbox(f"{r['person']}: {r['task']}", value=bool(r["done"]), key=f"p{r['id']}", on_change=_toggle, args=(r["id"],))
        with st.expander("🚨 " + tr(lang, "risks")):
            with db() as c:
                rr = c.execute("SELECT id, text FROM risks WHERE branch=? AND resolved=0 ORDER BY id DESC", (branch,)).fetchall()

            def _resolve(rid):
                with db() as cc:
                    cc.execute("UPDATE risks SET resolved=1 WHERE id=?", (rid,))
            for r in rr:
                st.checkbox(r["text"], value=False, key=f"r{r['id']}", on_change=_resolve, args=(r["id"],),
                            help="Tick when you have dealt with this")


def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if st is not None and _in_streamlit():
    main()
elif __name__ == "__main__":
    print("Run with:  streamlit run livingdoc_app.py")
