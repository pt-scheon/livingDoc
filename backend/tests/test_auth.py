"""Owner login for public hosting: closed by default when a password is set, public routes stay public."""
import pytest

from app import auth
from app.config import settings

B = {"branch": "Main Store"}


@pytest.fixture()
def locked(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "s3cret-pass")
    auth._fails.clear()
    return client


def test_open_mode_when_no_password(client):
    st = client.get("/api/auth/status").json()
    assert st["required"] is False and st["authed"] is True and st["setup"] is True and st["user"] is None
    assert client.get("/api/document", params=B).status_code == 200


def test_private_routes_need_login_when_password_is_set(locked):
    st = locked.get("/api/auth/status").json()
    assert st["required"] is True and st["authed"] is False and st["needs_setup_code"] is True
    for path in ("/api/document", "/api/trust/ledger", "/api/presence", "/api/items", "/api/branches", "/api/config"):
        assert locked.get(path, params=B).status_code == 401, path
    assert locked.post("/api/notes", json={"branch": "Main Store", "text": "sold 1 milk"}).status_code == 401
    assert locked.post("/api/scanner/events", json={"events": []}).status_code == 401


def test_login_sets_session_and_logout_clears_it(locked):
    assert locked.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = locked.post("/api/auth/login", json={"password": "s3cret-pass"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert locked.get("/api/document", params=B).status_code == 200
    assert locked.get("/api/auth/status").json()["authed"] is True
    locked.post("/api/auth/logout")
    locked.cookies.clear()
    assert locked.get("/api/document", params=B).status_code == 401


def test_bearer_token_for_scanners_and_scripts(locked):
    assert locked.get("/api/document", params=B, headers={"Authorization": "Bearer s3cret-pass"}).status_code == 200
    assert locked.get("/api/document", params=B, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_forged_or_expired_session_is_refused(locked, monkeypatch):
    locked.cookies.set(auth.COOKIE, "9999999999.deadbeef")
    assert locked.get("/api/document", params=B).status_code == 401
    monkeypatch.setattr(auth.time, "time", lambda: 1000.0)
    tok = auth.make_token()
    monkeypatch.setattr(auth.time, "time", lambda: 1000.0 + auth.SESSION_SECONDS + 5)
    assert auth.valid_token(tok) is False


def test_session_dies_when_password_changes(locked, monkeypatch):
    tok = auth.make_token()
    monkeypatch.setattr(settings, "admin_password", "another-one")
    assert auth.valid_token(tok) is False


def test_wrong_passwords_are_rate_limited(locked):
    for _ in range(auth.MAX_FAILS):
        assert locked.post("/api/auth/login", json={"password": "bad"}).status_code == 401
    assert locked.post("/api/auth/login", json={"password": "s3cret-pass"}).status_code == 429


def test_routes_meant_for_other_people_stay_public(locked):
    # authenticated owner prepares things, then a stranger (no cookie) uses the public ones
    locked.post("/api/auth/login", json={"password": "s3cret-pass"})
    locked.put("/api/presence", params=B, json={"tagline": "Hi", "published": True})
    slug = locked.get("/api/presence", params=B).json()["profile"]["slug"]
    locked.post("/api/trust/entries", params=B, json=dict(kind="owed_to_us", counterparty="Dave", amount=100))
    link = locked.post("/api/trust/parties/link", params=B, json={"name": "Dave"}).json()
    locked.post("/api/trust/entries", params=B, json=dict(kind="owed_to_us", counterparty="Zed", amount=5000, proof_owner=True))
    pk = locked.post("/api/proofs", params=B, json={}).json()
    locked.cookies.clear()
    assert locked.get(f"/api/presence/public/{slug}").status_code == 200
    assert locked.get(f"/api/trust/party/{link['token']}").status_code == 200
    assert locked.post("/api/proofs/verify", json=pk["packet"]).json()["valid"] is True
    assert locked.get(f"/api/proofs/{pk['packet']['id']}").status_code == 200
    assert locked.get("/api/health").status_code == 200
    # ...but the owner-side proof routes stay closed
    assert locked.post("/api/proofs", params=B, json={}).status_code == 401
    assert locked.get("/api/proofs/preview", params=B).status_code == 401
    assert locked.post(f"/api/proofs/{pk['packet']['id']}/revoke", params=B).status_code == 401


def test_security_headers_are_set(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer" and r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "content-security-policy" not in client.get("/docs").headers          # Swagger UI needs its CDN scripts
    assert "strict-transport-security" in client.get("/api/health", headers={"x-forwarded-proto": "https"}).headers
