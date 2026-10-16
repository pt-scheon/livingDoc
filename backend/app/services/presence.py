"""Find & trust: a public shop page the owner controls, and an AI helper that only ever drafts.

Rules the code enforces (each is tested):
* Nothing is public until the owner publishes the page, and every field is private until the owner ticks it.
* The public page never contains stock counts, debts, customers, cash or ledger entries. Trust badges are only the
  band-level claims of a signed, unexpired, unrevoked proof the owner chose.
* The helper writes drafts only when asked. It cannot publish, edit the profile or spend: each of those is an owner action,
  logged with who did it and why. Turning autonomy "off" stops suggestions completely.
* Spending is a budget the owner sets. Boosts above the remaining cap are refused. No ad account is connected, so a boost is
  recorded as planned spend and the page says nothing was bought.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

from ..database import db
from . import catalog, proofs, trust

KINDS = ("about", "offer", "trust_line")
LANGS = ("en", "hi", "gu")
MAX_TEXT = 600
LOOKAHEAD_DAYS = 45
PROFILE_TEXT = {"name": 80, "tagline": 120, "about": 600, "area": 80, "hours": 120}


class PresenceError(ValueError):
    pass


def _log(c, branch, actor, action, detail=""):
    c.execute("INSERT INTO presence_log(branch, at, actor, action, detail) VALUES(?,?,?,?,?)", (branch, trust.today().isoformat(), actor, action, detail[:300]))


def _slug(c, branch):
    base = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-") or "shop"
    slug, n = base, 2
    while c.execute("SELECT 1 FROM presence_profiles WHERE slug=? AND branch<>?", (slug, branch)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _profile_row(c, branch):
    r = c.execute("SELECT * FROM presence_profiles WHERE branch=?", (branch,)).fetchone()
    if r is None:
        c.execute("INSERT INTO presence_profiles(branch, slug, name) VALUES(?,?,?)", (branch, _slug(c, branch), branch))
        r = c.execute("SELECT * FROM presence_profiles WHERE branch=?", (branch,)).fetchone()
    return r


def _out(r):
    d = dict(r)
    for k in ("show_products", "show_trust", "published"):
        d[k] = bool(d[k])
    d["product_names"] = json.loads(d["product_names"])
    d["languages"] = [x for x in d["languages"].split(",") if x]
    return d


def get_profile(branch):
    with db() as c:
        return _out(_profile_row(c, branch))


def update_profile(branch, fields: dict):
    with db() as c:
        cur = _profile_row(c, branch)
        sets, args, changed = [], [], []
        for k, v in fields.items():
            if k in PROFILE_TEXT:
                v = (v or "").strip()
                if len(v) > PROFILE_TEXT[k]:
                    raise PresenceError(f"{k} is longer than {PROFILE_TEXT[k]} characters")
            elif k in ("show_products", "show_trust", "published"):
                v = 1 if v else 0
            elif k == "autonomy":
                if v not in ("off", "suggest"):
                    raise PresenceError("autonomy must be 'off' or 'suggest'")
            elif k == "budget_cap":
                v = float(v)
                if not 0 <= v <= 1e7:
                    raise PresenceError("budget cap must be between 0 and 10,000,000")
            elif k == "product_names":
                have = {i["name"] for i in catalog.list_items(branch)}
                v = json.dumps([n for n in dict.fromkeys(v) if n in have])
            elif k == "languages":
                v = ",".join(x for x in v if x in LANGS)
            elif k == "proof_id":
                if v:
                    row = c.execute("SELECT 1 FROM trust_proofs WHERE id=? AND branch=?", (v, branch)).fetchone()
                    if row is None:
                        raise PresenceError("That proof does not exist for this branch")
                else:
                    v = None
            else:
                continue
            if str(cur[k]) != str(v):
                sets.append(f"{k}=?"); args.append(v); changed.append(k)
        if sets:
            c.execute(f"UPDATE presence_profiles SET {', '.join(sets)} WHERE branch=?", (*args, branch))
            _log(c, branch, "owner", "profile_changed", ", ".join(changed))
        return _out(_profile_row(c, branch))


# ----------------------------------------------------------------------------- drafts
_OFFER = {
    "en": "{festival} is on {date}. We are stocking up early so your {festival} list is ready at {shop}{where}. Drop in and tell us what you need.",
    "hi": "{date} को {festival} है। हम पहले से माल भर रहे हैं ताकि {shop}{where} पर आपकी {festival} की सूची तैयार मिले। आइए और बताइए आपको क्या चाहिए।",
    "gu": "{date} ના રોજ {festival} છે. અમે અગાઉથી માલ ભરી રહ્યા છીએ જેથી {shop}{where} પર તમારી {festival} ની યાદી તૈયાર મળે. આવો અને જણાવો તમને શું જોઈએ છે.",
}
_WHERE = {"en": " in {area}", "hi": " ({area})", "gu": " ({area})"}
_ABOUT = {
    "en": "{shop}{where}: {tagline}{products}",
    "hi": "{shop}{where}: {tagline}{products}",
    "gu": "{shop}{where}: {tagline}{products}",
}
_PRODUCTS = {"en": " We stock: {names}.", "hi": " हमारे पास मिलता है: {names}।", "gu": " અમારી પાસે મળે છે: {names}."}
_CLAIM = {
    "receivable_floor": {"en": "Money owed to us is at least ₹{v}.", "hi": "हमें मिलने वाली रकम कम से कम ₹{v} है।", "gu": "અમને મળવાની રકમ ઓછામાં ઓછી ₹{v} છે."},
    "parties_floor": {"en": "Owed by at least {v} different people.", "hi": "कम से कम {v} अलग लोगों से।", "gu": "ઓછામાં ઓછા {v} અલગ લોકો પાસેથી."},
    "max_overdue": {"en": "Nothing we are owed is more than {v} days late.", "hi": "हमें मिलने वाली कोई रकम {v} दिन से ज़्यादा देर की नहीं।", "gu": "અમને મળવાની કોઈ રકમ {v} દિવસથી વધુ મોડી નથી."},
    "kept_rate_floor": {"en": "At least {v}% of promises were kept.", "hi": "कम से कम {v}% वादे निभाए गए।", "gu": "ઓછામાં ઓછા {v}% વચનો નિભાવ્યા."},
    "payable_ceiling": {"en": "We owe at most ₹{v}.", "hi": "हमें अधिकतम ₹{v} देना है।", "gu": "અમારે વધુમાં વધુ ₹{v} આપવાના છે."},
    "concentration_ceiling": {"en": "No one person is more than {v}% of what we are owed.", "hi": "बाक़ी रकम का {v}% से ज़्यादा किसी एक व्यक्ति से नहीं।", "gu": "બાકી રકમનો {v}% થી વધુ ભાગ કોઈ એક વ્યક્તિનો નથી."},
}
_TRUST_HEAD = {"en": "Our books, checkable: ", "hi": "हमारा हिसाब, जाँचा जा सकता है: ", "gu": "અમારો હિસાબ, ચકાસી શકાય: "}


def claim_sentence(claim: dict, lang: str) -> str:
    v = claim["value"]
    if claim["unit"] == "share":
        v = round(v * 100)
    elif claim["unit"] == "INR":
        v = f"{int(v):,}"
    return _CLAIM[claim["id"]][lang].format(v=v)


def valid_proof(c, branch, proof_id):
    """The chosen proof's packet if it is signed by us, unexpired and unrevoked, else None."""
    if not proof_id:
        return None
    r = c.execute("SELECT packet, revoked FROM trust_proofs WHERE id=? AND branch=?", (proof_id, branch)).fetchone()
    if r is None or r["revoked"]:
        return None
    p = json.loads(r["packet"])
    return None if p["valid_until"] < trust.today().isoformat() else p


def suggest(branch, lang="en"):
    """Write drafts from the owner's own data. Called only when the owner asks. Returns the drafts created."""
    if lang not in LANGS:
        raise PresenceError("Unknown language")
    made = []
    with db() as c:
        p = _out(_profile_row(c, branch))
        if p["autonomy"] == "off":
            raise PresenceError("Suggestions are switched off. Turn the helper on to get drafts.")
        shop = p["name"] or branch
        where = _WHERE[lang].format(area=p["area"]) if p["area"] else ""
        want = []
        today = trust.today()
        fests = [f for f in catalog.list_festivals() if today.isoformat() <= f["date"] <= (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat()]
        if fests:
            f = fests[0]
            want.append(("offer", _OFFER[lang].format(festival=f["name"], date=f["date"], shop=shop, where=where),
                         {"source": "festival calendar", "festival": f["name"], "date": f["date"], "uses": ["shop name", "area"], "invented": "nothing: no price or discount is stated"}))
        if p["tagline"]:
            names = p["product_names"] if p["show_products"] else []
            prod = _PRODUCTS[lang].format(names=", ".join(names)) if names else ""
            want.append(("about", _ABOUT[lang].format(shop=shop, where=where, tagline=p["tagline"], products=prod),
                         {"source": "your profile", "uses": ["shop name", "area", "tagline"] + (["products you chose to show"] if names else []), "invented": "nothing"}))
        pk = valid_proof(c, branch, p["proof_id"]) if p["show_trust"] else None
        if pk and pk["claims"]:
            sents = " ".join(claim_sentence(cl, lang) for cl in pk["claims"] if cl["id"] in _CLAIM)
            want.append(("trust_line", _TRUST_HEAD[lang] + sents,
                         {"source": "your signed proof", "proof_id": pk["id"], "valid_until": pk["valid_until"], "uses": ["band-level claims only"], "invented": "nothing"}))
        for kind, text, why in want:
            if c.execute("SELECT 1 FROM presence_drafts WHERE branch=? AND kind=? AND lang=? AND text=? AND status<>'rejected'", (branch, kind, lang, text)).fetchone():
                continue
            cur = c.execute("INSERT INTO presence_drafts(branch, kind, lang, text, why, created_on) VALUES(?,?,?,?,?,?)",
                            (branch, kind, lang, text, json.dumps(why, ensure_ascii=False), today.isoformat()))
            made.append(cur.lastrowid)
            _log(c, branch, "helper", "drafted", f"{kind} ({lang}) from {why['source']}")
        rows = [c.execute("SELECT * FROM presence_drafts WHERE id=?", (i,)).fetchone() for i in made]
    return [_draft(r) for r in rows]


def _draft(r):
    d = dict(r)
    d["why"] = json.loads(d["why"])
    return d


def list_drafts(branch):
    with db() as c:
        return [_draft(r) for r in c.execute("SELECT * FROM presence_drafts WHERE branch=? ORDER BY id DESC", (branch,))]


def _get(c, branch, did):
    r = c.execute("SELECT * FROM presence_drafts WHERE id=? AND branch=?", (did, branch)).fetchone()
    if r is None:
        raise KeyError(did)
    return r


_MOVES = {"approve": ("draft", "approved"), "publish": ("approved", "published"), "unpublish": ("published", "approved"),
          "reject": (None, "rejected")}


def edit_draft(branch, did, text):
    text = (text or "").strip()
    if not text or len(text) > MAX_TEXT:
        raise PresenceError(f"Text must be 1 to {MAX_TEXT} characters")
    with db() as c:
        r = _get(c, branch, did)
        if r["status"] == "published":
            raise PresenceError("Unpublish it before editing")
        c.execute("UPDATE presence_drafts SET text=?, status='draft' WHERE id=?", (text, did))
        _log(c, branch, "owner", "edited", f"draft {did}")
        return _draft(_get(c, branch, did))


def decide(branch, did, action):
    if action not in _MOVES:
        raise PresenceError("Unknown action")
    need, new = _MOVES[action]
    with db() as c:
        r = _get(c, branch, did)
        if need and r["status"] != need:
            raise PresenceError(f"Only a {need} draft can be {action}d" if action != "unpublish" else "Only a published post can be unpublished")
        pub = trust.today().isoformat() if new == "published" else None
        c.execute("UPDATE presence_drafts SET status=?, published_on=? WHERE id=?", (new, pub, did))
        _log(c, branch, "owner", action, f"draft {did} ({r['kind']}, {r['lang']})")
        return _draft(_get(c, branch, did))


def budget(branch):
    with db() as c:
        cap = _profile_row(c, branch)["budget_cap"]
        spent = c.execute("SELECT COALESCE(SUM(spend),0) s FROM presence_drafts WHERE branch=?", (branch,)).fetchone()["s"]
    return dict(cap=cap, planned=spent, remaining=max(0.0, cap - spent), connected=False,
                note="No ad account is connected, so nothing is bought. Boosts are recorded as planned spend inside your cap.")


def boost(branch, did, amount):
    amount = float(amount)
    if amount <= 0:
        raise PresenceError("Amount must be above zero")
    with db() as c:
        r = _get(c, branch, did)
        if r["status"] != "published":
            raise PresenceError("Only a published post can be boosted")
    b = budget(branch)
    if amount > b["remaining"] + 1e-9:
        raise PresenceError(f"Over your budget cap: ₹{b['remaining']:.0f} left of ₹{b['cap']:.0f}")
    with db() as c:
        c.execute("UPDATE presence_drafts SET spend=spend+? WHERE id=?", (amount, did))
        _log(c, branch, "owner", "boost_planned", f"draft {did}: ₹{amount:.0f} (nothing bought)")
    return budget(branch)


def log(branch, limit=50):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT at, actor, action, detail FROM presence_log WHERE branch=? ORDER BY id DESC LIMIT ?", (branch, limit))]


# ----------------------------------------------------------------------------- the public page
def public_view(slug):
    with db() as c:
        r = c.execute("SELECT * FROM presence_profiles WHERE slug=? AND published=1", (slug,)).fetchone()
        if r is None:
            raise KeyError(slug)
        p = _out(r)
        branch = p["branch"]
        pk = valid_proof(c, branch, p["proof_id"]) if p["show_trust"] else None
        posts = [dict(kind=d["kind"], lang=d["lang"], text=d["text"], published_on=d["published_on"])
                 for d in c.execute("SELECT * FROM presence_drafts WHERE branch=? AND status='published' ORDER BY id DESC LIMIT 20", (branch,))]
    have = {i["name"] for i in catalog.list_items(branch)}
    names = [n for n in p["product_names"] if n in have] if p["show_products"] else []
    ld = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": p["name"] or branch}
    if p["tagline"]:
        ld["description"] = p["tagline"]
    if p["area"]:
        ld["address"] = {"@type": "PostalAddress", "addressLocality": p["area"]}
    if p["hours"]:
        ld["openingHours"] = p["hours"]
    return dict(slug=slug, name=p["name"] or branch, tagline=p["tagline"], about=p["about"], area=p["area"], hours=p["hours"], languages=p["languages"],
                products=names, posts=posts, proof=pk, jsonld=ld,
                provenance="Everything here was chosen and published by the shop owner. Stock levels, customers, debts and cash are never shown.")
