"""Feedback in two directions, one table.

owner    -> developer : the shop owner suggests a fix or idea for LivingDoc itself ("Suggest to the developer").
customer -> owner     : a visitor to the public shop page leaves a rating and a comment for the shop.

Privacy: a customer's name and contact are optional and only the owner ever sees them. The developer export (for the
notes folder that coding assistants such as Gemini read) contains owner suggestions only; for customers it holds counts
and an average rating, never a comment, name or contact.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from ..database import db
from . import trust

CATEGORIES = ("bug", "idea", "confusing", "praise")
STATUSES = ("new", "seen", "planned", "done", "dismissed")
MAX_TEXT = 600
_HITS: dict[str, deque] = defaultdict(deque)
PUBLIC_LIMIT = (8, 3600)     # at most 8 customer comments per shop per hour


class FeedbackError(ValueError):
    pass


def _clean(s, n):
    return (s or "").strip()[:n]


def add(branch, source, text, category="idea", rating=None, name="", contact="", lang="en", screen=""):
    text = (text or "").strip()
    if not text and rating is None:
        raise FeedbackError("Write a few words or choose a rating")
    if len(text) > MAX_TEXT:
        raise FeedbackError(f"Please keep it under {MAX_TEXT} characters")
    if source not in ("owner", "customer"):
        raise FeedbackError("Unknown source")
    if category not in CATEGORIES:
        raise FeedbackError("Unknown category")
    if rating is not None and not 1 <= int(rating) <= 5:
        raise FeedbackError("Rating must be 1 to 5")
    with db() as c:
        cur = c.execute("INSERT INTO feedback(branch,source,category,rating,text,name,contact,lang,screen,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (branch, source, category, None if rating is None else int(rating), text, _clean(name, 80), _clean(contact, 120),
                         _clean(lang, 5) or "en", _clean(screen, 40), trust.today().isoformat()))
        return _row(c.execute("SELECT * FROM feedback WHERE id=?", (cur.lastrowid,)).fetchone())


def throttle(key) -> bool:
    """True when this shop has had too many public comments lately."""
    now, q = time.time(), _HITS[key]
    while q and now - q[0] > PUBLIC_LIMIT[1]:
        q.popleft()
    if len(q) >= PUBLIC_LIMIT[0]:
        return True
    q.append(now)
    return False


def _row(r):
    return dict(r)


def list_(branch, source=None):
    q, a = "SELECT * FROM feedback WHERE branch=?", [branch]
    if source:
        q += " AND source=?"; a.append(source)
    with db() as c:
        return [_row(r) for r in c.execute(q + " ORDER BY id DESC LIMIT 200", a)]


def set_status(branch, fid, status=None, dev_note=None):
    if status is not None and status not in STATUSES:
        raise FeedbackError("Unknown status")
    with db() as c:
        r = c.execute("SELECT * FROM feedback WHERE id=? AND branch=?", (fid, branch)).fetchone()
        if r is None:
            raise KeyError(fid)
        c.execute("UPDATE feedback SET status=?, dev_note=? WHERE id=?", (status or r["status"], _clean(dev_note, 400) if dev_note is not None else r["dev_note"], fid))
        return _row(c.execute("SELECT * FROM feedback WHERE id=?", (fid,)).fetchone())


def summary(branch):
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT source, rating, status FROM feedback WHERE branch=?", (branch,))]
    cust = [r for r in rows if r["source"] == "customer"]
    rated = [r["rating"] for r in cust if r["rating"]]
    return dict(owner_total=sum(r["source"] == "owner" for r in rows), owner_open=sum(r["source"] == "owner" and r["status"] in ("new", "seen", "planned") for r in rows),
                customer_total=len(cust), customer_new=sum(r["status"] == "new" for r in cust),
                average_rating=round(sum(rated) / len(rated), 2) if rated else None, rated=len(rated))


def export_markdown(branch):
    """Developer-facing notes. Owner suggestions in full; customers as numbers only."""
    s = summary(branch)
    out = ["# Feedback from the shop owner", "",
           "_Generated from the app (`GET /api/feedback/export.md` or `python scripts/export_feedback.py`). Do not edit by hand: change statuses in the app/API._", "",
           f"Owner suggestions: {s['owner_total']} ({s['owner_open']} still open). Customer comments: {s['customer_total']}"
           + (f", average rating {s['average_rating']} from {s['rated']} ratings." if s["average_rating"] else "."),
           "(Customer comments, names and contacts are private to the owner and are not exported.)", ""]
    rows = list_(branch, "owner")
    for st in ("new", "seen", "planned", "done", "dismissed"):
        part = [r for r in rows if r["status"] == st]
        if not part:
            continue
        out += [f"## {st.capitalize()} ({len(part)})", ""]
        for r in part:
            where = f" · screen: {r['screen']}" if r["screen"] else ""
            out.append(f"- **#{r['id']} [{r['category']}]** {r['text']}  _({r['created_at']}{where})_")
            if r["dev_note"]:
                out.append(f"  - developer note: {r['dev_note']}")
        out.append("")
    if not rows:
        out.append("_No suggestions yet._")
    return "\n".join(out).rstrip() + "\n"
