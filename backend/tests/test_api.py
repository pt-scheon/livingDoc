from concurrent.futures import ThreadPoolExecutor

B = "Main Store"


def doc(client, **kw):
    return client.get("/api/document", params={"branch": B, **kw}).json()


def stock(client, name, branch=B):
    return next(i for i in client.get("/api/items", params={"branch": branch}).json()["items"] if i["name"] == name)["qty"]


def test_health_config_branches(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    cfg = client.get("/api/config").json()
    assert set(cfg["languages"]) == {"en", "hi", "gu"} and cfg["llm"]["mode"] in ("llm", "rules")
    assert B in client.get("/api/branches").json()["branches"]


def test_document_and_markdown_and_unknown_branch(client):
    d = doc(client)
    assert len(d["inventory"]) >= 8 and d["cash"]["debts"] and d["forecast"]
    assert doc(client, lang="hi")["lang"] == "hi"
    assert doc(client, lang="xx")["lang"] == "en"  # unsupported language falls back
    md = client.get("/api/document.md", params={"branch": B})
    assert md.status_code == 200 and "Current Inventory" in md.text and md.headers["content-type"].startswith("text/markdown")
    assert client.get("/api/document", params={"branch": "Nope"}).status_code == 404


def test_notes_flow_and_errors(client):
    r = client.post("/api/notes", json={"branch": B, "text": "Sold 4 milks, Dave paid Rs 500 cash, remind me to order beans"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["deltas"]["inventory_deltas"]
    assert any(p["task"].startswith("order beans") for p in doc(client)["promises"])
    assert client.post("/api/notes", json={"branch": B, "text": "Sold 4 milks, Dave paid Rs 500 cash, remind me to order beans"}).status_code == 409
    assert client.post("/api/notes", json={"branch": B, "text": ""}).status_code == 422
    assert client.post("/api/notes", json={"branch": B, "text": "x" * 5001}).status_code == 422
    assert client.post("/api/notes", json={"branch": "Nope", "text": "hi"}).status_code == 404
    notes = client.get("/api/notes", params={"branch": B}).json()["notes"]
    assert notes and notes[0]["deltas"]


def test_items_upsert_count_and_validation(client):
    r = client.put("/api/items", json={"branch": B, "name": "Cardamom", "unit": "kg", "min_stock": 2, "counted": 5})
    assert r.status_code == 200 and r.json()["item"]["qty"] == 5 and r.json()["created"] is True
    r = client.put("/api/items", json={"branch": B, "name": "cardamom", "counted": 3})  # fuzzy match, not a duplicate item
    assert r.json()["created"] is False and r.json()["correction"] == -2 and stock(client, "Cardamom") == 3
    assert client.put("/api/items", json={"branch": B, "name": "X", "min_stock": -1}).status_code == 422
    assert client.get("/api/audit").json()["ok"] is True


def test_scanner_endpoint_is_loose_and_idempotent(client):
    g0 = stock(client, "Ghee")
    batch = {"branch": B, "events": [
        {"event_id": "a1", "sku": "ITM-GHEE", "qty": 2, "direction": "out"},
        {"event_id": "a1", "sku": "ITM-GHEE", "qty": 2, "direction": "out"},
        {"sku": "ITM-GHEE", "qty": -5, "direction": "out"},
        {"qty": 1, "direction": "in"},
        "garbage"]}
    r = client.post("/api/scanner/events", json=batch)
    assert r.status_code == 200 and r.json() == {"applied": 1, "duplicate": 1, "skipped": 3}
    assert stock(client, "Ghee") == g0 - 2
    assert client.post("/api/scanner/events", json={"events": []}).status_code == 422


def test_parallel_scans_keep_stock_consistent(client):
    start = stock(client, "Flour")
    def one(i):
        return client.post("/api/scanner/events", json={"branch": B, "events": [{"event_id": f"p{i}", "item": "Flour", "qty": 1, "direction": "out"}]}).json()["applied"]
    with ThreadPoolExecutor(8) as ex:
        assert sum(ex.map(one, range(40))) == 40
    assert stock(client, "Flour") == start - 40
    assert client.get("/api/audit").json()["ok"] is True


def test_promise_and_risk_actions(client):
    d = doc(client)
    pid = next(p["id"] for p in d["promises"] if not p["done"])
    assert client.patch(f"/api/promises/{pid}", json={"done": True}).status_code == 200
    assert next(p for p in doc(client)["promises"] if p["id"] == pid)["done"] is True
    assert client.patch("/api/promises/99999", json={"done": True}).status_code == 404
    rid = next(r["id"] for r in d["risks"] if r["kind"] == "noted")
    assert client.post(f"/api/risks/{rid}/resolve").status_code == 200
    assert all(r["id"] != rid for r in doc(client)["risks"])
    assert client.post("/api/risks/99999/resolve").status_code == 404


def test_festivals_and_lead_time_change_forecast(client):
    before = {r["item"]: r["must_order_by"] for r in doc(client)["forecast"]}
    assert client.post("/api/festivals", json={"name": "Holi", "date": "2027-03-04", "surge_multiplier": 2, "supplier_blackout_days": 2}).status_code == 201
    assert client.post("/api/festivals", json={"name": "Bad", "date": "2027-03-04", "surge_multiplier": 0.5, "supplier_blackout_days": 2}).status_code == 422
    assert client.put("/api/settings/lead-days", json={"days": 10}).status_code == 200
    after = {r["item"]: r["must_order_by"] for r in doc(client)["forecast"]}
    assert any(after[k] < before[k] for k in before if k in after)  # longer lead time => earlier deadline
    assert client.delete("/api/festivals", params={"name": "Holi", "date": "2027-03-04"}).status_code == 200
    assert client.delete("/api/festivals", params={"name": "Holi", "date": "2027-03-04"}).status_code == 404


def test_sync_endpoints(client):
    client.post("/api/scanner/events", json={"branch": B, "events": [{"event_id": "z1", "item": "Ghee", "qty": 1, "direction": "out"}]})
    assert client.get("/api/sync/status").json()["pending_movements"] >= 1
    r = client.post("/api/sync")
    assert r.status_code == 200 and r.json()["pushed"] >= 1
    assert client.get("/api/sync/status").json()["pending_movements"] == 0


def test_openapi_lists_the_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/document", "/api/notes", "/api/scanner/events", "/api/sync", "/api/festivals"):
        assert p in paths
