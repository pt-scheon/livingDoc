"""Multi-branch sync through a shared hub database (idempotent push/pull of stock movements)."""

from ..config import settings, now_dt, now_str, parse_ts
from ..database import HUB_SCHEMA, db, ensure_branch, meta_get, meta_set


# ---------------------------------------------------------- multi-branch sync ---
def sync_with_hub():
    """Push unsynced stock movements to the shared hub and pull other branches' movements (idempotent by id)."""
    with db() as c:
        rows = c.execute("SELECT * FROM movements WHERE synced=0 ORDER BY ts").fetchall()
        last_seq = int(meta_get(c, "hub_seq", "0"))
    pushed = 0
    with db(settings.hub_path) as h:
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
    if force or not last or (now_dt() - parse_ts(last)).total_seconds() >= settings.sync_interval_seconds:
        try:
            return sync_with_hub()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    return None
