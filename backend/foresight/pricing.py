"""Surge pricing, sales and how-much-to-buy — as an explicit optimisation, not a rule of thumb.

Setup
-----
* The owner's current price is assumed right on a *normal* day.  Elasticity is therefore calibrated from the
  margin (Lerner rule: e = price / (price − cost)) unless the owner overrides it.
* Customers are less price-sensitive on busy, high-spend days and more sensitive on lean days:

      e_today = e · clip(1 − κ·(demand_index − 1), 0.65, 1.35) · (1 + 0.6·rival_promo) · (1 − 0.1·trend)

  κ is larger for lower-income areas (they shop around more when money is tight).
* For every product and day we search price multipliers m and maximise profit:

      demand(m) = D · m^(−e_today)         D = forecast units at the normal price
      sold      = min(capacity, demand(m))
      profit(m) = (price·m − cost)·sold + halo·sold          (halo only for a trending "traffic driver")

Where surges and sales come from
* SURGE: busy day → lower elasticity → higher optimal price; and when forecast demand exceeds capacity a higher price
  clears the shelf at better margin instead of an early sell-out.
* SALE: lean day or a rival promotion → higher elasticity; or a trending item used as a footfall driver.

Guardrails (all owner-editable): essentials are never surged, a global surge cap, minimum margin, a sale floor,
and a ceiling relative to what rivals charge.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import competition

GRID = np.round(np.arange(0.60, 1.401, 0.01), 2)


def elasticity_today(base_e: float, index: float, promo: float, trend_score: float, income_price_sens: float) -> float:
    kappa = 0.50 * income_price_sens
    busy = float(np.clip(1.0 - kappa * (index - 1.0), 0.65, 1.35))
    e = base_e * busy * (1.0 + 0.6 * promo) * (1.0 - 0.10 * min(max(trend_score, 0.0), 1.0))
    return float(max(0.35, e))


def _profit(m, price, cost, D, e, capacity, halo):
    p = price * m
    sold = np.minimum(capacity, D * m ** (-e))
    return (p - cost) * sold + halo * sold, sold


def _round_price(p: float) -> float:
    return round(p * 2) / 2 if p < 50 else float(round(p))


def recommend(prod: dict, D: float, index: float, promo: float, income_price_sens: float, n_comp: int,
              comp_price_idx: float, surge_cap: float, discount_floor: float, trend_score: float = 0.0,
              sigma: float = 0.12) -> dict:
    price, cost = float(prod["price"]), float(prod["cost"])
    cap = float(prod["supply_per_day"])
    essential = bool(prod.get("essential", False))
    perishable = bool(prod.get("perishable", False))
    e = elasticity_today(float(prod["elasticity"]), index, promo, trend_score, income_price_sens)
    # "Traffic driver": a trending, non-essential item on a weak day / rival-promo day is worth a halo
    driver = (trend_score >= 0.6) and (not essential) and (index < 0.97 or promo > 0.05)
    halo = 0.35 * (price - cost) if driver else 0.0

    lo = max(discount_floor, (cost * 1.03) / price)
    hi = 1.0 if essential else min(1.0 + surge_cap, competition.surge_ceiling(comp_price_idx, n_comp))
    if essential:
        lo = max(lo, 0.90)
    if driver:
        lo = max(lo, 0.88)          # a footfall-driver offer is a nudge, not a fire sale
    hi = max(hi, lo)
    grid = GRID[(GRID >= lo - 1e-9) & (GRID <= hi + 1e-9)]
    if len(grid) == 0 or not (grid == 1.0).any():
        grid = np.unique(np.r_[grid, min(max(1.0, lo), hi)])

    prof, _ = _profit(grid, price, cost, D, e, cap, halo)
    best = prof.max()
    near = np.where(prof >= best - abs(best) * 0.004 - 1e-9)[0]      # near-optimal → prefer the price closest to normal
    m = float(grid[near[np.argmin(np.abs(grid[near] - 1.0))]])

    new_price = _round_price(price * m)
    m_eff = new_price / price
    prof_final, sold_final = _profit(m_eff, price, cost, D, e, cap, 0.0)
    base_prof, base_sold = _profit(1.0, price, cost, D, e, cap, 0.0)
    sold_final = float(sold_final)

    label = "SURGE" if m_eff >= 1.02 else "SALE" if m_eff <= 0.98 else "HOLD"
    over = D / max(cap, 1e-9)
    # reason_code / reason_params let a UI translate the explanation; `reason` stays the English text.
    flags = []
    params = dict(name=prod["name"], pct=abs(m_eff - 1), demand=D, cap=cap, idx=index, score=trend_score)
    if label == "SURGE" and D > cap:
        code = "surge_capacity"
        reason = (f"Forecast demand {D:.0f} exceeds capacity {cap:.0f}: +{m_eff - 1:.0%} clears the shelf at better "
                  f"margin instead of selling out early.")
    elif label == "SURGE":
        code = "surge_busy"
        reason = (f"Busy, high-spend day (demand {index:.2f}× typical): shoppers are less price-sensitive, "
                  f"so +{m_eff - 1:.0%} earns more per sale.")
    elif label == "SALE" and driver:
        code = "sale_driver_rival" if promo > 0.05 else "sale_driver_lean"
        reason = (f"'{prod['name']}' is trending (score {trend_score:.1f}) on a "
                  f"{'rival-promo' if promo > 0.05 else 'lean'} day: a {abs(m_eff - 1):.0%} offer pulls in basket sales.")
    elif label == "SALE":
        code = "sale_rival" if promo > 0.05 else "sale_lean"
        reason = (f"{'Rival promotion running' if promo > 0.05 else 'Lean, price-sensitive day'} "
                  f"(demand {index:.2f}× typical): a {abs(m_eff - 1):.0%} sale protects volume.")
    else:
        code = "hold"
        reason = "Demand is normal for this price: hold."
    if essential and label != "SALE":
        reason += " Essential item — surge disabled."
        flags.append("essential")
    if label == "SURGE" and m_eff >= hi - 0.005 and not essential and hi < 1.0 + surge_cap - 1e-9:
        reason += " Capped by the rival price ceiling."
        flags.append("rival_ceiling")
    elif label == "SURGE" and m_eff >= 1.0 + surge_cap - 0.005:
        reason += " At your surge cap."
        flags.append("surge_cap")

    # Newsvendor prep quantity at the chosen price (what to buy / make)
    margin = price * m_eff - cost
    waste_rate = 0.80 if perishable else 0.02
    cr = margin / max(margin + waste_rate * cost, 1e-9)
    z = _norm_ppf(min(max(cr, 0.05), 0.97))
    D_at = D * m_eff ** (-e)
    prep = D_at * math.exp(z * sigma)
    return dict(
        mult=round(m_eff, 3), price=new_price, label=label, units=sold_final, revenue=sold_final * new_price,
        profit=float(prof_final), base_profit=float(base_prof), uplift=float(prof_final - base_prof),
        demand_at_base=float(D), supply=cap, prep=float(prep), elasticity=e, index=float(index),
        promo=float(promo), reason=reason, reason_code=code, reason_flags=flags, reason_params=params,
    )


def _norm_ppf(p: float) -> float:
    """Acklam's rational approximation of the inverse normal CDF (no SciPy needed)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - plow:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def plan(dates: pd.DatetimeIndex, products: list[dict], demand: dict[str, pd.Series], trend: dict[str, float],
         store_index: pd.Series, rival_promo: pd.Series, n_comp: int, income_price_sens: float,
         comp_price_idx: float, surge_cap: float, discount_floor: float, sigma: pd.Series) -> pd.DataFrame:
    """The full price/sale/prep playbook: one row per (date, product)."""
    rows = []
    for d in dates:
        for p in products:
            r = recommend(p, float(demand[p["name"]].loc[d]), float(store_index.loc[d]), float(rival_promo.loc[d]),
                          income_price_sens, n_comp, comp_price_idx, surge_cap, discount_floor,
                          trend.get(p["name"], 0.0), float(sigma.loc[d]))
            r.update(date=d, product=p["name"], category=p["category"], base_price=float(p["price"]))
            rows.append(r)
    return pd.DataFrame(rows)


def evaluate_multipliers(products: list[dict], realized_demand: dict[str, float], mults: dict[str, float],
                         realized_index: float, promo: float, income_price_sens: float,
                         trend: dict[str, float]) -> tuple[float, float]:
    """Profit of the recommended multipliers vs. flat pricing under REALISED demand (for the scorecard)."""
    p_rec = p_flat = 0.0
    for p in products:
        e = elasticity_today(float(p["elasticity"]), realized_index, promo, trend.get(p["name"], 0.0), income_price_sens)
        D = realized_demand[p["name"]]
        m = mults.get(p["name"], 1.0)
        a, _ = _profit(m, float(p["price"]), float(p["cost"]), D, e, float(p["supply_per_day"]), 0.0)
        b, _ = _profit(1.0, float(p["price"]), float(p["cost"]), D, e, float(p["supply_per_day"]), 0.0)
        p_rec += float(a)
        p_flat += float(b)
    return p_rec, p_flat
