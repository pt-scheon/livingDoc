"""Proof without exposure: share facts about your promises without sharing the promises.

What this is (and is not)
-------------------------
It is a SIGNED, COMMITTED, SELECTIVELY-OPENABLE attestation:

1. Only entries that BOTH the owner and the counterparty allow (owner opt-in, no counterparty veto) are ever counted.
2. From those, the shop issues a few claims stated as bands/thresholds ("receivables of at least Rs 5,000", "nothing more than
   14 days overdue"): no names, no individual amounts, no descriptions.
3. Every counted entry is committed to a salted hash; the hashes form a Merkle tree and the root is signed (Ed25519) together
   with the claims. The shop cannot quietly change an entry afterwards without breaking the root.
4. A verifier can challenge: they send a nonce, the entries to open are derived from root+nonce (so the shop cannot pick
   flattering ones), and the shop (holding the proof's open key) reveals just those entries, with names replaced by a
   per-proof pseudonym, each with a Merkle path.

It is NOT a zero-knowledge proof: claims are the shop's own statements; the spot-check makes cherry-picking detectable
for the sampled entries, not mathematically impossible for the rest. It also says nothing about entries that were not
consented. The packet says so.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..database import db, meta_get, meta_set
from . import trust

VERSION = 1
MIN_RESOLVED_FOR_KEPT_RATE = 5
OPEN_SAMPLE = 3
DEFAULT_VALID_DAYS = 7
MAX_VALID_DAYS = 90
OVERDUE_BANDS = (0, 7, 14, 30, 60, 90, 180)
CLAIM_IDS = ("receivable_floor", "parties_floor", "max_overdue", "kept_rate_floor", "payable_ceiling", "concentration_ceiling")
SCOPE_NOTE = ("Claims cover only entries that both the shop and the other person allowed into proofs. They say nothing about entries "
              "kept private, and they are the shop's own signed statements, not zero-knowledge proofs.")


# ----------------------------------------------------------------------------- helpers
def _norm(o):
    """Whole-number floats become ints so 5000.0 and 5000 sign identically (JavaScript and Python print them differently)."""
    if isinstance(o, float) and o.is_integer():
        return int(o)
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_norm(v) for v in o]
    return o


def canon(obj) -> bytes:
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(b: bytes | str) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def floor_band(x: float) -> float:
    """Largest of 1-2-5 x 10^k that is <= x (0 if x < 1). A threshold that hides the exact figure."""
    if x < 1:
        return 0.0
    best, p = 1.0, 1.0
    while p <= x * 10:
        for m in (1, 2, 5):
            if m * p <= x:
                best = m * p
        p *= 10
    return best


def ceil_band(x: float) -> float:
    if x <= 0:
        return 0.0
    p = 1.0
    while True:
        for m in (1, 2, 5):
            if m * p >= x:
                return m * p
        p *= 10


def _key() -> Ed25519PrivateKey:
    with db() as c:
        hexkey = meta_get(c, "proof_signing_key")
        if not hexkey:
            k = Ed25519PrivateKey.generate()
            hexkey = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex()
            meta_set(c, "proof_signing_key", hexkey)
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(hexkey))


def public_hex() -> str:
    return _key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


# ----------------------------------------------------------------------------- merkle tree
def merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return sha("empty")
    level = sorted(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [sha(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_path(sorted_leaves: list[str], index: int) -> list[list[str]]:
    path, level, i = [], list(sorted_leaves), index
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        sib = i ^ 1
        path.append(["R" if sib > i else "L", level[sib]])
        level = [sha(level[j] + level[j + 1]) for j in range(0, len(level), 2)]
        i //= 2
    return path


def verify_path(leaf: str, path: list[list[str]], root: str) -> bool:
    h = leaf
    for side, sib in path:
        h = sha(h + sib) if side == "R" else sha(sib + h)
    return h == root


def challenge_indices(root: str, nonce: str, n: int) -> list[int]:
    out, j = [], 0
    while len(out) < min(OPEN_SAMPLE, n) and j < 1000:
        i = int(sha(f"{root}|{nonce}|{j}"), 16) % n
        if i not in out:
            out.append(i)
        j += 1
    return out


# ----------------------------------------------------------------------------- claims
def consenting(branch: str) -> list[dict]:
    d = trust.ledger(branch)
    return [e for e in d["entries"] if e["counts_in_proofs"]]


def compute_claims(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (claims, withheld). Claims are bands/thresholds; `withheld` explains what could not be said safely."""
    claims, withheld = [], []
    opens = [e for e in entries if e["status"] == "open"]
    rec = [e for e in opens if e["kind"] == "owed_to_us" and e["conservative_amount"] > 0]
    pay = [e for e in opens if e["kind"] == "we_owe" and e["conservative_amount"] > 0]
    if rec:
        total = sum(e["conservative_amount"] for e in rec)
        fb = floor_band(total)
        if fb > 0:
            claims.append(dict(id="receivable_floor", op=">=", value=fb, unit="INR"))
        parties = {trust.key_of(e["counterparty"]) for e in rec}
        claims.append(dict(id="parties_floor", op=">=", value=min(len(parties), 10), unit="count"))
        worst = max(e["overdue_days"] for e in rec)
        band = next((b for b in OVERDUE_BANDS if worst <= b), None)
        if band is not None:
            claims.append(dict(id="max_overdue", op="<=", value=band, unit="days"))
        if len(parties) >= 2:
            by = {}
            for e in rec:
                by[trust.key_of(e["counterparty"])] = by.get(trust.key_of(e["counterparty"]), 0) + e["conservative_amount"]
            share = max(by.values()) / total
            claims.append(dict(id="concentration_ceiling", op="<=", value=min(1.0, -(-share * 10 // 1) / 10), unit="share"))
        else:
            withheld.append(dict(id="concentration_ceiling", reason="needs at least two parties"))
    else:
        for cid in ("receivable_floor", "parties_floor", "max_overdue", "concentration_ceiling"):
            withheld.append(dict(id=cid, reason="no consenting open receivables"))
    res = [e for e in entries if e["status"] in ("kept", "broken") and e["kind"] in ("owed_to_us", "we_owe", "word", "favour_given", "favour_owed")]
    if len(res) >= MIN_RESOLVED_FOR_KEPT_RATE:
        kept = sum(1 for e in res if e["status"] == "kept")
        claims.append(dict(id="kept_rate_floor", op=">=", value=int((kept / len(res)) * 20) / 20, unit="share"))
    else:
        withheld.append(dict(id="kept_rate_floor", reason=f"needs at least {MIN_RESOLVED_FOR_KEPT_RATE} resolved consenting promises (small samples would identify people)"))
    if pay:
        claims.append(dict(id="payable_ceiling", op="<=", value=ceil_band(sum(e["conservative_amount"] for e in pay)), unit="INR"))
    else:
        withheld.append(dict(id="payable_ceiling", reason="no consenting open payables"))
    return claims, withheld


def preview(branch: str) -> dict:
    ents = consenting(branch)
    claims, withheld = compute_claims(ents)
    d = trust.ledger(branch)
    excluded = [dict(id=e["id"], why="owner_not_opted_in" if not e["proof_owner"] else "counterparty_withheld") for e in d["entries"] if not e["counts_in_proofs"]]
    return dict(consenting=len(ents), excluded=len(excluded), excluded_entries=excluded, claims=claims, withheld=withheld, scope_note=SCOPE_NOTE,
                reveals="Only the bands above, the number of consenting entries, a salted Merkle root and the shop's public key. No names, amounts or descriptions.")


# ----------------------------------------------------------------------------- issue / list / revoke
def issue(branch: str, claim_ids: list[str] | None = None, valid_days: int = DEFAULT_VALID_DAYS) -> dict:
    if not 1 <= int(valid_days) <= MAX_VALID_DAYS:
        raise trust.TrustError(f"valid_days must be between 1 and {MAX_VALID_DAYS}")
    if claim_ids is not None and not set(claim_ids) <= set(CLAIM_IDS):
        raise trust.TrustError("Unknown claim id.")
    ents = consenting(branch)
    if not ents:
        raise trust.TrustError("Nothing to prove yet: no entry is opted in. Tick 'allow in proofs' on entries that you and the other person are happy to count.")
    claims, withheld = compute_claims(ents)
    if claim_ids is not None:
        claims = [c for c in claims if c["id"] in claim_ids]
    if not claims:
        raise trust.TrustError("None of the chosen claims can be made safely from the consenting entries.")
    psalt = secrets.token_hex(8)
    leaves = []
    for e in ents:
        data = dict(kind=e["kind"], party=sha(psalt + "|" + trust.key_of(e["counterparty"]))[:10], amount=e["conservative_amount"] or e["amount"],
                    created_on=e["created_on"], due_on=e["due_effective"], status=e["status"], resolved_on=e["resolved_on"])
        salt = secrets.token_hex(16)
        leaves.append(dict(hash=sha("leaf|" + salt + "|" + canon(data).decode()), salt=salt, data=data))
    root = merkle_root([l["hash"] for l in leaves])
    now = trust.today()
    pid = secrets.token_hex(6)
    pub = public_hex()
    packet = dict(v=VERSION, id=pid, shop=sha(pub + "|" + branch)[:16], issued_on=now.isoformat(), valid_until=(now + timedelta(days=int(valid_days))).isoformat(),
                  claims=claims, entries_counted=len(leaves), merkle_root=root, scope_note=SCOPE_NOTE, public_key=pub)
    packet["signature"] = _key().sign(canon(packet)).hex()
    open_key = secrets.token_urlsafe(16)
    with db() as c:
        c.execute("INSERT INTO trust_proofs(id,branch,created_on,packet,open_key_hash,leaves) VALUES(?,?,?,?,?,?)",
                  (pid, branch, now.isoformat(), json.dumps(packet), sha(open_key), json.dumps(sorted(leaves, key=lambda l: l["hash"]))))
    return dict(packet=packet, open_key=open_key, withheld=withheld)


def list_proofs(branch: str) -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT id, created_on, packet, revoked FROM trust_proofs WHERE branch=? ORDER BY created_on DESC, rowid DESC", (branch,)).fetchall()
    out = []
    for r in rows:
        p = json.loads(r["packet"])
        out.append(dict(id=r["id"], issued_on=p["issued_on"], valid_until=p["valid_until"], claims=p["claims"], entries_counted=p["entries_counted"],
                        revoked=bool(r["revoked"]), expired=p["valid_until"] < trust.today().isoformat()))
    return out


def get_packet(pid: str) -> dict:
    with db() as c:
        r = c.execute("SELECT packet, revoked FROM trust_proofs WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise KeyError(pid)
    return dict(packet=json.loads(r["packet"]), revoked=bool(r["revoked"]))


def revoke(branch: str, pid: str) -> None:
    with db() as c:
        if c.execute("UPDATE trust_proofs SET revoked=1 WHERE id=? AND branch=?", (pid, branch)).rowcount == 0:
            raise KeyError(pid)


# ----------------------------------------------------------------------------- verify
def verify_signature(packet: dict) -> bool:
    try:
        body = {k: v for k, v in packet.items() if k != "signature"}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(packet["public_key"])).verify(bytes.fromhex(packet["signature"]), canon(body))
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False


def verify(packet: dict) -> dict:
    """Stateless checks anyone can do, plus (when this server issued it) revocation status."""
    ok = isinstance(packet, dict) and verify_signature(packet)
    res = dict(signature_valid=ok, expired=None, revoked=None, issued_by_this_shop=None, claims=[], entries_counted=None)
    if not ok:
        return res
    res["expired"] = packet["valid_until"] < trust.today().isoformat()
    res["claims"], res["entries_counted"], res["scope_note"] = packet["claims"], packet["entries_counted"], packet.get("scope_note")
    with db() as c:
        r = c.execute("SELECT revoked, packet FROM trust_proofs WHERE id=?", (packet.get("id"),)).fetchone()
    if r is not None:
        res["issued_by_this_shop"] = json.loads(r["packet"]).get("signature") == packet["signature"]
        res["revoked"] = bool(r["revoked"]) if res["issued_by_this_shop"] else None
    res["valid"] = ok and not res["expired"] and res["revoked"] is not True
    return res


# ----------------------------------------------------------------------------- spot-check openings
def open_leaves(pid: str, open_key: str, nonce: str) -> dict:
    if not nonce or len(nonce) < 8:
        raise trust.TrustError("The challenge nonce must be at least 8 characters (use random text).")
    with db() as c:
        r = c.execute("SELECT packet, open_key_hash, revoked, leaves FROM trust_proofs WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise KeyError(pid)
    if not hmac.compare_digest(r["open_key_hash"], sha(open_key or "")):
        raise PermissionError("wrong open key")
    if r["revoked"]:
        raise trust.TrustError("This proof was revoked.")
    packet, leaves = json.loads(r["packet"]), json.loads(r["leaves"])
    hashes = [l["hash"] for l in leaves]
    idx = challenge_indices(packet["merkle_root"], nonce, len(leaves))
    return dict(nonce=nonce, indices=idx, openings=[dict(index=i, salt=leaves[i]["salt"], data=leaves[i]["data"], leaf=leaves[i]["hash"],
                                                          path=merkle_path(hashes, i)) for i in idx])


def check_openings(packet: dict, nonce: str, openings: list[dict]) -> dict:
    """Verifier side: signature, challenge indices, leaf hashes, Merkle paths and consistency with the claims."""
    if not verify_signature(packet):
        return dict(ok=False, reason="bad_signature", checks=[])
    n, root = packet["entries_counted"], packet["merkle_root"]
    want = challenge_indices(root, nonce, n)
    got = [o.get("index") for o in openings]
    checks = []
    max_overdue = next((c["value"] for c in packet["claims"] if c["id"] == "max_overdue"), None)
    for o in openings:
        d = o.get("data", {})
        leaf_ok = sha("leaf|" + str(o.get("salt")) + "|" + canon(d).decode()) == o.get("leaf")
        path_ok = leaf_ok and verify_path(o["leaf"], o.get("path", []), root)
        consistent = True
        if max_overdue is not None and d.get("kind") == "owed_to_us" and d.get("status") == "open" and d.get("due_on"):
            late = (trust._d(packet["issued_on"]) - trust._d(d["due_on"])).days
            consistent = late <= max_overdue
        checks.append(dict(index=o.get("index"), leaf_matches_data=leaf_ok, in_tree=path_ok, consistent_with_claims=consistent))
    ok = got == want and all(c["in_tree"] and c["consistent_with_claims"] for c in checks) and len(openings) == len(want)
    return dict(ok=ok, indices_as_challenged=got == want, expected_indices=want, checks=checks)
