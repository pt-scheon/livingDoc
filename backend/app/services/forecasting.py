"""Foresight integration: demand forecast, pricing plan, owner factors, scorecard.

How LivingDoc data feeds Foresight (see README "Forecast & Pricing"):

* Each branch has its own Foresight SQLite file (``<db dir>/foresight_data/<branch>.db``). Foresight keeps its own
  ``festivals`` table (different shape from LivingDoc's), so the two calendars are deliberately separate.
* ``items``  -> Foresight ``profile["products"]``: baseline_burn -> base_units, current stock -> supply_per_day
  (capacity), shelf life -> perishable. LivingDoc has no price/cost/category/elasticity, so those live in a
  per-branch *catalogue* of product settings (assumed defaults, flagged until the owner edits them).
* ``cash_events`` (collected) and outflow ``movements`` -> daily ``actuals`` (orders ~ outflow events: a proxy,
  the owner can overwrite any day).  These are tagged ``source=livingdoc`` and can be cleared.
* Nothing here hides an assumption: every payload carries the flags the UI needs to label assumed values.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
import threading
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from foresight import calendar_feats, config as fc, demo as fdemo, owner, paycheck, scorecard, trends, weather
from foresight.engine import Engine
from foresight.store import Store

from ..config import settings
from ..database import db, meta_get, meta_set

log = logging.getLogger("livingdoc.forecasting")

_LOCKS: dict[str, threading.RLock] = defaultdict(threading.RLock)
_DAILY_RUNNING = threading.Event()


class ForecastError(ValueError):
    """Bad input (maps to HTTP 400)."""


# ----------------------------------------------------------------------------- plumbing
def today() -> dt.date:
    return dt.date.today()


def _slug(branch: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", branch.lower()).strip("_") or "branch"


def store_path(branch: str) -> Path:
    import os
    base = os.environ.get("LIVINGDOC_FORESIGHT_DIR") or str(Path(settings.db_path).resolve().parent / "foresight_data")
    return Path(base) / f"{_slug(branch)}.db"


def live_allowed() -> bool:
    import os
    return os.environ.get("LIVINGDOC_FORESIGHT_LIVE", "1") == "1"


def lock(branch: str) -> threading.RLock:
    return _LOCKS[store_path(branch).as_posix()]


def py(v):
    """Make pandas/numpy values JSON-safe: NaN/NaT -> None, Timestamps -> 'YYYY-MM-DD'."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, dict):
        return {str(k): py(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [py(x) for x in v]
    if isinstance(v, np.ndarray):
        return [py(x) for x in v.tolist()]
    return v


def records(df: pd.DataFrame, cols: list[str] | None = None, index_name: str | None = None) -> list[dict]:
    if df is None or not len(df):
        return []
    d = df.reset_index() if index_name else df
    if index_name and d.columns[0] != index_name:
        d = d.rename(columns={d.columns[0]: index_name})
    cols = cols or list(d.columns)
    if index_name and index_name not in cols:
        cols = [index_name, *cols]
    return [{c: py(r[c]) for c in cols} for _, r in d.iterrows()]


# ----------------------------------------------------------------------------- product catalogue
_CAT_HINTS = [
    (r"sweet|mithai|barfi|laddu|kaju|jalebi|halwa|peda|chikki", "sweets"),
    (r"gift|hamper|box", "gifts"),
    (r"coffee|tea|milk|juice|drink|cola|soda|cup", "beverages"),
    (r"snack|chips|namkeen|fafda|biscuit", "snacks"),
    (r"lamp|diya|decor|rangoli|candle", "decor"),
]
_ESSENTIAL = r"flour|atta|sugar|milk|oil|rice|dal|salt|wheat"
CATEGORIES = ["sweets", "snacks", "beverages", "gifts", "grocery", "decor", "apparel", "electronics"]
DEFAULT_PRICE, DEFAULT_COST = 100.0, 70.0


def _guess_category(name: str) -> str:
    n = name.lower()
    for pat, cat in _CAT_HINTS:
        if re.search(pat, n):
            return cat
    return "grocery"


def _margin_elasticity(price: float, cost: float) -> float:
    """Lerner rule: your price is assumed right on a normal day, so e = price / (price - cost)."""
    return round(float(np.clip(price / max(price - cost, 1e-6), 0.4, 4.0)), 3)


def default_setting(name: str, shelf_life) -> dict:
    cat = _guess_category(name)
    ess = bool(re.search(_ESSENTIAL, name.lower()))
    return dict(category=cat, cost=DEFAULT_COST, price=DEFAULT_PRICE, elasticity_auto=True,
                elasticity=_margin_elasticity(DEFAULT_PRICE, DEFAULT_COST), essential=ess,
                perishable=bool(shelf_life and shelf_life <= 14), temp_sens=0.0, rain_sens=0.0,
                keywords=name.lower(), tracked=True, assumed_prices=True)


def _items(branch: str) -> list[dict]:
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT name, unit, qty, baseline_burn, shelf_life_days FROM items WHERE branch=? ORDER BY name", (branch,))]


def sync_products(branch: str, store: Store) -> dict:
    """Rebuild profile['products'] from LivingDoc items + the catalogue of product settings."""
    cat = store.get_kv("catalogue", {})
    products, skipped, rows = [], [], []
    changed = False
    for it in _items(branch):
        name = it["name"]
        s = cat.get(name)
        if s is None:
            s = default_setting(name, it["shelf_life_days"])
            cat[name] = s
            changed = True
        if s.get("elasticity_auto", True):
            e = _margin_elasticity(s["price"], s["cost"])
            if e != s.get("elasticity"):
                s["elasticity"] = e
                changed = True
        burn = float(it["baseline_burn"] or 0)
        stock = max(float(it["qty"] or 0), 0.0)
        row = dict(name=name, unit=it["unit"], stock=stock, daily_use=burn, **{k: s[k] for k in (
            "category", "cost", "price", "elasticity", "elasticity_auto", "essential", "perishable",
            "temp_sens", "rain_sens", "keywords", "tracked", "assumed_prices")})
        if not s.get("tracked", True):
            row["status"] = "untracked"
        elif burn <= 0:
            row["status"] = "no_daily_use"
            skipped.append(name)
        else:
            row["status"] = "tracked"
            products.append(dict(
                name=name, category=s["category"], cost=float(s["cost"]), price=float(s["price"]), base_units=burn,
                elasticity=float(s["elasticity"]), supply_per_day=stock, perishable=bool(s["perishable"]),
                essential=bool(s["essential"]), temp_sens=float(s["temp_sens"]), rain_sens=float(s["rain_sens"]),
                keywords=s["keywords"], unit=it["unit"], assumed_prices=bool(s.get("assumed_prices", True))))
        rows.append(row)
    if changed:
        store.set_kv("catalogue", cat)
    prof = store.get_profile()
    if prof.get("products") != products:
        prof["products"] = products
        store.set_profile(prof)
    return dict(products=rows, skipped=skipped, tracked=len(products))


def get_store(branch: str) -> Store:
    path = store_path(branch)
    first = not path.exists()
    store = Store(str(path))
    prof = store.get_profile()
    if first or not live_allowed() and prof.get("use_live_weather", True):
        if not live_allowed():
            prof["use_live_weather"] = False
        store.set_profile(prof)
    return store


def open_engine(branch: str, store: Store | None = None) -> tuple[Store, Engine, dict]:
    store = store or get_store(branch)
    info = sync_products(branch, store)
    if info["tracked"] == 0:
        raise ForecastError("No tracked products: give at least one item a daily use above zero in the inventory, "
                            "and keep it ticked as tracked in Owner inputs.")
    return store, Engine(store, today=today()), info


# ----------------------------------------------------------------------------- forecast
def _assumption_flags(eng: Engine, info: dict) -> dict:
    prof = eng.profile
    nreal = eng.model.n_real
    return dict(
        festival_dates="assumed",           # editable, verify for your region
        pay_schedules="assumed",
        climatology_when_offline="assumed",
        starting_coefficients="learning" if nreal < 30 else "mostly_learned",
        prices_assumed=sum(1 for p in info["products"] if p["status"] == "tracked" and p["assumed_prices"]),
        elasticity_from_margin=sum(1 for p in info["products"] if p["status"] == "tracked" and p["elasticity_auto"]),
        capacity="current stock (deliveries are not modelled)",
        orders_proxy="outflow events per day (LivingDoc has no order count)",
        base_orders=prof["base_orders"],
        avg_ticket=prof["avg_ticket"],
    )


def source_counts(store: Store) -> dict:
    act = store.actuals()
    by = act["source"].value_counts().to_dict() if len(act) else {}
    return dict(total=int(len(act)), by_source={k: int(v) for k, v in by.items()}, demo=int(by.get("demo", 0)))


def forecast(branch: str, horizon: int = 28, history: int = 28) -> dict:
    horizon, history = max(1, min(int(horizon), 90)), max(0, min(int(history), 90))
    with lock(branch):
        store, eng, info = open_engine(branch)
        fc_df = eng.forecast(horizon, history)
        plan = eng.full_plan(fc_df)
        eng.log_forecasts(fc_df, plan)
        wdf = fc_df.rename(columns={"wsource": "source"})
        n_live = int((fc_df["wsource"] == "live").sum())
        brief = eng.brief(fc_df, plan)
        fut = fc_df[fc_df["is_future"]]
        days = records(fc_df, ["point", "lo50", "hi50", "lo80", "hi80", "index", "wave_idx", "fest_name", "tmax", "tmin",
                               "rain_mm", "wsource", "actual", "actual_kind", "is_future", "owner_frac", "competition"],
                       index_name="date")
        spans = calendar_feats.festival_spans(eng.festivals, fc_df.index.min().date(), fc_df.index.max().date())
        peaks = paycheck.peak_days(fut, 3)
        trend = store.get_trends(eng.today.date()) or store.latest_trends()[1]
        return py(dict(
            branch=branch, today=eng.today, horizon=horizon,
            days=days,
            festivals=spans,
            payday_peaks=peaks,
            brief=dict(today_orders=brief["today_orders"], today_vs_typical=brief["today_vs_typical"],
                       lo80=brief["lo80"], hi80=brief["hi80"], reasons=brief["reasons"], peak_day=brief["peak_day"],
                       peak_orders=brief["peak_orders"], peak_vs_typical=brief["peak_vs_typical"],
                       surges=brief["surges"], sales=brief["sales"]),
            meta=dict(
                weather=dict(status=weather.weather_status(wdf), live_days=n_live, total_days=len(fc_df),
                             live_enabled=bool(eng.profile.get("use_live_weather", True)) and live_allowed()),
                model=dict(n_real=eng.model.n_real, n_assumed=eng.model.n_assumed, sigma=eng.model.sigma,
                           typical_orders=float(np.exp(eng.model.typical_log()))),
                trends=dict(source=(trend or {}).get("source", "assumed"), day=(trend or {}).get("day")),
                actuals=source_counts(store),
                assumptions=_assumption_flags(eng, info),
                location=eng.profile["location"]["name"],
                skipped_products=info["skipped"],
            ),
        ))


def pricing_plan(branch: str, date=None, days: int = 1) -> dict:
    days = max(1, min(int(days), 28))
    with lock(branch):
        store, eng, info = open_engine(branch)
        start = pd.Timestamp(date or eng.today).normalize()
        dates = pd.date_range(start, periods=days)
        fr = eng._frame(dates)
        plan = eng.pricing_plan(fr)
        stock = {p["name"]: p for p in info["products"]}
        rows = []
        for r in plan.to_dict("records"):
            out = {k: py(r[k]) for k in ("date", "product", "category", "label", "mult", "price", "base_price", "units",
                                          "revenue", "profit", "uplift", "demand_at_base", "supply", "prep", "elasticity",
                                          "index", "promo", "reason", "reason_code", "reason_flags", "reason_params")}
            s = stock.get(r["product"], {})
            out["unit"] = s.get("unit")
            out["assumed_prices"] = bool(s.get("assumed_prices", True))
            out["essential"] = bool(s.get("essential", False))
            if r["supply"] <= 0:                       # nothing on the shelf: a price recommendation is meaningless
                out.update(label="HOLD", mult=1.0, price=out["base_price"], reason_code="out_of_stock",
                           reason="Out of stock: reorder first; no price change recommended.", reason_flags=[])
            rows.append(out)
        return py(dict(branch=branch, date=start, days=days, rows=rows,
                       trend_source=(store.get_trends(eng.today.date()) or store.latest_trends()[1] or {}).get("source", "assumed"),
                       assumptions=_assumption_flags(eng, info)))


def explain(branch: str, date) -> dict:
    with lock(branch):
        store, eng, info = open_engine(branch)
        d = pd.Timestamp(date or eng.today).normalize()
        s = eng.explain(d)
        items = []
        for k, v in s.items():
            kind = "owner" if k.startswith("You: ") else "assumed" if "assumed" in k else "model"
            items.append(dict(driver=k, effect=float(v), kind=kind))
        items.sort(key=lambda x: -abs(x["effect"]))
        fr = eng._frame([d])
        return py(dict(date=d, drivers=items, expected_orders=float(fr["point"].iloc[0]),
                       typical_orders=float(fr["typical"].iloc[0])))


# ----------------------------------------------------------------------------- actuals / learning
def _recompute_beliefs(eng: Engine, store: Store) -> list[dict]:
    """Re-grade owner factors against already-logged days (used after a factor is added or removed)."""
    act = store.actuals()
    if not len(act) or not len(store.factors()):
        return []
    span = pd.date_range(act["date"].min(), act["date"].max())
    fr = eng._frame(span)
    pred = pd.Series(fr["point_no_owner"].to_numpy(), index=span)
    changes = owner.update_posteriors(store, pred, act, eng.cat_w)
    eng.refit()
    return changes


def log_actual(branch: str, date, orders: float, revenue=None, note: str = "", source: str = "owner") -> dict:
    d = pd.Timestamp(date).normalize()
    with lock(branch):
        store, eng, _ = open_engine(branch)
        if d > eng.today:
            raise ForecastError("You can only log days up to today.")
        res = eng.log_actual(d, float(orders), None if revenue is None else float(revenue), note, source)
        return py(dict(date=d, factor_changes=res["factor_changes"], n_real=res["n_real"],
                       beta_shift=res["beta_shift"]))


def list_actuals(branch: str, limit: int = 60) -> list[dict]:
    with lock(branch):
        store = get_store(branch)
        a = store.actuals()
        return records(a.sort_values("date", ascending=False).head(limit), ["date", "orders", "revenue", "note", "source"]) if len(a) else []


def delete_actual(branch: str, date) -> bool:
    with lock(branch):
        store, eng, _ = open_engine(branch)
        a = store.actuals()
        d = pd.Timestamp(date).normalize()
        if not len(a) or d not in set(a["date"]):
            return False
        store.delete_actual(d.date())
        eng.refit()
        return True


def clear_actuals(branch: str, source: str) -> int:
    if source not in ("demo", "livingdoc", "owner"):
        raise ForecastError("source must be demo, livingdoc or owner")
    with lock(branch):
        store, eng, _ = open_engine(branch)
        a = store.actuals()
        n = 0
        if len(a):
            for r in a[a["source"] == source].itertuples():
                store.delete_actual(r.date.date())
                n += 1
        with store.conn() as c:
            c.execute("DELETE FROM forecast_log WHERE kind='backcast'")
        eng.refit()
        return n


def derive_daily(branch: str, since: dt.date, until: dt.date) -> list[dict]:
    """LivingDoc -> (date, orders, revenue) for days in [since, until]. Orders = number of outflow events."""
    with db() as c:
        out = {r["d"]: r["n"] for r in c.execute(
            "SELECT substr(ts,1,10) d, COUNT(*) n FROM movements WHERE branch=? AND change<0 AND source IN ('scanner','note') "
            "AND substr(ts,1,10)>=? AND substr(ts,1,10)<=? GROUP BY d", (branch, since.isoformat(), until.isoformat()))}
        cash = {r["d"]: r["s"] for r in c.execute(
            "SELECT substr(ts,1,10) d, SUM(amount) s FROM cash_events WHERE branch=? AND type='collected' "
            "AND substr(ts,1,10)>=? AND substr(ts,1,10)<=? GROUP BY d", (branch, since.isoformat(), until.isoformat()))}
    return [dict(date=d, orders=float(n), revenue=float(cash[d]) if d in cash else None) for d, n in sorted(out.items())]


def import_livingdoc(branch: str, days: int = 30) -> dict:
    """Log past LivingDoc days (not today, not days already logged) as actuals with source=livingdoc."""
    days = max(1, min(int(days), 90))
    with lock(branch):
        store, eng, _ = open_engine(branch)
        until = eng.today.date() - dt.timedelta(days=1)
        have = set(store.actuals()["date"].dt.strftime("%Y-%m-%d")) if len(store.actuals()) else set()
        cand = [r for r in derive_daily(branch, until - dt.timedelta(days=days - 1), until) if r["date"] not in have]
        for r in cand:
            eng.log_actual(r["date"], r["orders"], r["revenue"], "from LivingDoc movements (orders = outflow events)", "livingdoc")
        return dict(imported=len(cand), dates=[r["date"] for r in cand])


# ----------------------------------------------------------------------------- owner factors / rivals
def _factor_row(r, nreal_ok=True) -> dict:
    prior = owner.prior_effect(float(r.effect_pct), float(r.confidence)) * 100
    post = None if pd.isna(r.posterior_pct) else float(r.posterior_pct)
    return dict(id=int(r.id), name=r.name, start=py(r.start), end=py(r.end), effect_pct=float(r.effect_pct),
                confidence=float(r.confidence), scope=r.scope, note=r.note or "", prior_pct=prior,
                belief_pct=post if post is not None else prior, posterior_pct=post, n_obs=int(r.n_obs or 0),
                active=bool(r.active))


def list_factors(branch: str) -> dict:
    with lock(branch):
        store = get_store(branch)
        df = store.factors()
        return dict(factors=[_factor_row(r) for r in df.itertuples()] if len(df) else [],
                    library=owner.FACTOR_LIBRARY)


def add_factor(branch: str, name, start, end, effect_pct, confidence, scope, note) -> dict:
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if not name.strip():
        raise ForecastError("Give the factor a name.")
    if e < s:
        raise ForecastError("The end date is before the start date.")
    if not -90 <= effect_pct <= 300:
        raise ForecastError("Effect must be between -90% and +300%.")
    if not 0 <= confidence <= 1:
        raise ForecastError("Confidence must be between 0 and 1.")
    with lock(branch):
        store, eng, info = open_engine(branch)
        cats = {p["category"] for p in info["products"] if p["status"] == "tracked"}
        if scope not in ("all", "") and scope not in cats:
            raise ForecastError(f"Scope must be 'all' or one of: {', '.join(sorted(cats))}.")
        fid = store.add_factor(name.strip(), s.date(), e.date(), effect_pct, confidence, scope or "all", note or "")
        eng.refit()
        changes = _recompute_beliefs(eng, store)
        return py(dict(id=fid, belief_changes=changes))


def delete_factor(branch: str, fid: int) -> bool:
    with lock(branch):
        store, eng, _ = open_engine(branch)
        df = store.factors()
        if not len(df) or int(fid) not in set(df["id"].astype(int)):
            return False
        store.delete_factor(fid)
        eng.refit()
        return True


def list_rivals(branch: str) -> list[dict]:
    with lock(branch):
        df = get_store(branch).competitor_events()
        return [dict(id=int(r.id), rival=r.rival, start=py(r.start), end=py(r.end), discount_pct=float(r.discount_pct),
                     note=r.note or "") for r in df.itertuples()] if len(df) else []


def add_rival(branch: str, rival, start, end, discount_pct, note="") -> int:
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if e < s:
        raise ForecastError("The end date is before the start date.")
    if not 0 < discount_pct <= 90:
        raise ForecastError("Discount must be between 1% and 90%.")
    with lock(branch):
        store, eng, _ = open_engine(branch)
        rid = store.add_competitor_event(rival.strip() or "Rival", s.date(), e.date(), discount_pct, note or "")
        eng.refit()
        return rid


def delete_rival(branch: str, rid: int) -> bool:
    with lock(branch):
        store, eng, _ = open_engine(branch)
        df = store.competitor_events()
        if not len(df) or int(rid) not in set(df["id"].astype(int)):
            return False
        store.delete_competitor_event(rid)
        eng.refit()
        return True


# ----------------------------------------------------------------------------- scorecard
def verdict(m: dict) -> list[dict]:
    """Structured mirror of foresight.scorecard.verdict (same thresholds) so the UI can translate it."""
    if not m:
        return [dict(status="info", code="empty", params={})]
    out = []
    if m["n"] < 7:
        out.append(dict(status="info", code="few_days", params=dict(n=m["n"])))
    mp = m["mape"]
    out.append(dict(status="good" if mp < 0.10 else "warn" if mp < 0.18 else "bad",
                    code="mape_tight" if mp < 0.10 else "mape_ok" if mp < 0.18 else "mape_loose", params=dict(mape=mp)))
    if abs(m["bias"]) > 0.04:
        out.append(dict(status="warn", code="bias_under" if m["bias"] > 0 else "bias_over", params=dict(bias=m["bias"])))
    cov = m["coverage"]
    out.append(dict(status="good" if 0.65 <= cov <= 0.95 else "warn",
                    code="cov_good" if 0.65 <= cov <= 0.95 else "cov_over" if cov < 0.65 else "cov_wide", params=dict(cov=cov)))
    if "skill" in m:
        out.append(dict(status="good" if m["skill"] > 0.1 else "warn", code="skill_lower" if m["skill"] > 0 else "skill_higher",
                        params=dict(skill=m["skill"])))
    if "uplift_total" in m:
        out.append(dict(status="good" if m["uplift_total"] > 0 else "warn", code="uplift",
                        params=dict(total=m["uplift_total"], pct=m["uplift_pct"])))
    return out


def scorecard_payload(branch: str) -> dict:
    with lock(branch):
        store, eng, _ = open_engine(branch)
        df, m = scorecard.evaluate(store, eng)
        rows = records(df, ["date", "actual", "point", "lo80", "hi80", "naive", "kind", "err_pct", "in80", "profit_rec", "profit_flat"]) if len(df) else []
        return py(dict(metrics=m, rows=rows, verdict=verdict(m), verdict_en=[dict(status=s, text=t) for s, t in scorecard.verdict(m)],
                       actuals=source_counts(store)))


# ----------------------------------------------------------------------------- trends
def trends_payload(branch: str) -> dict:
    with lock(branch):
        store, eng, _ = open_engine(branch)
        day, payload = store.get_trends(eng.today.date()), None
        payload = day or store.latest_trends()[1]
        fresh = bool(day)
        if payload:
            scores, source, pday, heads = payload["scores"], payload["source"], payload["day"], payload.get("headlines", [])
        else:
            scores = trends.assumed_scores(eng.products, eng.festivals, eng.today.date())
            source, pday, heads = "assumed", None, []
        rows = [dict(product=k, score=float(v), boost_pct=(trends.boost(float(v)) - 1) * 100) for k, v in scores.items()]
        rows.sort(key=lambda r: -r["score"])
        return py(dict(day=pday, fresh=fresh, source=source, scores=rows, headlines=heads))


def refresh_trends(branch: str, force: bool = False) -> dict:
    with lock(branch):
        store, eng, _ = open_engine(branch)
    # the web search can be slow: do it outside the lock
    payload = trends.refresh(store, eng.profile, eng.festivals, eng.today.date(), force=force)
    return dict(day=payload["day"], source=payload["source"], n_results=payload["n_results"])


# ----------------------------------------------------------------------------- setup: profile, products, festivals, demo
PROFILE_FIELDS = dict(business_name=str, income_key=str, n_competitors=int, comp_price_idx=float, base_orders=float,
                      avg_ticket=float, surge_cap=float, discount_floor=float, use_live_weather=bool)
RANGES = dict(n_competitors=(0, 50), comp_price_idx=(0.5, 1.5), base_orders=(1, 100000), avg_ticket=(1, 1000000),
              surge_cap=(0, 0.5), discount_floor=(0.5, 1.0))


def get_profile(branch: str) -> dict:
    with lock(branch):
        store, eng, info = open_engine(branch)
        p = eng.profile
        return py(dict(
            profile={k: p.get(k) for k in PROFILE_FIELDS} | dict(location=p["location"], assumptions=p["assumptions"]),
            income_levels={k: dict(label=v["label"]) for k, v in fc.INCOME_LEVELS.items()},
            categories=CATEGORIES, products=info["products"], skipped=info["skipped"],
            live_weather_allowed=live_allowed()))


def update_profile(branch: str, patch: dict) -> dict:
    with lock(branch):
        store = get_store(branch)
        p = store.get_profile()
        for k, v in patch.items():
            if v is None:
                continue
            if k == "location":
                name = str(v.get("name", "")).strip()
                lat, lon = float(v.get("lat")), float(v.get("lon"))
                if not name or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ForecastError("Location needs a name and valid latitude/longitude.")
                p["location"] = dict(name=name, lat=lat, lon=lon)
            elif k == "assumptions":
                a = dict(p["assumptions"])
                for ak, lo, hi in (("growth_pct_month", -10, 20), ("sentiment_pct", -50, 50), ("prior_strength", 1, 200)):
                    if ak in v and v[ak] is not None:
                        x = float(v[ak])
                        if not lo <= x <= hi:
                            raise ForecastError(f"{ak} must be between {lo} and {hi}.")
                        a[ak] = x
                p["assumptions"] = a
            elif k in PROFILE_FIELDS:
                typ = PROFILE_FIELDS[k]
                val = typ(v) if typ is not bool else bool(v)
                if k == "income_key" and val not in fc.INCOME_LEVELS:
                    raise ForecastError("Unknown income level.")
                if k in RANGES and not RANGES[k][0] <= val <= RANGES[k][1]:
                    raise ForecastError(f"{k} must be between {RANGES[k][0]} and {RANGES[k][1]}.")
                if k == "use_live_weather" and val and not live_allowed():
                    val = False
                p[k] = val
        store.set_profile(p)
    return get_profile(branch)


PRODUCT_FIELDS = ("category", "cost", "price", "elasticity", "essential", "perishable", "temp_sens", "rain_sens", "keywords", "tracked")


def update_product(branch: str, name: str, patch: dict) -> dict:
    with lock(branch):
        store = get_store(branch)
        sync_products(branch, store)
        cat = store.get_kv("catalogue", {})
        if name not in cat:
            raise KeyError(name)
        s = cat[name]
        for k, v in patch.items():
            if v is None or k not in PRODUCT_FIELDS:
                continue
            if k == "category" and v not in CATEGORIES:
                raise ForecastError(f"Category must be one of: {', '.join(CATEGORIES)}.")
            if k in ("cost", "price") and float(v) <= 0:
                raise ForecastError("Price and cost must be above zero.")
            if k == "elasticity":
                if not 0.2 <= float(v) <= 6:
                    raise ForecastError("Elasticity must be between 0.2 and 6.")
                s["elasticity_auto"] = False
            if k in ("temp_sens", "rain_sens") and not -1 <= float(v) <= 1:
                raise ForecastError(f"{k} must be between -1 and 1.")
            s[k] = v if isinstance(v, (str, bool)) else float(v)
        if float(s["cost"]) >= float(s["price"]):
            raise ForecastError("Cost must be below price.")
        if any(k in patch and patch[k] is not None for k in ("price", "cost")):
            s["assumed_prices"] = False
        if patch.get("elasticity_auto") is True:
            s["elasticity_auto"] = True
        cat[name] = s
        store.set_kv("catalogue", cat)
        info = sync_products(branch, store)
        return py(next(p for p in info["products"] if p["name"] == name))


def list_festivals(branch: str) -> dict:
    with lock(branch):
        store = get_store(branch)
        with db() as c:
            ld = [dict(r) for r in c.execute("SELECT name, date, surge_multiplier, supplier_blackout_days FROM festivals ORDER BY date")]
        return py(dict(festivals=store.festivals(), categories=CATEGORIES, livingdoc_festivals=ld))


def replace_festivals(branch: str, rows: list[dict]) -> int:
    clean = []
    for r in rows:
        name = str(r.get("name", "")).strip()
        try:
            s, e = pd.Timestamp(r["start"]).date(), pd.Timestamp(r.get("end") or r["start"]).date()
        except Exception as ex:
            raise ForecastError(f"Bad date in festival {name!r}.") from ex
        if not name or e < s:
            raise ForecastError(f"Festival {name or '(unnamed)'}: needs a name and end on/after start.")
        lift = float(r.get("lift", 0.3))
        if not -0.9 <= lift <= 3:
            raise ForecastError(f"Festival {name}: lift must be between -0.9 and 3.")
        aff = {k: float(v) for k, v in (r.get("aff") or {}).items() if k in CATEGORIES}
        clean.append(dict(name=name, start=s.isoformat(), end=e.isoformat(), lift=lift, lead=int(r.get("lead", 3)),
                          tail=int(r.get("tail", 1)), kind=r.get("kind", "festival"), aff=aff))
    with lock(branch):
        store = get_store(branch)
        store.replace_festivals(clean)
    return len(clean)


def reset_festivals(branch: str) -> int:
    return replace_festivals(branch, fc.FESTIVALS_DEFAULT)


def load_demo(branch: str, days: int = 21) -> dict:
    days = max(7, min(int(days), 60))
    with lock(branch):
        store, eng, _ = open_engine(branch)
        have = {r.date.date() for r in store.actuals().itertuples()} if len(store.actuals()) else set()
        target = {(eng.today - pd.Timedelta(days=i)).date() for i in range(1, days + 1)}
        if have & target:
            raise ForecastError("Some of those days already have logged sales. Clear demo/imported days first, so simulated "
                                "numbers never overwrite real ones.")
        info = fdemo.load_demo(eng, days)
        return py(dict(days=days, hidden_event_dates=info["event_dates"]))


def clear_demo(branch: str) -> int:
    return clear_actuals(branch, "demo")


def learned(branch: str) -> list[dict]:
    with lock(branch):
        store, eng, _ = open_engine(branch)
        df = eng.learned_vs_prior()
        return [dict(driver=r["driver"], assumed=float(r["assumed (prior)"]), learned=float(r["learned now"])) for _, r in df.iterrows()]


# ----------------------------------------------------------------------------- daily job
def daily_refresh(force: bool = False, auto_import: bool | None = None) -> dict:
    """Once a day: refresh web trends, import yesterday's LivingDoc numbers, freeze today's forecast per branch."""
    import os
    if auto_import is None:
        auto_import = os.environ.get("LIVINGDOC_FORESIGHT_AUTOIMPORT", "1") == "1"
    with db() as c:
        branches = [r["name"] for r in c.execute("SELECT name FROM branches ORDER BY name")]
    summary = {}
    for b in branches:
        res = {}
        try:
            res["trends"] = refresh_trends(b, force=force)
            if auto_import:
                res["imported"] = import_livingdoc(b, 3)["imported"]
            f = forecast(b, 28, 0)
            res["forecast_days"] = len(f["days"])
        except ForecastError as e:
            res["skipped"] = str(e)
        except Exception as e:      # one branch failing must not stop the others
            log.exception("daily refresh failed for %s", b)
            res["error"] = str(e)
        summary[b] = res
    with db() as c:
        meta_set(c, "foresight_last_daily", today().isoformat())
    return summary


def daily_if_due() -> bool:
    """Called from the worker loop; starts the daily job in its own thread at most once per day."""
    with db() as c:
        last = meta_get(c, "foresight_last_daily", "")
    if last == today().isoformat() or _DAILY_RUNNING.is_set():
        return False
    _DAILY_RUNNING.set()

    def _go():
        try:
            daily_refresh()
        except Exception:
            log.exception("daily foresight refresh failed")
        finally:
            _DAILY_RUNNING.clear()

    threading.Thread(target=_go, name="foresight-daily", daemon=True).start()
    return True
