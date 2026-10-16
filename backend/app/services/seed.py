"""Starter data so the app is useful on first run (sweet shop + cafe, two branches)."""
import random
import uuid
from datetime import timedelta

from ..config import settings, now_dt, now_str
from ..database import SCHEMA, add_risk, db, ensure_branch, meta_get, meta_set
from .inventory import apply_movement
from .ledger import add_cash_event


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
        for b in (settings.default_branch, "Navrangpura Branch"):
            ensure_branch(c, b)
        for spec in SEED_ITEMS:
            _seed_item(c, settings.default_branch, spec, rng)
        for spec in SEED_BRANCH2:
            _seed_item(c, "Navrangpura Branch", spec, rng)
        # a few live scanner events so the feed looks alive
        apply_movement(c, settings.default_branch, "Paper Cups", -10, "scanner", "seed", ts=(n - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
        apply_movement(c, settings.default_branch, "Gift Boxes", -1, "scanner", "seed", ts=(n - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
        for d in range(14, 0, -1):
            add_cash_event(c, settings.default_branch, "collected", "Counter sales", round(rng.uniform(1800, 2600)), "Daily sales",
                           (n - timedelta(days=d)).strftime("%Y-%m-%d 20:00:00"))
        add_cash_event(c, settings.default_branch, "owed", "Dave", 1200, "Sweet boxes on credit", (n - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"))
        add_cash_event(c, settings.default_branch, "owed", "Mehta Catering", 8500, "Wedding order balance", (n - timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S"))
        add_cash_event(c, settings.default_branch, "owed", "Priya", 650, "Birthday mithai", (n - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"))
        for person, task, done, days in [("Mehta Catering", "Deliver 20 gift boxes before Saturday", 0, 4),
                                         ("Ramesh (ghee supplier)", "Call about the price revision", 0, 1),
                                         ("Dave", "Send invoice copy", 1, 6)]:
            c.execute("INSERT INTO promises(ts,branch,person,task,done,done_ts) VALUES(?,?,?,?,?,?)",
                      ((n - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"), settings.default_branch, person, task, done,
                       now_str() if done else None))
        add_risk(c, settings.default_branch, "Ghee supplier raised prices twice this month and there is no backup supplier.", "note")
        # Festival calendar (dates/multipliers are editable in the sidebar)
        for f in [("Diwali", "2026-11-08", 2.8, 4), ("Christmas", "2026-12-25", 1.6, 2), ("Uttarayan", "2027-01-14", 2.2, 2)]:
            c.execute("INSERT OR IGNORE INTO festivals VALUES(?,?,?,?)", f)
        meta_set(c, "lead_days", settings.supplier_lead_days)
        meta_set(c, "seeded", "1")
        meta_set(c, "last_sync", now_str())
