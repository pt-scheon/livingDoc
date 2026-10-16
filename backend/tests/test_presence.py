"""Find & trust: owner-controlled public page, drafting helper that cannot act alone, budget cap, audit log."""
import json
from datetime import date, timedelta

from app.database import db

B = "Main Store"
Q = {"branch": B}


def put(client, **f):
    r = client.put("/api/presence", params=Q, json=f)
    assert r.status_code == 200, r.text
    return r.json()["profile"]


def slug(client):
    return client.get("/api/presence", params=Q).json()["profile"]["slug"]


def test_nothing_is_public_until_the_owner_publishes(client):
    s = slug(client)
    assert client.get(f"/api/presence/public/{s}").status_code == 404
    put(client, tagline="Fresh milk and spices", published=True)
    r = client.get(f"/api/presence/public/{s}")
    assert r.status_code == 200 and r.json()["tagline"] == "Fresh milk and spices"
    put(client, published=False)
    assert client.get(f"/api/presence/public/{s}").status_code == 404


def test_every_field_is_private_until_ticked_and_nothing_internal_leaks(client):
    s = slug(client)
    items = client.get("/api/presence", params=Q).json()["items"]
    put(client, published=True, product_names=items[:2])
    pub = client.get(f"/api/presence/public/{s}").json()
    assert pub["products"] == []                      # names chosen but show_products not ticked
    put(client, show_products=True)
    pub = client.get(f"/api/presence/public/{s}").json()
    assert pub["products"] == items[:2]
    blob = json.dumps({k: v for k, v in pub.items() if k != "provenance"}).lower()
    for secret in ("dave", "priya", "mehta", "qty", "stock", "min_stock", "owed", "debt"):
        assert secret not in blob


def test_product_names_are_limited_to_real_items(client):
    p = put(client, product_names=["Not A Real Item"])
    assert p["product_names"] == []


def test_helper_drafts_only_and_cannot_publish(client):
    put(client, tagline="Neighbourhood grocer", area="Navrangpura")
    r = client.post("/api/presence/suggest", params=Q, json={"lang": "en"})
    assert r.status_code == 201
    drafts = r.json()["drafts"]
    assert drafts and all(d["status"] == "draft" and d["why"]["source"] for d in drafts)
    s = slug(client)
    assert client.get(f"/api/presence/public/{s}").status_code == 404      # still private, nothing went out
    d = drafts[0]
    # publishing needs approval first, and both are owner actions
    assert client.post(f"/api/presence/drafts/{d['id']}/publish", params=Q).status_code == 400
    assert client.post(f"/api/presence/drafts/{d['id']}/approve", params=Q).json()["status"] == "approved"
    assert client.post(f"/api/presence/drafts/{d['id']}/publish", params=Q).json()["status"] == "published"
    put(client, published=True)
    assert any(p["text"] == d["text"] for p in client.get(f"/api/presence/public/{s}").json()["posts"])
    assert client.post(f"/api/presence/drafts/{d['id']}/unpublish", params=Q).json()["status"] == "approved"
    assert not client.get(f"/api/presence/public/{s}").json()["posts"]


def test_drafts_invent_nothing_and_are_deduplicated(client):
    put(client, tagline="Neighbourhood grocer")
    a = client.post("/api/presence/suggest", params=Q, json={"lang": "en"}).json()["drafts"]
    b = client.post("/api/presence/suggest", params=Q, json={"lang": "en"}).json()["drafts"]
    assert a and b == []
    assert all("₹" not in d["text"] and "%" not in d["text"] for d in a if d["kind"] != "trust_line")
    assert all(d["why"]["invented"].startswith("nothing") for d in a)


def test_festival_offer_uses_the_calendar_and_speaks_hindi_and_gujarati(client):
    soon = (date.today() + timedelta(days=10)).isoformat()
    client.post("/api/festivals", json={"name": "Testival", "date": soon, "surge_multiplier": 1.5, "supplier_blackout_days": 0})
    for lang in ("hi", "gu"):
        d = client.post("/api/presence/suggest", params=Q, json={"lang": lang}).json()["drafts"]
        offer = [x for x in d if x["kind"] == "offer"]
        assert offer and "Testival" in offer[0]["text"] and soon in offer[0]["text"]
        assert any(ord(ch) > 0x900 for ch in offer[0]["text"])


def test_switching_the_helper_off_stops_suggestions(client):
    put(client, tagline="x", autonomy="off")
    assert client.post("/api/presence/suggest", params=Q, json={"lang": "en"}).status_code == 400
    assert client.put("/api/presence", params=Q, json={"autonomy": "full"}).status_code == 400


def test_editing_resets_approval_and_published_posts_cannot_be_edited(client):
    put(client, tagline="Grocer")
    d = client.post("/api/presence/suggest", params=Q, json={"lang": "en"}).json()["drafts"][0]
    client.post(f"/api/presence/drafts/{d['id']}/approve", params=Q)
    e = client.patch(f"/api/presence/drafts/{d['id']}", params=Q, json={"text": "My own words"}).json()
    assert e["status"] == "draft" and e["text"] == "My own words"
    client.post(f"/api/presence/drafts/{d['id']}/approve", params=Q); client.post(f"/api/presence/drafts/{d['id']}/publish", params=Q)
    assert client.patch(f"/api/presence/drafts/{d['id']}", params=Q, json={"text": "sneaky"}).status_code == 400


def test_budget_cap_is_enforced_and_honest_about_not_spending(client):
    put(client, tagline="Grocer", budget_cap=500)
    d = client.post("/api/presence/suggest", params=Q, json={"lang": "en"}).json()["drafts"][0]
    assert client.post(f"/api/presence/drafts/{d['id']}/boost", params=Q, json={"amount": 100}).status_code == 400   # not published
    client.post(f"/api/presence/drafts/{d['id']}/approve", params=Q); client.post(f"/api/presence/drafts/{d['id']}/publish", params=Q)
    b = client.post(f"/api/presence/drafts/{d['id']}/boost", params=Q, json={"amount": 300}).json()
    assert b["planned"] == 300 and b["remaining"] == 200 and b["connected"] is False and "nothing is bought" in b["note"].lower()
    assert client.post(f"/api/presence/drafts/{d['id']}/boost", params=Q, json={"amount": 250}).status_code == 400
    assert client.post(f"/api/presence/drafts/{d['id']}/boost", params=Q, json={"amount": -5}).status_code == 422


def test_trust_badges_come_only_from_a_valid_signed_proof(client):
    client.post("/api/trust/entries", params=Q, json=dict(kind="owed_to_us", counterparty="Zed", amount=5000, proof_owner=True))
    pk = client.post("/api/proofs", params=Q, json={}).json()["packet"]
    s = slug(client)
    put(client, published=True, show_trust=True, proof_id=pk["id"])
    pub = client.get(f"/api/presence/public/{s}").json()
    assert pub["proof"]["id"] == pk["id"] and client.post("/api/proofs/verify", json=pub["proof"]).json()["valid"] is True
    assert "zed" not in json.dumps(pub).lower()
    client.post(f"/api/proofs/{pk['id']}/revoke", params=Q)
    assert client.get(f"/api/presence/public/{s}").json()["proof"] is None          # revoked: badge disappears at once
    assert client.put("/api/presence", params=Q, json={"proof_id": "nope"}).status_code == 400


def test_trust_line_draft_translates_claims(client):
    client.post("/api/trust/entries", params=Q, json=dict(kind="owed_to_us", counterparty="Zed", amount=5000, proof_owner=True))
    pk = client.post("/api/proofs", params=Q, json={}).json()["packet"]
    put(client, show_trust=True, proof_id=pk["id"])
    d = client.post("/api/presence/suggest", params=Q, json={"lang": "gu"}).json()["drafts"]
    t = [x for x in d if x["kind"] == "trust_line"]
    assert t and "Zed" not in t[0]["text"] and "₹" in t[0]["text"]


def test_every_action_is_logged_with_who_did_it(client):
    put(client, tagline="Grocer")
    d = client.post("/api/presence/suggest", params=Q, json={"lang": "en"}).json()["drafts"][0]
    client.post(f"/api/presence/drafts/{d['id']}/approve", params=Q)
    log = client.get("/api/presence/log", params=Q).json()["log"]
    acts = [(x["actor"], x["action"]) for x in log]
    assert ("helper", "drafted") in acts and ("owner", "approve") in acts and ("owner", "profile_changed") in acts


def test_public_page_exposes_jsonld_for_search_engines(client):
    put(client, name="Shah Provision", area="Navrangpura", tagline="Spices", hours="Mo-Sa 09:00-21:00", published=True)
    ld = client.get(f"/api/presence/public/{slug(client)}").json()["jsonld"]
    assert ld["@type"] == "LocalBusiness" and ld["name"] == "Shah Provision" and ld["address"]["addressLocality"] == "Navrangpura"


def test_text_limits_and_openapi(client):
    assert client.put("/api/presence", params=Q, json={"tagline": "x" * 500}).status_code == 400
    assert "/api/presence/public/{slug}" in client.get("/openapi.json").json()["paths"]
