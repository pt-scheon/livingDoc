"""Sign-in for public hosting: accounts (sign up / sign in / invites) plus the optional deployment password.

How it fits together
  * No accounts and no LIVINGDOC_ADMIN_PASSWORD: open mode (fine on localhost, never on the internet). The sidebar offers "Create account".
  * LIVINGDOC_ADMIN_PASSWORD set: every /api route needs a session or `Authorization: Bearer <password>` (scanners, scripts).
    That password is also the SETUP CODE: only someone who knows it can create the first (owner) account on a public host.
  * At least one account exists: sign-in is required even without the deployment password. New people join with an owner's invite code.
  * The deployment password can still sign in on its own (leave the e-mail empty): a break-glass owner session.
Routes meant for other people (public shop page JSON, proof checks, a counterparty's private link, health) stay public.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import settings
from .database import db, meta_get, meta_set
from .services import accounts

COOKIE = "ld_session"
SESSION_SECONDS = 7 * 24 * 3600
MAX_FAILS, WINDOW = 5, 60
SIGNUPS_PER_HOUR = 10
_fails: dict[str, deque] = defaultdict(deque)
_signups: dict[str, deque] = defaultdict(deque)
LEGACY = {"id": 0, "name": "Owner", "email": "", "role": "owner"}      # the deployment-password session

PUBLIC = [
    ("GET", re.compile(r"^/api/health$")),
    ("GET", re.compile(r"^/api/auth/status$")),
    ("POST", re.compile(r"^/api/auth/(login|logout|signup)$")),
    ("GET", re.compile(r"^/api/presence/public/[^/]+$")),
    ("POST", re.compile(r"^/api/presence/public/[^/]+/feedback$")),   # a customer comment; honeypot + rate limit inside
    ("POST", re.compile(r"^/api/proofs/(verify|check-openings)$")),
    ("POST", re.compile(r"^/api/proofs/[^/]+/open$")),            # gated by the proof's one-time open key
    ("GET", re.compile(r"^/api/proofs/[0-9a-f]+$")),               # a proof packet is meant to be shared
    ("GET", re.compile(r"^/api/trust/party/[^/]+$")),              # the token in the link is the credential
    ("POST", re.compile(r"^/api/trust/party/[^/]+/entries/\d+$")),
]


def required() -> bool:
    return bool(settings.admin_password) or accounts.count() > 0


def _secret() -> bytes:
    env = os.environ.get("LIVINGDOC_SECRET_KEY")
    if env:
        return env.encode()
    with db() as c:
        v = meta_get(c, "session_secret")
        if not v:
            v = secrets.token_hex(32)
            meta_set(c, "session_secret", v)
        return v.encode()


def _stamp(uid: int) -> str:
    """Changes when the person's password changes, so old sessions die. Empty for the deployment-password session."""
    if not uid:
        return ""
    u = accounts.get(uid)
    return hashlib.sha256(u["pw_hash"].encode()).hexdigest()[:16] if u else "gone"


def _sig(uid: int, expiry: str) -> str:
    key = hashlib.sha256(_secret() + b"|session|" + settings.admin_password.encode()).digest()
    return hmac.new(key, f"{uid}.{expiry}.{_stamp(uid)}".encode(), hashlib.sha256).hexdigest()


def make_token(uid: int = 0) -> str:
    exp = str(int(time.time()) + SESSION_SECONDS)
    return f"{uid}.{exp}.{_sig(uid, exp)}"


def session_user(tok: str | None):
    """The signed-in person for a session cookie, or None."""
    try:
        uid_s, exp, sig = (tok or "").split(".")
    except ValueError:
        return None
    if not (uid_s.isdigit() and exp.isdigit()) or int(exp) <= time.time():
        return None
    uid = int(uid_s)
    if not hmac.compare_digest(sig, _sig(uid, exp)):
        return None
    if uid == 0:
        return dict(LEGACY) if settings.admin_password else None
    u = accounts.get(uid)
    return accounts.public(u) if u else None


def valid_token(tok: str | None) -> bool:
    return session_user(tok) is not None


def _bearer(request: Request) -> bool:
    h = request.headers.get("authorization", "")
    return bool(settings.admin_password) and h.lower().startswith("bearer ") and hmac.compare_digest(h[7:].strip().encode(), settings.admin_password.encode())


def current_user(request: Request):
    u = session_user(request.cookies.get(COOKIE))
    if u:
        return u
    return dict(LEGACY) if _bearer(request) else None


def is_authed(request: Request) -> bool:
    return (not required()) or current_user(request) is not None


def is_public(method: str, path: str) -> bool:
    if method == "GET" and path == "/api/forecast/chart.png" and os.environ.get("LIVINGDOC_DEMO_STOREFRONT") == "1":
        return True   # a picture of sample forecast numbers, public only on a demo deployment
    return any(m == method and rx.match(path) for m, rx in PUBLIC)


async def guard(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api") and request.method != "OPTIONS" and not is_public(request.method, p) and required() and not is_authed(request):
        return JSONResponse({"detail": "Sign in required"}, status_code=401)
    return await call_next(request)


# ----------------------------------------------------------------------------- routes
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")


def _blocked(ip: str, key: str = "") -> bool:
    q, now = _fails[ip + key], time.time()
    while q and now - q[0] > WINDOW:
        q.popleft()
    return len(q) >= MAX_FAILS


def _fail(ip: str, status: int, msg: str, key: str = ""):
    _fails[ip + key].append(time.time())
    raise HTTPException(status, msg)


def _start_session(request: Request, response: Response, uid: int) -> None:
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, make_token(uid), max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=secure, path="/")


def need_user(request: Request) -> dict:
    u = current_user(request)
    if u is None:
        raise HTTPException(401, "Sign in required")
    return u


def need_owner(request: Request) -> dict:
    u = need_user(request)
    if u["role"] != "owner":
        raise HTTPException(403, "Only an owner can do this")
    return u


class LoginIn(BaseModel):
    email: str = Field(default="", max_length=120)
    password: str = Field(max_length=200)


class SignupIn(BaseModel):
    name: str = Field(max_length=60)
    email: str = Field(max_length=120)
    password: str = Field(max_length=200)
    code: str = Field(default="", max_length=200)


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class InviteIn(BaseModel):
    role: str = "staff"


@router.get("/status")
def status(request: Request):
    n = accounts.count()
    return {"required": required(), "authed": is_authed(request), "user": current_user(request), "setup": n == 0,
            "needs_setup_code": n == 0 and bool(settings.admin_password), "deployment_password": bool(settings.admin_password)}


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response):
    ip = _ip(request)
    if _blocked(ip, "|signup"):
        raise HTTPException(429, "Too many tries. Wait a minute and try again.")
    q, now = _signups[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= SIGNUPS_PER_HOUR:
        raise HTTPException(429, "Too many sign-ups from here. Try again later.")
    first = accounts.count() == 0
    invite = None
    if first:
        if settings.admin_password and not hmac.compare_digest(body.code.strip().encode(), settings.admin_password.encode()):
            _fail(ip, 403, "That setup code is not right", "|signup")
        role = "owner"
    else:
        invite = accounts.redeem_invite(body.code)
        if invite is None:
            _fail(ip, 403, "That invite code is not valid or has expired. Ask an owner for a new one.", "|signup")
        role = invite["role"]
    try:
        user = accounts.create_user(body.name, body.email, body.password, role)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    q.append(now)
    if invite:
        accounts.consume_invite(invite["id"], user["id"])
    accounts.touch_login(user["id"])
    _start_session(request, response, user["id"])
    return {"ok": True, "user": user}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    email = body.email.strip()
    if not required() and not email:
        return {"ok": True}
    ip = _ip(request)
    if _blocked(ip):
        raise HTTPException(429, "Too many wrong tries. Wait a minute and try again.")
    if email:
        u = accounts.by_email(email)
        if u is None:
            accounts.burn_time(body.password)
            _fail(ip, 401, "Wrong e-mail or password")
        if not accounts.check_password(body.password, u["pw_hash"]):
            _fail(ip, 401, "Wrong e-mail or password")
        accounts.touch_login(u["id"])
        _start_session(request, response, u["id"])
        return {"ok": True, "user": accounts.public(u)}
    if not settings.admin_password or not hmac.compare_digest(body.password.encode(), settings.admin_password.encode()):
        _fail(ip, 401, "Wrong password")
    _start_session(request, response, 0)
    return {"ok": True, "user": dict(LEGACY)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, response: Response):
    u = need_user(request)
    if not u["id"]:
        raise HTTPException(400, "The deployment password is changed in the hosting settings, not here")
    try:
        accounts.change_password(u["id"], body.current, body.new)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    _start_session(request, response, u["id"])      # the old sessions just died; keep this one signed in
    return {"ok": True}


@router.get("/users")
def users(request: Request):
    need_owner(request)
    return {"users": accounts.list_users(), "invites": accounts.list_invites()}


@router.delete("/users/{uid}")
def remove(uid: int, request: Request):
    me = need_owner(request)
    try:
        accounts.remove_user(uid, me["id"])
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, "No such person")
    return {"ok": True}


@router.post("/invites", status_code=201)
def invite(body: InviteIn, request: Request):
    me = need_owner(request)
    try:
        return accounts.make_invite(body.role, me["id"])
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))


@router.delete("/invites/{iid}")
def revoke(iid: int, request: Request):
    need_owner(request)
    accounts.revoke_invite(iid)
    return {"ok": True}
