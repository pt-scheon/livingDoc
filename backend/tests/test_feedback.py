"""Feedback: owner -> developer, customer -> owner, privacy of the export."""
from app.config import settings
from app.services import demo_storefront, feedback

Q = {"branch": "Main Store"}


def publish(client):
    client.put("/api/presence", params=Q, json={"tagline": "Fresh", "published": True})
    return client.get("/api/presence", params=Q).json()["profile"]["slug"]


def test_owner_suggestion_flows_to_the_developer_export(client):
    r = client.post("/api/feedback", params=Q, json={"text": "The stock table is hard to read on my phone", "category": "confusing", "screen": "stock"})
    assert r.status_code == 201 and r.json()["status"] == "new"
    fid = r.json()["id"]
    assert client.patch(f"/api/feedback/{fid}", params=Q, json={"status": "planned", "dev_note": "Bigger rows"}).json()["status"] == "planned"
    md = client.get("/api/feedback/export.md", params=Q)
    assert md.status_code == 200 and "hard to read on my phone" in md.text and "Planned (1)" in md.text and "Bigger rows" in md.text


def test_validation(client):
    assert client.post("/api/feedback", params=Q, json={"text": "  "}).status_code == 400
    assert client.post("/api/feedback", params=Q, json={"text": "x", "category": "rant"}).status_code == 400
    assert client.patch("/api/feedback/999", params=Q, json={"status": "done"}).status_code == 404
    fid = client.post("/api/feedback", params=Q, json={"text": "ok"}).json()["id"]
    assert client.patch(f"/api/feedback/{fid}", params=Q, json={"status": "bogus"}).status_code == 400


def test_customers_can_comment_only_on_a_published_page_and_it_stays_private_to_the_owner(client):
    s = client.get("/api/presence", params=Q).json()["profile"]["slug"]
    assert client.post(f"/api/presence/public/{s}/feedback", json={"rating": 5, "text": "Great"}).status_code == 404
    s = publish(client)
    r = client.post(f"/api/presence/public/{s}/feedback", json={"rating": 5, "text": "Lovely mithai", "name": "Meera", "contact": "meera@example.com"})
    assert r.status_code == 201
    client.post(f"/api/presence/public/{s}/feedback", json={"rating": 3})
    inbox = client.get("/api/feedback", params={**Q, "source": "customer"}).json()
    assert inbox["summary"]["customer_total"] == 2 and inbox["summary"]["average_rating"] == 4.0
    assert any(i["contact"] == "meera@example.com" for i in inbox["items"])
    # nothing a customer wrote reaches the developer export or the public page
    md = client.get("/api/feedback/export.md", params=Q).text
    assert "Lovely mithai" not in md and "Meera" not in md and "meera@example.com" not in md and "average rating 4.0" in md
    assert "Lovely mithai" not in client.get(f"/api/presence/public/{s}").text


def test_honeypot_and_rate_limit(client):
    s = publish(client)
    client.post(f"/api/presence/public/{s}/feedback", json={"rating": 5, "website": "http://spam"})
    assert client.get("/api/feedback", params=Q).json()["summary"]["customer_total"] == 0
    feedback._HITS.clear()
    codes = [client.post(f"/api/presence/public/{s}/feedback", json={"rating": 4, "text": f"n{i}"}).status_code for i in range(10)]
    assert codes.count(429) == 2 and codes.count(201) == 8
    feedback._HITS.clear()


def test_public_comment_works_with_a_password_but_the_inbox_does_not(client, monkeypatch):
    s = publish(client)
    monkeypatch.setattr(settings, "admin_password", "pw")
    assert client.post(f"/api/presence/public/{s}/feedback", json={"rating": 5}).status_code == 201
    assert client.get("/api/feedback").status_code == 401
    assert client.post("/api/feedback", json={"text": "x"}).status_code == 401
    assert client.get("/api/feedback/export.md").status_code == 401
    feedback._HITS.clear()
