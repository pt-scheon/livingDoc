"""Trust ledger: promises as two-sided records.

A promise is both an asset (it has value to the business) and someone's private story. So every entry carries:

* the owner's figure (`amount`) AND the counterparty's own figure (`cp_amount`): both views are kept, never silently merged;
* two independent consents for being counted in an outside-facing proof: the owner's (`proof_owner`) and the
  counterparty's (`proof_cp`). Entries default to PRIVATE: they count only when the owner opts in and the
  counterparty has not withheld consent;
* a private link per counterparty so they can see exactly what is recorded about them, how they are scored,
  state their own figure, dispute it, or withhold proof consent.

Existing LivingDoc data is mirrored in (debts from `cash_events`, people's promises from `promises`) as private entries.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta

from ..config import now_str
from ..database import db

KINDS = ("owed_to_us", "we_owe", "favour_given", "favour_owed", "word")
ROLES = ("customer", "supplier", "worker", "neighbour", "other")
STATUSES = ("open", "kept", "broken", "forgiven")
DEFAULT_TERMS_DAYS = 15          # a receivable with no due date is assumed due this many days after it was recorded
DISPUTE_TOLERANCE = 0.10         # figures within 10% of each other count as agreed
PRIOR_P, PRIOR_N = 0.80, 2.0     # new counterparties: assume 80% reliable, worth two observations
LATE_WEIGHT = 0.6                # a promise kept late counts as 0.6 of a kept one


class TrustError(ValueError):
    """Bad input (HTTP 400)."""


def today() -> date:
    return date.today()


def key_of(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _d(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise TrustError(f"Bad date {s!r}; use YYYY-MM-DD.")


def _row(r) -> dict:
    return dict(r)


# ----------------------------------------------------------------------------- mirror core data
def sync_core(c, branch: str) -> None:
    """Mirror customer debts and other people's promises into the ledger (as private entries, nothing is exposed)."""
    for r in c.execute("SELECT id, ts, entity, amount, settled, descr FROM cash_events WHERE branch=? AND type='owed'", (branch,)).fetchall():
        ref = f"cash:{r['id']}"
        done = r["amount"] - r["settled"] <= 0.004
        row = c.execute("SELECT id, status FROM trust_entries WHERE source_ref=?", (ref,)).fetchone()
        if row is None:
            c.execute("INSERT INTO trust_entries(branch,kind,counterparty,role,description,amount,settled,created_on,status,resolved_on,source_ref,salt)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (branch, "owed_to_us", r["entity"], "customer", r["descr"] or "", r["amount"], r["settled"], r["ts"][:10],
                       "kept" if done else "open", today().isoformat() if done else None, ref, secrets.token_hex(8)))
        else:
            sets, args = ["settled=?", "amount=?"], [r["settled"], r["amount"]]
            if row["status"] == "open" and done:
                sets += ["status='kept'", "resolved_on=?"]
                args.append(today().isoformat())
            c.execute(f"UPDATE trust_entries SET {', '.join(sets)} WHERE id=?", (*args, row["id"]))
    for r in c.execute("SELECT id, ts, person, task, done, done_ts FROM promises WHERE branch=?", (branch,)).fetchall():
        if key_of(r["person"]) in ("me", ""):
            continue                                   # the owner's own to-dos are not promises between two parties
        ref = f"promise:{r['id']}"
        row = c.execute("SELECT id, status FROM trust_entries WHERE source_ref=?", (ref,)).fetchone()
        if row is None:
            c.execute("INSERT INTO trust_entries(branch,kind,counterparty,role,description,created_on,status,resolved_on,source_ref,salt)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (branch, "word", r["person"], "other", r["task"], r["ts"][:10], "kept" if r["done"] else "open",
                       (r["done_ts"] or r["ts"])[:10] if r["done"] else None, ref, secrets.token_hex(8)))
        elif row["status"] == "open" and r["done"]:
            c.execute("UPDATE trust_entries SET status='kept', resolved_on=? WHERE id=?", ((r["done_ts"] or now_str())[:10], row["id"]))


# ----------------------------------------------------------------------------- derived fields
def _is_disputed(e: dict) -> bool:
    if e["disputed"]:
        return True
    if e["amount"] and e["cp_amount"] is not None:
        return abs(e["amount"] - e["cp_amount"]) > DISPUTE_TOLERANCE * max(e["amount"], e["cp_amount"])
    return False


def open_amount(e: dict) -> float:
    if e["amount"] is None or e["status"] != "open":
        return 0.0
    return max(round(e["amount"] - (e["settled"] or 0.0), 2), 0.0)


def conservative_open_amount(e: dict) -> float:
    """What a careful outsider may rely on: the LOWER figure of the two views for money owed to us, the HIGHER for what we owe."""
    amt = open_amount(e)
    if e["cp_amount"] is None or amt <= 0:
        return amt
    cp = max(e["cp_amount"] - (e["settled"] or 0.0), 0.0)
    return round(min(amt, cp) if e["kind"] == "owed_to_us" else max(amt, cp), 2)


def due_date(e: dict) -> date | None:
    d = _d(e["due_on"])
    if d is None and e["kind"] in ("owed_to_us", "we_owe") and e["amount"]:
        d = _d(e["created_on"]) + timedelta(days=DEFAULT_TERMS_DAYS)
    return d


def overdue_days(e: dict, ref: date | None = None) -> int:
    d = due_date(e)
    if e["status"] != "open" or d is None:
        return 0
    return max((ref or today()) - d, timedelta(0)).days


def decorate(e: dict) -> dict:
    e = dict(e)
    e["disputed_effective"] = _is_disputed(e)
    e["open_amount"] = open_amount(e)
    e["conservative_amount"] = conservative_open_amount(e)
    e["due_effective"] = due_date(e).isoformat() if due_date(e) else None
    e["overdue_days"] = overdue_days(e)
    e["worth_low"] = min([v for v in (e["amount"], e["cp_amount"]) if v is not None], default=None)
    e["worth_high"] = max([v for v in (e["amount"], e["cp_amount"]) if v is not None], default=None)
    e["derived"] = e["source_ref"] is not None
    e["counts_in_proofs"] = bool(e["proof_owner"]) and e["proof_cp"] != 0
    e.pop("salt", None)
    return e


# ----------------------------------------------------------------------------- scores
def party_scores(entries: list[dict]) -> dict[str, dict]:
    """Explainable reliability per counterparty from RESOLVED promises: on-time kept 1.0, late kept 0.6, broken 0 (forgiven ignored).
    score = (weighted kept + prior) / (resolved + prior weight), so one data point never decides anything."""
    out: dict[str, dict] = {}
    for e in entries:
        k = key_of(e["counterparty"])
        p = out.setdefault(k, dict(name=e["counterparty"], on_time=0, late=0, broken=0, open=0, forgiven=0, delays=[], open_amount=0.0))
        if e["status"] == "open":
            p["open"] += 1
            p["open_amount"] += open_amount(e)
        elif e["status"] == "forgiven":
            p["forgiven"] += 1
        elif e["status"] == "broken":
            p["broken"] += 1
        else:
            due, res = _d(e["due_on"]), _d(e["resolved_on"])
            late = bool(due and res and res > due)
            p["late" if late else "on_time"] += 1
            if due and res:
                p["delays"].append(max((res - due).days, 0))
    for p in out.values():
        n = p["on_time"] + p["late"] + p["broken"]
        w = p["on_time"] + LATE_WEIGHT * p["late"]
        p["resolved"] = n
        p["score"] = round((w + PRIOR_P * PRIOR_N) / (n + PRIOR_N), 3)
        p["avg_delay_days"] = round(sum(p["delays"]) / len(p["delays"]), 1) if p["delays"] else None
        p["label"] = "new" if n == 0 else "reliable" if p["score"] >= 0.8 else "mixed" if p["score"] >= 0.55 else "shaky"
        del p["delays"]
        p["open_amount"] = round(p["open_amount"], 2)
    return out


# ----------------------------------------------------------------------------- CRUD
def raw_entries(c, branch: str) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT * FROM trust_entries WHERE branch=? ORDER BY (status='open') DESC, created_on DESC, id DESC", (branch,))]


def ledger(branch: str) -> dict:
    with db() as c:
        sync_core(c, branch)
        raw = raw_entries(c, branch)
        tokens = {r["name_key"]: r["token"] for r in c.execute("SELECT name_key, token FROM trust_parties WHERE branch=?", (branch,))}
    scores = party_scores(raw)
    entries = [decorate(e) for e in raw]
    for e in entries:
        e["party_score"] = scores[key_of(e["counterparty"])]["score"]
        e["party_label"] = scores[key_of(e["counterparty"])]["label"]
    parties = sorted(({**v, "key": k, "has_link": k in tokens} for k, v in scores.items()), key=lambda p: -p["open_amount"])
    opens = [e for e in entries if e["status"] == "open"]
    summary = dict(
        open_count=len(opens),
        receivable=round(sum(e["open_amount"] for e in opens if e["kind"] == "owed_to_us"), 2),
        payable=round(sum(e["open_amount"] for e in opens if e["kind"] == "we_owe"), 2),
        overdue_count=sum(1 for e in opens if e["overdue_days"] > 0),
        disputed=sum(1 for e in opens if e["disputed_effective"]),
        in_proofs=sum(1 for e in entries if e["counts_in_proofs"]),
        private=sum(1 for e in entries if not e["counts_in_proofs"]),
    )
    return dict(entries=entries, parties=parties, summary=summary)


def _check(kind, counterparty, amount, due_on, role, created_on=None):
    if kind not in KINDS:
        raise TrustError(f"kind must be one of: {', '.join(KINDS)}")
    if role not in ROLES:
        raise TrustError(f"role must be one of: {', '.join(ROLES)}")
    if not (counterparty or "").strip():
        raise TrustError("Name the other person.")
    if amount is not None and not 0 <= float(amount) <= 1e9:
        raise TrustError("Amount must be zero or more.")
    if kind in ("owed_to_us", "we_owe") and not amount:
        raise TrustError("Money promises need an amount.")
    d, cr = _d(due_on), _d(created_on) if created_on else today()
    if d and cr and d < cr - timedelta(days=3650):
        raise TrustError("Due date is implausibly old.")


def create_entry(branch, kind, counterparty, description="", amount=None, due_on=None, role="other", proof_owner=False) -> dict:
    _check(kind, counterparty, amount, due_on, role)
    with db() as c:
        cur = c.execute("INSERT INTO trust_entries(branch,kind,counterparty,role,description,amount,created_on,due_on,proof_owner,salt)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (branch, kind, counterparty.strip(), role, (description or "")[:300], amount, today().isoformat(), due_on or None,
                         1 if proof_owner else 0, secrets.token_hex(8)))
        return decorate(dict(c.execute("SELECT * FROM trust_entries WHERE id=?", (cur.lastrowid,)).fetchone()))


def _get(c, branch, eid):
    r = c.execute("SELECT * FROM trust_entries WHERE id=? AND branch=?", (eid, branch)).fetchone()
    if r is None:
        raise KeyError(eid)
    return dict(r)


def update_entry(branch, eid, patch: dict) -> dict:
    allowed = {"description", "amount", "due_on", "role", "proof_owner"}
    with db() as c:
        e = _get(c, branch, eid)
        new = {**e, **{k: v for k, v in patch.items() if k in allowed and v is not None}}
        if e["source_ref"] and ("amount" in patch and patch["amount"] is not None and patch["amount"] != e["amount"]):
            raise TrustError("This entry mirrors a debt recorded elsewhere; its amount follows that record.")
        _check(new["kind"], new["counterparty"], new["amount"], new["due_on"], new["role"], e["created_on"])
        c.execute("UPDATE trust_entries SET description=?, amount=?, due_on=?, role=?, proof_owner=? WHERE id=?",
                  (new["description"][:300], new["amount"], new["due_on"] or None, new["role"], 1 if new["proof_owner"] else 0, eid))
        return decorate(_get(c, branch, eid))


def resolve_entry(branch, eid, status) -> dict:
    if status not in STATUSES:
        raise TrustError(f"status must be one of: {', '.join(STATUSES)}")
    with db() as c:
        e = _get(c, branch, eid)
        if e["source_ref"] and e["source_ref"].startswith("cash:") and status == "kept" and open_amount(e) > 0:
            raise TrustError("Record the payment in your notes (e.g. 'Dave paid 500') so cash and the ledger stay in step.")
        c.execute("UPDATE trust_entries SET status=?, resolved_on=? WHERE id=?", (status, None if status == "open" else today().isoformat(), eid))
        return decorate(_get(c, branch, eid))


def delete_entry(branch, eid) -> None:
    with db() as c:
        e = _get(c, branch, eid)
        if e["source_ref"]:
            raise TrustError("This entry mirrors another record; remove it there. You can keep it out of every proof by leaving it private.")
        c.execute("DELETE FROM trust_entries WHERE id=?", (eid,))


# ----------------------------------------------------------------------------- counterparty's own view
def party_link(branch: str, name: str) -> dict:
    k = key_of(name)
    if not k:
        raise TrustError("Name the other person.")
    with db() as c:
        row = c.execute("SELECT counterparty FROM trust_entries WHERE branch=? AND lower(trim(counterparty))=?", (branch, k)).fetchone()
        if not row:
            raise KeyError(name)
        name = row["counterparty"]
        r = c.execute("SELECT token FROM trust_parties WHERE branch=? AND name_key=?", (branch, k)).fetchone()
        if r:
            return dict(token=r["token"])
        tok = secrets.token_urlsafe(18)
        c.execute("INSERT INTO trust_parties(token,branch,name_key,name,created_on) VALUES(?,?,?,?,?)", (tok, branch, k, name.strip(), today().isoformat()))
        return dict(token=tok)


def revoke_party_link(branch: str, name: str) -> int:
    with db() as c:
        return c.execute("DELETE FROM trust_parties WHERE branch=? AND name_key=?", (branch, key_of(name))).rowcount


def _party(c, token):
    r = c.execute("SELECT * FROM trust_parties WHERE token=?", (token,)).fetchone()
    if r is None:
        raise KeyError("link")
    return dict(r)


def party_view(token: str) -> dict:
    """Exactly what the shop has recorded about THIS person. Nothing about anyone else."""
    with db() as c:
        p = _party(c, token)
        sync_core(c, p["branch"])
        raw = raw_entries(c, p["branch"])
    k = p["name_key"]
    mine = [e for e in raw if key_of(e["counterparty"]) == k]
    sc = party_scores(raw).get(k)
    shop = [dict(id=e["id"], kind=e["kind"], description=e["description"], amount=e["amount"], settled=e["settled"], cp_amount=e["cp_amount"],
                 cp_note=e["cp_note"], created_on=e["created_on"], due_on=e["due_on"], resolved_on=e["resolved_on"], status=e["status"],
                 disputed=bool(e["disputed"]), included_in_proofs=bool(e["proof_owner"]) and e["proof_cp"] != 0,
                 owner_wants_included=bool(e["proof_owner"]), my_consent=e["proof_cp"]) for e in mine]
    return dict(name=p["name"], branch=p["branch"], entries=shop, score=sc and dict(score=sc["score"], label=sc["label"], on_time=sc["on_time"],
                late=sc["late"], broken=sc["broken"], resolved=sc["resolved"], prior=PRIOR_P, late_weight=LATE_WEIGHT))


def party_respond(token: str, eid: int, cp_amount=None, cp_note=None, disputed=None, proof_consent=None) -> dict:
    with db() as c:
        p = _party(c, token)
        e = _get(c, p["branch"], eid)
        if key_of(e["counterparty"]) != p["name_key"]:
            raise KeyError(eid)
        sets, args = [], []
        if cp_amount is not None:
            if not 0 <= float(cp_amount) <= 1e9:
                raise TrustError("Amount must be zero or more.")
            sets.append("cp_amount=?"); args.append(float(cp_amount))
        if cp_note is not None:
            sets.append("cp_note=?"); args.append(cp_note[:300])
        if disputed is not None:
            sets.append("disputed=?"); args.append(1 if disputed else 0)
        if proof_consent is not None:
            sets.append("proof_cp=?"); args.append(1 if proof_consent else 0)
        if sets:
            c.execute(f"UPDATE trust_entries SET {', '.join(sets)} WHERE id=?", (*args, eid))
    return party_view(token)
