"""Optional owner login for public hosting.

If LIVINGDOC_ADMIN_PASSWORD is empty the app runs open (fine on localhost, never on the internet). If it is set, every /api route
needs a signed session cookie or `Authorization: Bearer <password>` (for scanners and scripts), EXCEPT the routes that are meant
to be reached by other people:
  * the public shop page JSON and the proof verification tools,
  * a counterparty's private link (the unguessable token is the credential),
  * health and login themselves.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import settings

COOKIE = "ld_session"
SESSION_SECONDS = 7 * 24 * 3600
MAX_FAILS, WINDOW = 5, 60
_fails: dict[str, deque] = defaultdict(deque)

PUBLIC = [
    ("GET", re.compile(r"^/api/health$")),
    ("GET", re.compile(r"^/api/auth/status$")),
    ("POST", re.compile(r"^/api/auth/(login|logout)$")),
    ("GET", re.compile(r"^/api/presence/public/[^/]+$")),
    ("POST", re.compile(r"^/api/proofs/(verify|check-openings)$")),
    ("POST", re.compile(r"^/api/proofs/[^/]+/open$")),            # gated by the proof's one-time open key
    ("GET", re.compile(r"^/api/proofs/[0-9a-f]+$")),               # a proof packet is meant to be shared
    ("GET", re.compile(r"^/api/trust/party/[^/]+$")),              # the token in the link is the credential
    ("POST", re.compile(r"^/api/trust/party/[^/]+/entries/\d+$")),
]


def required() -> bool:
    return bool(settings.admin_password)


def _sig(expiry: str) -> str:
    key = hashlib.sha256(("livingdoc-session|" + settings.admin_password).encode()).digest()
    return hmac.new(key, expiry.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_SECONDS)
    return f"{exp}.{_sig(exp)}"


def valid_token(tok: str | None) -> bool:
    if not tok or "." not in tok:
        return False
    exp, sig = tok.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _sig(exp))


def is_authed(request: Request) -> bool:
    if not required():
        return True
    if valid_token(request.cookies.get(COOKIE)):
        return True
    h = request.headers.get("authorization", "")
    return h.lower().startswith("bearer ") and hmac.compare_digest(h[7:].strip().encode(), settings.admin_password.encode())


def is_public(method: str, path: str) -> bool:
    if method == "GET" and path == "/api/forecast/chart.png" and os.environ.get("LIVINGDOC_DEMO_STOREFRONT") == "1":
        return True   # a picture of sample forecast numbers, public only on a demo deployment
    return any(m == method and rx.match(path) for m, rx in PUBLIC)


async def guard(request: Request, call_next):
    p = request.url.path
    if required() and p.startswith("/api") and request.method != "OPTIONS" and not is_public(request.method, p) and not is_authed(request):
        return JSONResponse({"detail": "Sign in required"}, status_code=401)
    return await call_next(request)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


@router.get("/status")
def status(request: Request):
    return {"required": required(), "authed": is_authed(request)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    if not required():
        return {"ok": True}
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
    q, now = _fails[ip], time.time()
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= MAX_FAILS:
        raise HTTPException(429, "Too many wrong passwords. Wait a minute and try again.")
    if not hmac.compare_digest(body.password.encode(), settings.admin_password.encode()):
        q.append(now)
        raise HTTPException(401, "Wrong password")
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, make_token(), max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=secure, path="/")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
