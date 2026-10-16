"""Inventory primitives: item resolution, deterministic stock movements, burn rate, audit."""
import difflib
import uuid
from datetime import timedelta

from ..config import now_dt, now_str, parse_ts
from ..textutil import norm_tokens, pretty_name


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
