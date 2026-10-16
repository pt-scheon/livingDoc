"""Small text helpers: name normalisation, Markdown escaping, number/money formatting."""
import re

from .config import settings


# ------------------------------------------------------------ name helpers ---
STOP_TOKENS = {"of", "the", "a", "an", "some", "few", "more"}


def stem(w: str) -> str:
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and re.search(r"(s|x|z|ch|sh)es$", w):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def norm_tokens(s: str):
    toks = re.findall(r"[^\W_]+", (s or "").lower(), flags=re.UNICODE)
    return [stem(t) for t in toks if t not in STOP_TOKENS]


def pretty_name(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw.strip())
    return raw.title() if raw.isascii() else raw


def same_entity(a: str, b: str) -> bool:
    ta, tb = set(norm_tokens(a)), set(norm_tokens(b))
    return bool(ta and tb and (ta <= tb or tb <= ta))


def md_esc(s) -> str:
    return re.sub(r"\s+", " ", str(s)).replace("|", "\\|").replace("`", "'").replace("<", "&lt;").strip()


def fmt_qty(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def fmt_money(x: float) -> str:
    return f"{settings.currency}{x:,.0f}" if abs(x - round(x)) < 0.005 else f"{settings.currency}{x:,.2f}"
