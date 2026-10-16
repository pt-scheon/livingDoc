"""Trust ledger, counterparty links, promise->cashflow predictor, proof without exposure."""
import json
from datetime import date, timedelta

import pytest

from app.database import db
from app.services import cashflow, proofs, trust

B = "Main Store"
Q = {"branch": B}


def d(off: int) -> str:
    return (date.today() + timedelta(days=off)).isoformat()


def add(client, kind="owed_to_us", who="Asha Stores", amount=1000, due=None, role="customer", proof=False, desc=""):
    r = client.post("/api/trust/entries", params=Q, json=dict(kind=kind, counterparty=who, amount=amount, due_on=due, role=role, proof_owner=proof, description=desc))
    assert r.status_code == 201, r.text
    return r.json()


def ledger(client):
    return client.get("/api/trust/ledger", params=Q).json()


def set_status(client, eid, status):
    r = client.post(f"/api/trust/entries/{eid}/resolve", params=Q, json={"status": status})
    assert r.status_code == 200, r.text
    return r.json()


def backdate(eid, created=None, due=None, resolved=None):
    with db() as c:
        if created:
            c.execute("UPDATE trust_entries SET created_on=? WHERE id=?", (created, eid))
        if due:
            c.execute("UPDATE trust_entries SET due_on=? WHERE id=?", (due, eid))
        if resolved:
            c.execute("UPDATE trust_entries SET resolved_on=? WHERE id=?", (resolved, eid))


# ------------------------------------------------------------------ ledger
def test_core_debts_and_promises_are_mirrored_privately(client):
    L = ledger(client)
    ents = L["entries"]
    assert {e["counterparty"] for e in ents} >= {"Dave", "Priya", "Mehta Catering"}
    debts = [e for e in ents if e["kind"] == "owed_to_us"]
    assert debts and all(e["derived"] and e["proof_owner"] == 0 and e["counts_in_proofs"] is False for e in ents)
    assert L["summary"]["in_proofs"] == 0 and L["summary"]["receivable"] == pytest.approx(sum(e["open_amount"] for e in debts))
    assert "salt" not in json.dumps(L)                        # commitment salts never leave the server through the ledger
    assert not any(e["counterparty"].lower() == "me" for e in ents)


def test_crud_and_validation(client):
    e = add(client, desc="wedding sweets", due=d(10))
    assert e["amount"] == 1000 and e["status"] == "open" and e["due_effective"] == d(10)
    bad = lambda **kw: client.post("/api/trust/entries", params=Q, json={"kind": "owed_to_us", "counterparty": "X", "amount": 5, **kw}).status_code
    assert bad(kind="loan") == 400 and bad(role="king") == 400 and bad(counterparty="  ") in (400, 422)
    assert bad(amount=None) == 400                                          # a money promise needs an amount
    assert client.post("/api/trust/entries", params=Q, json=dict(kind="owed_to_us", counterparty="X", amount=-1)).status_code == 422
    assert bad(due_on="31/12/2026") == 422
    p = client.patch(f"/api/trust/entries/{e['id']}", params=Q, json={"amount": 1200, "proof_owner": True})
    assert p.status_code == 200 and p.json()["amount"] == 1200 and p.json()["proof_owner"] == 1
    assert client.delete(f"/api/trust/entries/{e['id']}", params=Q).status_code == 200
    assert client.delete(f"/api/trust/entries/{e['id']}", params=Q).status_code == 404
    fav = add(client, kind="favour_given", who="Neighbour Raju", amount=None, role="neighbour", desc="lent the van")
    assert fav["amount"] is None and fav["open_amount"] == 0


def test_derived_entries_follow_their_source(client):
    debt = next(e for e in ledger(client)["entries"] if e["counterparty"] == "Dave" and e["kind"] == "owed_to_us")
    assert client.patch(f"/api/trust/entries/{debt['id']}", params=Q, json={"amount": 1}).status_code == 400
    assert client.delete(f"/api/trust/entries/{debt['id']}", params=Q).status_code == 400
    assert client.post(f"/api/trust/entries/{debt['id']}/resolve", params=Q, json={"status": "kept"}).status_code == 400   # pay via notes
    client.post("/api/notes", json={"branch": B, "text": "Dave paid Rs 1200 cash"})
    again = next(e for e in ledger(client)["entries"] if e["id"] == debt["id"])
    assert again["status"] == "kept" and again["open_amount"] == 0 and again["resolved_on"]


def test_two_views_of_the_same_promise_are_kept_not_merged(client):
    e = add(client, amount=1000)
    link = client.post("/api/trust/parties/link", params=Q, json={"name": "Asha Stores"}).json()
    tok = link["token"]
    assert link["path"].endswith(tok)
    r = client.post(f"/api/trust/party/{tok}/entries/{e['id']}", json={"cp_amount": 600, "cp_note": "I paid 400 in cash last week"})
    assert r.status_code == 200
    mine = next(x for x in ledger(client)["entries"] if x["id"] == e["id"])
    assert mine["amount"] == 1000 and mine["cp_amount"] == 600 and mine["disputed_effective"] is True
    assert (mine["worth_low"], mine["worth_high"]) == (600, 1000)
    assert mine["conservative_amount"] == 600                  # outsiders may only rely on the LOWER figure for money owed to us
    assert mine["cp_note"].startswith("I paid")
    owe = add(client, kind="we_owe", who="Ramesh", amount=900, role="supplier")
    t2 = client.post("/api/trust/parties/link", params=Q, json={"name": "Ramesh"}).json()["token"]
    client.post(f"/api/trust/party/{t2}/entries/{owe['id']}", json={"cp_amount": 1100})
    assert next(x for x in ledger(client)["entries"] if x["id"] == owe["id"])["conservative_amount"] == 1100   # the HIGHER figure for what we owe


def test_counterparty_sees_only_their_own_records_and_score(client):
    a = add(client, who="Asha Stores", amount=500)
    add(client, who="Bhavin Traders", amount=777, desc="secret private thing")
    tok = client.post("/api/trust/parties/link", params=Q, json={"name": "asha stores"}).json()["token"]      # case-insensitive match
    v = client.get(f"/api/trust/party/{tok}").json()
    assert v["name"] == "Asha Stores" and [x["id"] for x in v["entries"]] == [a["id"]]
    assert "Bhavin" not in json.dumps(v) and "777" not in json.dumps(v) and v["score"]["prior"] == trust.PRIOR_P
    other = add(client, who="Bhavin Traders", amount=1)
    assert client.post(f"/api/trust/party/{tok}/entries/{other['id']}", json={"disputed": True}).status_code == 404   # cannot touch anyone else's
    assert client.get("/api/trust/party/not-a-token").status_code == 404
    assert client.post("/api/trust/parties/link", params=Q, json={"name": "Nobody Here"}).status_code == 404
    assert client.delete("/api/trust/parties/link", params={**Q, "name": "Asha Stores"}).json()["revoked"] == 1
    assert client.get(f"/api/trust/party/{tok}").status_code == 404                                    # revoked link stops working


def test_reliability_score_is_explainable_and_cautious():
    mk = lambda st, due=None, res=None: dict(counterparty="Z", status=st, due_on=due, resolved_on=res, amount=10, settled=0)
    one = trust.party_scores([mk("kept", "2026-01-10", "2026-01-10")])["z"]
    assert one["score"] == pytest.approx((1 + 0.8 * 2) / 3, abs=1e-3) and one["label"] == "reliable"          # one data point never decides
    mixed = trust.party_scores([mk("kept", "2026-01-10", "2026-01-10"), mk("kept", "2026-01-10", "2026-01-20"), mk("broken")])["z"]
    assert mixed["score"] == pytest.approx((1 + 0.6 + 1.6) / 5, abs=1e-3) and mixed["avg_delay_days"] == 5.0
    assert trust.party_scores([mk("open"), mk("forgiven")])["z"]["label"] == "new"                   # forgiven and open do not move the score
    shaky = trust.party_scores([mk("broken")] * 4)["z"]
    assert shaky["label"] == "shaky" and shaky["score"] < 0.35


# ------------------------------------------------------------------ cash-flow predictor
def cf(client, **kw):
    r = client.get("/api/cashflow/promises", params={**Q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def clean(client):
    """Ledger with only entries made by the test (drop the seeded debts)."""
    ledger(client)
    with db() as c:
        c.execute("DELETE FROM trust_entries")
        c.execute("UPDATE cash_events SET settled=amount WHERE type='owed'")
        c.execute("DELETE FROM promises")
    return client


def test_cashflow_is_deterministic_and_bounded(clean):
    add(clean, amount=1000, due=d(5))
    a, b = cf(clean, horizon=30), cf(clean, horizon=30)
    assert a == b                                              # same ledger, same answer
    assert len(a["days"]) == 30 and a["days"][0]["date"] == d(0)
    s = a["summary"]
    assert 0 < s["expected_in"] <= 1000 and s["at_risk"] == pytest.approx(1000 - s["expected_in"], abs=0.01)
    assert all(x["net_p10"] <= x["net_p50"] <= x["net_p90"] for x in a["days"])
    assert all(a["days"][i]["net_p90"] <= a["days"][i + 1]["net_p90"] + 1e-9 for i in range(29))     # no outflows: cumulative never falls
    assert a["items"][0]["amount"] == 1000 and "no_history" in a["items"][0]["flags"] and a["assumptions"]["prior_reliability"] == 0.8


def test_broken_history_lowers_expected_cash(clean):
    add(clean, who="Good Payer", amount=1000, due=d(3))
    add(clean, who="Bad Payer", amount=1000, due=d(3))
    for who, status, n in (("Good Payer", "kept", 6), ("Bad Payer", "broken", 6)):
        for _ in range(n):
            e = add(clean, who=who, amount=10, due=d(-30))
            set_status(clean, e["id"], status)
            backdate(e["id"], resolved=d(-30) if status == "kept" else None)
    items = {i["counterparty"]: i for i in cf(clean, horizon=60)["items"] if i["amount"] == 1000}
    assert items["Good Payer"]["p_kept"] > 0.85 > 0.4 > items["Bad Payer"]["p_kept"]
    assert items["Good Payer"]["p_in_window"] > items["Bad Payer"]["p_in_window"]


def test_overdue_and_disputed_money_is_discounted_and_flagged(clean):
    fresh = add(clean, who="A", amount=1000, due=d(2))
    old = add(clean, who="B", amount=1000, due=d(-90))
    disp = add(clean, who="C", amount=1000, due=d(2))
    tok = clean.post("/api/trust/parties/link", params=Q, json={"name": "C"}).json()["token"]
    clean.post(f"/api/trust/party/{tok}/entries/{disp['id']}", json={"disputed": True, "cp_amount": 700})
    it = {i["counterparty"]: i for i in cf(clean)["items"]}
    assert it["B"]["overdue_days"] >= 90 and "overdue" in it["B"]["flags"] and it["B"]["p_kept"] < it["A"]["p_kept"] * 0.6
    assert "disputed" in it["C"]["flags"] and it["C"]["amount"] == 700 and "lower_figure_used" in it["C"]["flags"]
    codes = {w["code"] for w in cf(clean)["warnings"]}
    assert {"overdue_inflows", "disputed_inflows"} <= codes
    _ = fresh, old


def test_payables_are_certain_outflows_and_shortfall_is_called_out(clean):
    add(clean, kind="we_owe", who="Supplier", amount=5000, due=d(4), role="supplier")
    add(clean, who="Customer", amount=3000, due=d(6))
    r = cf(clean, horizon=30, opening_cash=1000)
    assert r["summary"]["committed_out"] == 5000
    day4 = r["days"][4]
    assert day4["out_expected"] == 5000 and day4["p_negative"] > 0.9
    assert r["summary"]["first_shortfall"] is not None and any(w["code"] == "shortfall" for w in r["warnings"])
    assert cf(clean, horizon=30)["summary"]["first_shortfall"] is None           # no opening cash given: no verdict, no guess
    rich = cf(clean, horizon=30, opening_cash=100000)
    assert rich["summary"]["first_shortfall"] is None


def test_favours_carry_no_cash_and_concentration_is_flagged(clean):
    add(clean, kind="favour_given", who="Raju", amount=5000, role="neighbour")
    add(clean, who="Big", amount=9000, due=d(3))
    add(clean, who="Small", amount=500, due=d(3))
    r = cf(clean)
    assert {i["counterparty"] for i in r["items"]} == {"Big", "Small"}
    w = next(w for w in r["warnings"] if w["code"] == "concentration")
    assert w["who"] == "Big" and w["share"] > 0.8


def test_cashflow_can_add_the_sales_forecast_and_degrades_gracefully(clean):
    add(clean, amount=1000, due=d(3))
    r = cf(clean, horizon=14, include_sales=True)
    assert sum(x["sales_expected"] for x in r["days"]) > 0 and "average bill" in r["assumptions"]["sales"]
    assert cf(clean, horizon=14)["days"][0]["sales_expected"] == 0
    assert client_status(clean, horizon=3) == 422


def client_status(client, **kw):
    return client.get("/api/cashflow/promises", params={**Q, **kw}).status_code


# ------------------------------------------------------------------ proofs
def opted(client, **kw):
    return add(client, proof=True, **kw)


def test_nothing_is_counted_unless_both_sides_allow_it(clean):
    a = opted(clean, who="Asha", amount=2400, due=d(5))
    b = add(clean, who="Private Pat", amount=9000, due=d(5), proof=False)          # owner did not opt in
    c = opted(clean, who="Vetoing Vik", amount=7000, due=d(5))
    tok = clean.post("/api/trust/parties/link", params=Q, json={"name": "Vetoing Vik"}).json()["token"]
    clean.post(f"/api/trust/party/{tok}/entries/{c['id']}", json={"proof_consent": False})   # counterparty vetoes
    pv = clean.get("/api/proofs/preview", params=Q).json()
    assert pv["consenting"] == 1 and pv["excluded"] >= 2
    why = {x["id"]: x["why"] for x in pv["excluded_entries"]}
    assert why[b["id"]] == "owner_not_opted_in" and why[c["id"]] == "counterparty_withheld"
    assert next(x for x in pv["claims"] if x["id"] == "receivable_floor")["value"] == 2000          # 2,400 -> band 2,000: only the owner-and-counterparty-approved entry
    clean.post(f"/api/trust/party/{tok}/entries/{c['id']}", json={"proof_consent": True})
    assert clean.get("/api/proofs/preview", params=Q).json()["consenting"] == 2             # veto can be lifted
    _ = a


def test_packet_reveals_bands_not_people(clean):
    secret_name, secret_desc = "Zubin Dalal", "his daughter's hospital bill"
    opted(clean, who=secret_name, amount=3170, due=d(9), desc=secret_desc)
    opted(clean, who="Meena Shah", amount=1930, due=d(2))
    r = clean.post("/api/proofs", params=Q, json={"valid_days": 7})
    assert r.status_code == 201
    j = r.json()
    blob = json.dumps(j["packet"])
    for leak in (secret_name, "Zubin", "Dalal", "Meena", secret_desc, "3170", "1930", "5100"):
        assert leak not in blob, leak
    claims = {c["id"]: c for c in j["packet"]["claims"]}
    assert claims["receivable_floor"]["value"] == 5000 and claims["receivable_floor"]["op"] == ">="        # true total 5,000 -> exact band, never the amount
    assert claims["parties_floor"]["value"] == 2 and claims["max_overdue"]["value"] == 0
    assert j["packet"]["entries_counted"] == 2 and "zero-knowledge" in j["packet"]["scope_note"]
    assert j["open_key"] and "open_key" not in blob


def test_bands_hide_the_exact_figure():
    assert [proofs.floor_band(x) for x in (0.5, 1, 1.9, 2, 4999, 5000, 7300, 99999, 100000)] == [0, 1, 1, 2, 2000, 5000, 5000, 50000, 100000]
    assert [proofs.ceil_band(x) for x in (0, 1, 3, 5.1, 7300, 100001)] == [0, 1, 5, 10, 10000, 200000]


def test_signature_verifies_and_any_tampering_breaks_it(clean):
    opted(clean, amount=2500, due=d(5))
    p = clean.post("/api/proofs", params=Q, json={}).json()["packet"]
    ok = clean.post("/api/proofs/verify", json=p).json()
    assert ok["signature_valid"] and ok["valid"] and ok["issued_by_this_shop"] and ok["revoked"] is False and ok["expired"] is False
    for mutate in (lambda q: q["claims"][0].update(value=q["claims"][0]["value"] * 100), lambda q: q.update(entries_counted=99),
                   lambda q: q.update(merkle_root="0" * 64), lambda q: q.update(valid_until="2099-01-01")):
        t = json.loads(json.dumps(p))
        mutate(t)
        res = clean.post("/api/proofs/verify", json=t).json()
        assert res["signature_valid"] is False and res["claims"] == []
    other = json.loads(json.dumps(p))
    other["public_key"] = proofs.Ed25519PrivateKey.generate().public_key().public_bytes(
        proofs.serialization.Encoding.Raw, proofs.serialization.PublicFormat.Raw).hex()
    assert clean.post("/api/proofs/verify", json=other).json()["signature_valid"] is False
    assert clean.post("/api/proofs/verify", json={"junk": 1}).json()["signature_valid"] is False


def test_expiry_and_revocation(clean, monkeypatch):
    opted(clean, amount=2500, due=d(5))
    j = clean.post("/api/proofs", params=Q, json={"valid_days": 1}).json()
    pid, packet = j["packet"]["id"], j["packet"]
    assert clean.get(f"/api/proofs/{pid}").json()["packet"] == packet
    assert clean.post(f"/api/proofs/{pid}/revoke", params=Q).status_code == 200
    v = clean.post("/api/proofs/verify", json=packet).json()
    assert v["signature_valid"] and v["revoked"] is True and v["valid"] is False
    assert clean.post(f"/api/proofs/{pid}/open", json={"open_key": j["open_key"], "nonce": "random-nonce-1"}).status_code == 400
    j2 = clean.post("/api/proofs", params=Q, json={"valid_days": 1}).json()
    monkeypatch.setattr(trust, "today", lambda: date.today() + timedelta(days=3))
    v2 = clean.post("/api/proofs/verify", json=j2["packet"]).json()
    assert v2["expired"] is True and v2["valid"] is False and v2["signature_valid"] is True
    assert clean.post("/api/proofs/ffff/revoke", params=Q).status_code == 404


def test_issue_validation(clean):
    assert clean.post("/api/proofs", params=Q, json={}).status_code == 400                  # nothing opted in
    opted(clean, amount=2500, due=d(5))
    assert clean.post("/api/proofs", params=Q, json={"valid_days": 0}).status_code == 422
    assert clean.post("/api/proofs", params=Q, json={"claims": ["bogus"]}).status_code == 400
    assert clean.post("/api/proofs", params=Q, json={"claims": ["kept_rate_floor"]}).status_code == 400    # too few resolved: refused, not faked
    r = clean.post("/api/proofs", params=Q, json={"claims": ["receivable_floor"]}).json()
    assert [c["id"] for c in r["packet"]["claims"]] == ["receivable_floor"]                  # owner chooses what to say
    assert any(w["id"] == "kept_rate_floor" for w in r["withheld"])


def test_kept_rate_needs_enough_resolved_promises(clean):
    for st in ("kept", "kept", "kept", "kept", "broken"):
        e = opted(clean, who=f"P{st}{id(st)}{date.today().toordinal() % 7}", amount=100, due=d(-5))
        set_status(clean, e["id"], st)
    claims = {c["id"]: c for c in clean.get("/api/proofs/preview", params=Q).json()["claims"]}
    assert claims["kept_rate_floor"]["value"] == 0.8


def test_overdue_claim_is_honest(clean):
    opted(clean, who="Late One", amount=2500, due=d(-20))
    claims = {c["id"]: c for c in clean.get("/api/proofs/preview", params=Q).json()["claims"]}
    assert claims["max_overdue"]["value"] == 30                                             # 20 days late -> the next band up, never understated


def test_spot_check_openings_are_unforgeable_and_gated(clean):
    for i in range(7):
        opted(clean, who=f"Customer {i}", amount=1000 + i * 100, due=d(3 + i))
    j = clean.post("/api/proofs", params=Q, json={}).json()
    packet, key, pid = j["packet"], j["open_key"], j["packet"]["id"]
    assert clean.post(f"/api/proofs/{pid}/open", json={"open_key": "wrong-key", "nonce": "random-nonce-1"}).status_code == 403
    assert clean.post(f"/api/proofs/{pid}/open", json={"open_key": key, "nonce": "short"}).status_code == 422
    r = clean.post(f"/api/proofs/{pid}/open", json={"open_key": key, "nonce": "verifier-nonce-A"}).json()
    assert len(r["openings"]) == 3 and r["indices"] == proofs.challenge_indices(packet["merkle_root"], "verifier-nonce-A", 7)
    assert all(not any(f"Customer {i}" in json.dumps(o) for i in range(7)) for o in r["openings"])      # names are pseudonyms
    chk = clean.post("/api/proofs/check-openings", json={"packet": packet, "nonce": "verifier-nonce-A", "openings": r["openings"]}).json()
    assert chk["ok"] and chk["indices_as_challenged"] and all(c["in_tree"] and c["consistent_with_claims"] for c in chk["checks"])
    # the shop answering a different challenge (cherry-picking) is caught
    r2 = clean.post(f"/api/proofs/{pid}/open", json={"open_key": key, "nonce": "verifier-nonce-B"}).json()
    assert r2["indices"] != r["indices"]
    swapped = clean.post("/api/proofs/check-openings", json={"packet": packet, "nonce": "verifier-nonce-A", "openings": r2["openings"]}).json()
    assert swapped["ok"] is False and swapped["indices_as_challenged"] is False
    # editing a revealed entry after the fact breaks the commitment
    forged = json.loads(json.dumps(r["openings"]))
    forged[0]["data"]["amount"] = 999999
    bad = clean.post("/api/proofs/check-openings", json={"packet": packet, "nonce": "verifier-nonce-A", "openings": forged}).json()
    assert bad["ok"] is False and bad["checks"][0]["leaf_matches_data"] is False
    # a tampered packet fails before anything else
    t = json.loads(json.dumps(packet)); t["entries_counted"] = 3
    assert clean.post("/api/proofs/check-openings", json={"packet": t, "nonce": "verifier-nonce-A", "openings": r["openings"]}).json()["reason"] == "bad_signature"


def test_merkle_tree_roundtrip():
    for n in (1, 2, 3, 5, 8, 13):
        leaves = [proofs.sha(f"leaf{i}") for i in range(n)]
        root = proofs.merkle_root(leaves)
        s = sorted(leaves)
        assert all(proofs.verify_path(s[i], proofs.merkle_path(s, i), root) for i in range(n))
        assert not proofs.verify_path(proofs.sha("other"), proofs.merkle_path(s, 0), root)
    assert proofs.merkle_root([proofs.sha("a"), proofs.sha("b")]) == proofs.merkle_root([proofs.sha("b"), proofs.sha("a")])   # order leaks nothing


def test_public_listing_never_contains_secrets(clean):
    opted(clean, amount=2500, due=d(5))
    j = clean.post("/api/proofs", params=Q, json={}).json()
    listing = json.dumps(clean.get("/api/proofs", params=Q).json())
    assert j["open_key"] not in listing and "salt" not in listing and "leaves" not in listing
    assert j["packet"]["id"] in listing
    assert clean.get(f"/api/proofs/{j['packet']['id']}").status_code == 200
    assert clean.get("/api/proofs/nope").status_code == 404


def test_offline_verifier_script(clean, tmp_path):
    import subprocess, sys
    from pathlib import Path
    opted(clean, amount=2500, due=d(5))
    p = clean.post("/api/proofs", params=Q, json={}).json()["packet"]
    f = tmp_path / "p.json"
    f.write_text(json.dumps(p))
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_proof.py"
    ok = subprocess.run([sys.executable, str(script), str(f)], capture_output=True, text=True)
    assert ok.returncode == 0 and "SIGNATURE VALID" in ok.stdout
    p["claims"][0]["value"] = 10 ** 9
    f.write_text(json.dumps(p))
    bad = subprocess.run([sys.executable, str(script), str(f)], capture_output=True, text=True)
    assert bad.returncode == 1 and "SIGNATURE INVALID" in bad.stdout


def test_openapi_lists_trust_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/trust/ledger", "/api/trust/entries", "/api/cashflow/promises", "/api/proofs", "/api/proofs/verify", "/api/proofs/{pid}/open"):
        assert p in paths
    assert cashflow.SIMS >= 1000


def test_packet_verifies_after_javascript_style_number_round_trip(client, clean):
    """Browsers print 5000.0 as 5000; the signature must not depend on that."""
    import json
    client.post("/api/trust/entries", json={"kind": "owed_to_us", "counterparty": "Zed", "amount": 5000, "proof_owner": True})
    packet = client.post("/api/proofs", json={}).json()["packet"]
    raw = json.dumps(packet).replace(".0,", ",").replace(".0}", "}")
    assert client.post("/api/proofs/verify", json=json.loads(raw)).json()["valid"] is True
