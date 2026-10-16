"""Daily web-trend search: what are people looking for right now?

Once per day (cached in SQLite) we run a handful of web searches (DuckDuckGo via the `ddgs` package — no API key)
about the city, the upcoming festival and each product category, then score each product by how often its keywords
show up in result titles/snippets.  That score nudges its demand (+12% at most) and decides which item is the
"traffic driver" for a sale.

If the search is unreachable, an *assumed* score derived from festival affinity is used — and labelled as such.
Run `python scripts/refresh_daily.py` from cron / Task Scheduler for a true once-a-day refresh; the app also
refreshes lazily if today's cache is missing.
"""
from __future__ import annotations

import datetime as dt
import re

import numpy as np

MAX_BOOST = 0.12


def _queries(city: str, upcoming: list[str], categories: list[str]) -> list[str]:
    q = [f"trending products to buy this week {city}", f"what is selling most {city} festive shopping"]
    for f in upcoming[:2]:
        q.append(f"{f} shopping demand {city} best selling")
    for c in categories[:4]:
        q.append(f"{c} demand India this season trending")
    return q


def _search(queries: list[str], max_results: int = 8) -> list[dict]:
    try:
        from ddgs import DDGS
    except Exception:
        try:
            from duckduckgo_search import DDGS  # older package name
        except Exception:
            return []
    out, fails = [], 0
    try:
        with DDGS(timeout=6) as ddg:
            for q in queries:
                try:
                    for r in ddg.text(q, region="in-en", timelimit="w", max_results=max_results) or []:
                        out.append(dict(query=q, title=r.get("title", ""), body=r.get("body", ""), url=r.get("href", "")))
                    fails = 0
                except Exception:
                    fails += 1
                    if fails >= 2 and not out:      # offline / blocked: stop early instead of waiting on every query
                        break
    except Exception:
        return out
    return out


def score_products(results: list[dict], products: list[dict]) -> dict[str, float]:
    """Keyword hits → score in [0, 1.5]. Hits are normalised by the best product so scores are relative."""
    text = [(r["title"] + " " + r["body"]).lower() for r in results]
    hits = {}
    for p in products:
        kws = [k.strip().lower() for k in (p.get("keywords") or "").split(",") if k.strip()] + [p["category"].lower()]
        hits[p["name"]] = sum(len(re.findall(r"\b" + re.escape(k) + r"s?\b", t)) for t in text for k in kws)
    top = max(hits.values()) if hits else 0
    if top == 0:
        return {k: 0.0 for k in hits}
    confidence = min(1.0, len(results) / 20.0)
    return {k: float(min(1.5, 1.5 * (v / top) * confidence)) for k, v in hits.items()}


def assumed_scores(products: list[dict], festivals: list[dict], today: dt.date) -> dict[str, float]:
    """Offline fallback: the next festival within 21 days, weighted by category affinity."""
    best = None
    for f in festivals:
        s = dt.date.fromisoformat(str(f["start"])[:10])
        if 0 <= (s - today).days <= 21 and (best is None or f["lift"] > best["lift"]):
            best = f
    out = {}
    for p in products:
        aff = (best or {}).get("aff", {}).get(p["category"], 1.0) if best else 1.0
        out[p["name"]] = float(np.clip((aff - 0.8) * 0.9, 0.0, 1.0)) if best else 0.0
    return out


def refresh(store, profile: dict, festivals: list[dict], today: dt.date | None = None, force: bool = False) -> dict:
    """Return today's trend payload, searching the web at most once per day unless force=True."""
    today = today or dt.date.today()
    cached = store.get_trends(today)
    if cached and not force:
        return cached
    city = profile["location"]["name"].split(",")[0]
    upcoming = [f["name"] for f in festivals if 0 <= (dt.date.fromisoformat(str(f["start"])[:10]) - today).days <= 30]
    cats = sorted({p["category"] for p in profile["products"]})
    results = _search(_queries(city, upcoming, cats))
    if results:
        scores = score_products(results, profile["products"])
        source = "web"
    else:
        scores = assumed_scores(profile["products"], festivals, today)
        source = "assumed"
    seen, headlines = set(), []
    for r in results:
        if r["url"] and r["url"] not in seen and len(headlines) < 8:
            seen.add(r["url"])
            headlines.append(dict(title=r["title"][:110], url=r["url"], query=r["query"]))
    payload = dict(day=today.isoformat(), source=source, scores=scores, headlines=headlines,
                   n_results=len(results), queries=_queries(city, upcoming, cats))
    store.set_trends(today, payload)
    return payload


def boost(score: float) -> float:
    return 1.0 + MAX_BOOST * min(max(score, 0.0), 1.0)
