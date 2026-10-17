"""Accounts: people who may open the app. Passwords are stored only as salted scrypt hashes.

Two roles: `owner` (everything, can invite and remove people) and `staff` (everything except managing people).
The first account is the owner. After that, new people join only with a single-use invite code made by an owner.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone

from ..database import db

INVITE_SECONDS = 7 * 24 * 3600
MIN_PASSWORD = 8
COMMON = {"password", "passw0rd", "12345678", "123456789", "1234567890", "qwertyui", "qwerty123", "admin123", "letmein1", "iloveyou", "welcome1",
          "administrator", "livingdoc", "password1", "11111111", "00000000", "abcd1234"}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_N, _R, _P = 2 ** 14, 8, 1


class AccountError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, bytes.fromhex(dk))
    except Exception:
        return False


_DUMMY = hash_password("not-a-real-password")


def burn_time(pw: str) -> None:
    """Spend the same time as a real check, so an unknown e-mail cannot be told apart by speed."""
    check_password(pw, _DUMMY)


def validate_password(pw: str, email: str = "", name: str = "") -> None:
    if len(pw) < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters")
    if len(pw) > 200:
        raise AccountError("Password is too long")
    low = pw.lower()
    if low in COMMON or len(set(low)) < 4:
        raise AccountError("That password is too easy to guess. Try a few unrelated words.")
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in low:
        raise AccountError("The password should not contain your e-mail name")
    if name and len(name) >= 4 and name.lower() in low:
        raise AccountError("The password should not contain your name")


def norm_email(e: str) -> str:
    e = (e or "").strip().lower()
    if not _EMAIL.match(e) or len(e) > 120:
        raise AccountError("Enter a valid e-mail address")
    return e


def count() -> int:
    try:
        with db() as c:
            return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    except Exception:
        return 0


def public(u) -> dict:
    return dict(id=u["id"], name=u["name"], email=u["email"], role=u["role"], created_at=u["created_at"], last_login=u["last_login"])


def get(uid: int):
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None


def by_email(email: str):
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()
        return dict(r) if r else None


def _hash_code(code: str) -> str:
    return hashlib.sha256(("livingdoc-invite|" + code.strip().upper()).encode()).hexdigest()


def create_user(name, email, password, role) -> dict:
    name = (name or "").strip()
    if not 1 <= len(name) <= 60:
        raise AccountError("Enter your name (up to 60 characters)")
    email = norm_email(email)
    validate_password(password, email, name)
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise AccountError("That e-mail already has an account. Sign in instead.")
        cur = c.execute("INSERT INTO users(email,name,role,pw_hash,created_at) VALUES(?,?,?,?,?)", (email, name, role, hash_password(password), _now()))
        return public(dict(c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()))


def touch_login(uid: int) -> None:
    with db() as c:
        c.execute("UPDATE users SET last_login=? WHERE id=?", (_now(), uid))


def change_password(uid: int, current: str, new: str) -> None:
    u = get(uid)
    if u is None or not check_password(current, u["pw_hash"]):
        raise AccountError("Your current password is not right")
    validate_password(new, u["email"], u["name"])
    with db() as c:
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), uid))


def list_users() -> list[dict]:
    with db() as c:
        return [public(dict(r)) for r in c.execute("SELECT * FROM users ORDER BY id")]


def remove_user(uid: int, by: int) -> None:
    if uid == by:
        raise AccountError("You cannot remove yourself")
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if u is None:
            raise KeyError(uid)
        if u["role"] == "owner" and c.execute("SELECT COUNT(*) n FROM users WHERE role='owner'").fetchone()["n"] <= 1:
            raise AccountError("There must always be one owner")
        c.execute("DELETE FROM users WHERE id=?", (uid,))


def make_invite(role: str, by: int) -> dict:
    if role not in ("owner", "staff"):
        raise AccountError("Unknown role")
    code = "-".join(secrets.token_hex(2).upper() for _ in range(3))      # e.g. 3FA9-0C1B-77D2
    exp = time.time() + INVITE_SECONDS
    with db() as c:
        c.execute("INSERT INTO invites(code_hash,role,created_by,created_at,expires_at,hint) VALUES(?,?,?,?,?,?)", (_hash_code(code), role, by, _now(), exp, code[-4:]))
    return dict(code=code, role=role, expires_at=exp)


def list_invites() -> list[dict]:
    with db() as c:
        return [dict(id=r["id"], role=r["role"], hint=r["hint"], expires_at=r["expires_at"], created_at=r["created_at"])
                for r in c.execute("SELECT * FROM invites WHERE used_by IS NULL AND expires_at>? ORDER BY id DESC", (time.time(),))]


def revoke_invite(iid: int) -> None:
    with db() as c:
        c.execute("DELETE FROM invites WHERE id=? AND used_by IS NULL", (iid,))


def redeem_invite(code: str):
    """Returns the invite row if valid, else None. Marked used only after the account exists (see consume_invite)."""
    with db() as c:
        r = c.execute("SELECT * FROM invites WHERE code_hash=? AND used_by IS NULL AND expires_at>?", (_hash_code(code or ""), time.time())).fetchone()
        return dict(r) if r else None


def consume_invite(iid: int, uid: int) -> None:
    with db() as c:
        c.execute("UPDATE invites SET used_by=? WHERE id=?", (uid, iid))
