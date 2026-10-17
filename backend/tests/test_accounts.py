"""Sign up, sign in, invites, roles, password change."""
import pytest

from app import auth
from app.config import settings

B = {"branch": "Main Store"}
OWNER = dict(name="Aaditya Sheth", email="Aaditya@Example.com", password="mango-river-42")


@pytest.fixture(autouse=True)
def _clean():
    auth._fails.clear(); auth._signups.clear()
    yield
    auth._fails.clear(); auth._signups.clear()


def signup(c, **kw):
    return c.post("/api/auth/signup", json={**OWNER, **kw})


def test_first_signup_in_open_mode_makes_an_owner_and_locks_the_app(client):
    assert client.get("/api/document", params=B).status_code == 200            # open until someone signs up
    r = signup(client)
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner" and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/status").json()["user"]["email"] == "aaditya@example.com"
    assert client.get("/api/document", params=B).status_code == 200             # signed in
    client.cookies.clear()
    st = client.get("/api/auth/status").json()
    assert st["required"] is True and st["authed"] is False and st["setup"] is False
    assert client.get("/api/document", params=B).status_code == 401


def test_password_is_hashed_never_stored_plain(client):
    signup(client)
    from app.database import db
    with db() as c:
        h = c.execute("SELECT pw_hash FROM users").fetchone()["pw_hash"]
    assert h.startswith("scrypt$") and OWNER["password"] not in h


def test_sign_in_with_email_is_case_insensitive_and_errors_do_not_reveal_which_part_was_wrong(client):
    signup(client); client.cookies.clear()
    a = client.post("/api/auth/login", json={"email": "aaditya@example.com", "password": "wrong-pass-1"})
    b = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass-1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    ok = client.post("/api/auth/login", json={"email": "AADITYA@example.com", "password": OWNER["password"]})
    assert ok.status_code == 200 and client.get("/api/document", params=B).status_code == 200


def test_weak_and_invalid_signups_are_refused(client):
    for bad in ({"password": "short"}, {"password": "password"}, {"password": "aaaaaaaa"}, {"password": "aaditya-1234"}, {"email": "not-an-email"}, {"name": ""}):
        assert signup(client, **bad).status_code == 400, bad
    assert client.get("/api/auth/status").json()["setup"] is True


def test_duplicate_email_is_refused(client):
    signup(client)
    inv = client.post("/api/auth/invites", json={"role": "staff"}).json()["code"]
    client.cookies.clear()
    assert signup(client, code=inv).status_code == 400


def test_with_a_deployment_password_the_first_signup_needs_it_as_setup_code(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "deploy-secret")
    assert signup(client).status_code == 403
    assert signup(client, code="wrong").status_code == 403
    assert signup(client, code="deploy-secret").status_code == 200
    # the deployment password alone still works as a break-glass owner sign-in
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"password": "deploy-secret"}).status_code == 200
    assert client.get("/api/auth/status").json()["user"]["role"] == "owner"


def test_later_people_join_only_with_a_single_use_invite(client):
    signup(client)
    assert signup(client, email="b@example.com").status_code == 403           # open signup is closed once an owner exists
    code = client.post("/api/auth/invites", json={"role": "staff"}).json()["code"]
    assert client.get("/api/auth/users").json()["invites"][0]["hint"] == code[-4:]
    client.cookies.clear()
    r = signup(client, name="Ravi", email="ravi@example.com", password="tiger-lamp-77", code=code)
    assert r.status_code == 200 and r.json()["user"]["role"] == "staff"
    client.cookies.clear()
    assert signup(client, name="Eve", email="eve@example.com", password="tiger-lamp-78", code=code).status_code == 403   # already used


def test_staff_cannot_manage_people_but_can_use_the_app(client):
    signup(client)
    code = client.post("/api/auth/invites", json={"role": "staff"}).json()["code"]
    client.cookies.clear()
    signup(client, name="Ravi", email="ravi@example.com", password="tiger-lamp-77", code=code)
    assert client.get("/api/document", params=B).status_code == 200
    assert client.get("/api/auth/users").status_code == 403
    assert client.post("/api/auth/invites", json={"role": "owner"}).status_code == 403
    assert client.delete("/api/auth/users/1").status_code == 403


def test_owner_can_remove_staff_not_self_and_a_removed_session_dies(client):
    signup(client)
    code = client.post("/api/auth/invites", json={}).json()["code"]
    owner_cookie = dict(client.cookies)
    client.cookies.clear()
    signup(client, name="Ravi", email="ravi@example.com", password="tiger-lamp-77", code=code)
    staff_cookie = dict(client.cookies)
    client.cookies.clear(); client.cookies.update(owner_cookie)
    users = client.get("/api/auth/users").json()["users"]
    me = next(u for u in users if u["role"] == "owner"); ravi = next(u for u in users if u["role"] == "staff")
    assert client.delete(f"/api/auth/users/{me['id']}").status_code == 400
    assert client.delete(f"/api/auth/users/{ravi['id']}").status_code == 200
    client.cookies.clear(); client.cookies.update(staff_cookie)
    assert client.get("/api/document", params=B).status_code == 401


def test_changing_password_ends_other_sessions(client):
    signup(client)
    old = dict(client.cookies)
    assert client.post("/api/auth/password", json={"current": "wrong-one-1", "new": "river-mango-88"}).status_code == 400
    assert client.post("/api/auth/password", json={"current": OWNER["password"], "new": "river-mango-88"}).status_code == 200
    assert client.get("/api/document", params=B).status_code == 200            # this session was renewed
    other = client.__class__(client.app)
    other.cookies.update(old)
    assert other.get("/api/document", params=B).status_code == 401              # the old one died
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}).status_code == 401
    assert client.post("/api/auth/login", json={"email": OWNER["email"], "password": "river-mango-88"}).status_code == 200


def test_wrong_tries_are_rate_limited_for_sign_in_and_for_invite_guessing(client):
    signup(client); client.cookies.clear()
    for _ in range(auth.MAX_FAILS):
        assert client.post("/api/auth/login", json={"email": OWNER["email"], "password": "bad-bad-bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}).status_code == 429
    for _ in range(auth.MAX_FAILS):
        assert signup(client, email="x@example.com", code="AAAA-BBBB-CCCC").status_code == 403
    assert signup(client, email="x@example.com", code="AAAA-BBBB-CCCC").status_code == 429


def test_public_routes_stay_public_once_accounts_exist(client):
    signup(client)
    client.put("/api/presence", params=B, json={"tagline": "Hi", "published": True})
    slug = client.get("/api/presence", params=B).json()["profile"]["slug"]
    client.cookies.clear()
    assert client.get(f"/api/presence/public/{slug}").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/presence", params=B).status_code == 401
