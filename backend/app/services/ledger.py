"""Cash events (collected / owed with FIFO settlement) and promises."""
import difflib

from ..config import now_str
from ..textutil import norm_tokens, same_entity


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
