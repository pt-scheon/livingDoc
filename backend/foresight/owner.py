"""Owner knowledge → model.

The owner can add *factors* the data cannot see ("cousin's wedding on our street, +25% for 3 days").
How the AI accommodates them:

1. A factor is treated as a prior belief: effective effect = stated effect × (0.4 + 0.6 × confidence).
2. It enters the forecast as an offset in log-demand, widening the uncertainty band by how unsure the owner is.
3. Once real days inside the factor's window are logged, the AI compares reality with what it
   would have predicted *without* the factor, and updates its belief (Bayesian shrinkage):

       posterior = (k · prior + n · observed) / (k + n),   k = 2 + 6 · confidence  pseudo-days

   So a confident owner needs more contradicting evidence to be overruled; a hunch is corrected quickly.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# Typical effects for common local factors (starting suggestions — the owner can change them).
FACTOR_LIBRARY = [
    dict(name="Wedding / big family event nearby", keywords="wedding,shaadi,reception,function,barat", effect_pct=25, scope="all",
         why="Guests and caterers nearby raise footfall for a few days."),
    dict(name="School / college vacation", keywords="vacation,holiday,school,college,summer break,diwali break", effect_pct=-10, scope="all",
         why="Fewer student & parent trips; family spending shifts to leisure."),
    dict(name="Exam season", keywords="exam,board,test season", effect_pct=-8, scope="all",
         why="Households cut outings; snacks & stationery up, others down."),
    dict(name="Road closure / metro construction", keywords="road,closure,construction,metro,diversion,digging,flyover", effect_pct=-18, scope="all",
         why="Access friction cuts walk-in and vehicle traffic."),
    dict(name="New competitor opening nearby", keywords="new shop,competitor,opening,rival,mall,store opens", effect_pct=-15, scope="all",
         why="Opening offers pull customers for 1-2 weeks, then partly return."),
    dict(name="Cricket / big match", keywords="cricket,match,ipl,world cup,final", effect_pct=12, scope="snacks",
         why="Snacks and beverages spike during match evenings; other footfall dips."),
    dict(name="Local strike / bandh", keywords="strike,bandh,curfew,protest,shutdown", effect_pct=-40, scope="all",
         why="Shops and transport close; demand shifts to neighbouring days."),
    dict(name="Local fair / mela / exhibition", keywords="fair,mela,exhibition,expo,carnival,garba night", effect_pct=30, scope="all",
         why="Crowds bring walk-in demand."),
    dict(name="Viral social-media mention", keywords="viral,reel,instagram,influencer,trending,youtube,blogger", effect_pct=35, scope="all",
         why="Short-lived spike that decays in days."),
    dict(name="New office / housing society occupied", keywords="office,society,apartment,occupied,flats,campus", effect_pct=15, scope="all",
         why="A durable new customer base nearby."),
    dict(name="Salary delay at a nearby employer", keywords="salary delay,late salary,layoff,factory closed,bonus delayed", effect_pct=-20, scope="all",
         why="Spending waits for the paycheck."),
    dict(name="Extra bonus / DA arrears paid", keywords="bonus,arrears,da hike,incentive,pay commission", effect_pct=18, scope="all",
         why="Windfall income lifts discretionary buying."),
    dict(name="Heatwave / cold snap advisory", keywords="heatwave,heat wave,cold wave,fog,storm,cyclone,alert", effect_pct=-12, scope="all",
         why="People stay indoors; delivery and cold/hot beverages shift."),
    dict(name="Power cut / water problem in area", keywords="power cut,blackout,water supply,outage", effect_pct=-10, scope="all",
         why="Reduced evening footfall."),
]


def suggest_from_text(text: str, top: int = 3) -> list[dict]:
    """Match free text to the factor library (keyword overlap). Returns [] if nothing matches —
    in that case the owner types the effect themselves and the AI learns it from data."""
    t = text.lower()
    scored = []
    for f in FACTOR_LIBRARY:
        hits = sum(1 for kw in f["keywords"].split(",") if re.search(r"\b" + re.escape(kw.strip()) + r"\b", t))
        if hits:
            scored.append((hits, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:top]]


def prior_effect(effect_pct: float, confidence: float) -> float:
    """Effective prior effect as a fraction (e.g. 0.25 → +25% scaled by confidence)."""
    return float(effect_pct) / 100.0 * (0.4 + 0.6 * float(confidence))


def current_effect(row) -> float:
    """Posterior if the AI has learned one, otherwise the confidence-scaled prior."""
    post = row.posterior_pct if hasattr(row, "posterior_pct") else row.get("posterior_pct")
    if post is not None and not (isinstance(post, float) and np.isnan(post)):
        return float(post) / 100.0
    return prior_effect(row.effect_pct, row.confidence)


def factor_effects(dates: pd.DatetimeIndex, factors: pd.DataFrame, categories: list[str],
                   cat_weights: dict[str, float]) -> dict:
    """Per-date owner effects.

    Returns dict with
      store_frac : Series  — total store-level fractional effect (Σ over factors, weighted by category share)
      var        : Series  — extra log-variance from owner uncertainty
      per_cat    : DataFrame date × category fractional effect
      by_factor  : dict name → Series store-level fractional effect (for the explanation chart)
    """
    per_cat = pd.DataFrame(0.0, index=dates, columns=sorted(set(categories)))
    var = pd.Series(0.0, index=dates)
    by_factor: dict[str, pd.Series] = {}
    if factors is not None and len(factors):
        for f in factors.itertuples():
            if not getattr(f, "active", 1):
                continue
            m = (dates >= f.start) & (dates <= f.end)
            if not m.any():
                continue
            eff = current_effect(f)
            cats = per_cat.columns if f.scope in ("all", "", None) else [f.scope] if f.scope in per_cat.columns else []
            for c in cats:
                per_cat.loc[m, c] += eff
            w = sum(cat_weights.get(c, 0.0) for c in cats)
            s = pd.Series(0.0, index=dates)
            s[m] = eff * w
            name = f.name
            while name in by_factor:
                name += "*"
            by_factor[name] = s
            unsure = (1 - float(f.confidence)) * abs(eff) * 0.5
            var[m] += (unsure * w) ** 2
    store_frac = sum((by_factor[k] for k in by_factor), pd.Series(0.0, index=dates))
    return dict(store_frac=store_frac, var=var, per_cat=per_cat, by_factor=by_factor)


def update_posteriors(store, pred_without: pd.Series, actual: pd.DataFrame, cat_weights: dict[str, float]) -> list[dict]:
    """Learn each factor's real effect from logged days inside its window.

    pred_without : Series (index=date) model prediction (orders) with *no owner factors*
    actual       : DataFrame with `date`, `orders`
    Returns a list of changes for display.
    """
    changes = []
    if actual is None or not len(actual):
        return changes
    act = actual.set_index("date")["orders"]
    factors = store.factors()
    for f in factors.itertuples():
        days = [d for d in pd.date_range(f.start, f.end) if d in act.index and d in pred_without.index]
        if not days:
            continue
        w = 1.0 if f.scope in ("all", "", None) else cat_weights.get(f.scope, 0.2)
        # Other factors overlapping these days are held at their current effect
        ratios = []
        for d in days:
            others = 0.0
            for g in factors.itertuples():
                if g.id != f.id and g.active and g.start <= d <= g.end:
                    others += current_effect(g) * (1.0 if g.scope in ("all", "", None) else cat_weights.get(g.scope, 0.2))
            base = pred_without.loc[d] * (1 + others)
            ratios.append(act.loc[d] / max(base, 1e-9) - 1.0)
        n = len(ratios)
        observed = float(np.mean(ratios)) / max(w, 1e-6)
        prior = prior_effect(f.effect_pct, f.confidence)
        k = 2 + 6 * float(f.confidence)
        post = (k * prior + n * observed) / (k + n)
        post = float(np.clip(post, -0.8, 2.0))
        old = f.posterior_pct if f.posterior_pct is not None and not pd.isna(f.posterior_pct) else prior * 100
        store.update_factor(f.id, posterior_pct=post * 100, n_obs=n)
        changes.append(dict(factor=f.name, you_said_pct=float(f.effect_pct), ai_belief_pct=post * 100,
                            observed_pct=observed * 100, days_seen=n, previous_belief_pct=float(old)))
    return changes
