"""Catalogue and settings operations used by the API: items, physical counts, festivals, promises, risks."""
from datetime import date

from ..config import settings, now_str
from ..database import db, ensure_branch, meta_get, meta_set
from .inventory import apply_movement, resolve_item


def list_items(branch):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT name, sku, unit, qty, min_stock, baseline_burn, shelf_life_days, needs_review FROM items "
            "WHERE branch=? ORDER BY name", (branch,))]


def upsert_item(branch, name, unit=None, min_stock=None, daily_use=None, shelf_life_days=None, sku=None, counted=None):
    """Create/update an item and optionally record a physical count as a correction movement."""
    with db() as c:
        ensure_branch(c, branch)
        item, created = resolve_item(c, branch, name, sku)
        sets, args = ["needs_review=0"], []
        for col, val in (("unit", unit), ("min_stock", min_stock), ("sku", sku or None)):
            if val is not None:
                sets.append(f"{col}=?")
                args.append(val)
        if daily_use is not None and daily_use > 0:
            sets.append("baseline_burn=?")
            args.append(daily_use)
        if shelf_life_days is not None:
            sets.append("shelf_life_days=?")
            args.append(shelf_life_days or None)
        c.execute(f"UPDATE items SET {', '.join(sets)} WHERE branch=? AND name=?", (*args, branch, item))
        correction = 0.0
        if counted is not None:
            cur = c.execute("SELECT qty FROM items WHERE branch=? AND name=?", (branch, item)).fetchone()["qty"]
            correction = apply_movement(c, branch, item, counted - cur, "count", "physical count")["applied"]
        row = dict(c.execute("SELECT name, sku, unit, qty, min_stock, baseline_burn, shelf_life_days, needs_review "
                             "FROM items WHERE branch=? AND name=?", (branch, item)).fetchone())
    return {"item": row, "created": created, "correction": correction}


def list_festivals():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM festivals ORDER BY date")]


def save_festival(name, fdate: date, multiplier, blackout_days):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO festivals VALUES(?,?,?,?)", (name.strip(), fdate.isoformat(), float(multiplier), int(blackout_days)))


def delete_festival(name, fdate):
    with db() as c:
        return c.execute("DELETE FROM festivals WHERE name=? AND date=?", (name, fdate)).rowcount


def get_lead_days():
    with db() as c:
        return int(meta_get(c, "lead_days", settings.supplier_lead_days))


def set_lead_days(days):
    with db() as c:
        meta_set(c, "lead_days", int(days))


def set_promise_done(pid, done):
    with db() as c:
        n = c.execute("UPDATE promises SET done=?, done_ts=? WHERE id=?", (1 if done else 0, now_str() if done else None, pid)).rowcount
    return n


def resolve_risk(rid):
    with db() as c:
        return c.execute("UPDATE risks SET resolved=1 WHERE id=?", (rid,)).rowcount


def recent_notes(branch, limit=20):
    import json
    with db() as c:
        rows = c.execute("SELECT id, ts, raw, extractor, deltas_json FROM notes WHERE branch=? ORDER BY id DESC LIMIT ?", (branch, limit)).fetchall()
    return [{"id": r["id"], "ts": r["ts"], "raw": r["raw"], "extractor": r["extractor"], "deltas": json.loads(r["deltas_json"] or "{}")} for r in rows]


def recent_movements(branch, limit=30):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT ts, item, change, source, note FROM movements WHERE branch=? ORDER BY ts DESC, rowid DESC LIMIT ?", (branch, limit))]


def branch_exists(branch):
    with db() as c:
        return c.execute("SELECT 1 FROM branches WHERE name=?", (branch,)).fetchone() is not None


def list_branches():
    with db() as c:
        return [r["name"] for r in c.execute("SELECT name FROM branches ORDER BY name")]
