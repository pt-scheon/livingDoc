"""How would you ever know afterwards whether you decided well?

Three honest tests, all computed only from forecasts that were *logged before* the day happened:

1. Accuracy      — MAPE and bias of the forecast.
2. Calibration   — did ~80% of days fall inside the 80% range?  (A forecast that is always "sure" is useless.)
3. Skill & value — is the AI better than the owner's gut-feel baseline (average of the last 7 days)?
                   and would the recommended prices have earned more than flat prices, given what really happened?
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import pricing


def evaluate(store, engine) -> tuple[pd.DataFrame, dict]:
    act = store.actuals()
    flog = store.forecast_log()
    if not len(act) or not len(flog):
        return pd.DataFrame(), {}
    rows = []
    act = act.sort_values("date").reset_index(drop=True)
    prof = engine.profile
    trend = engine.trend_scores()
    for i, a in act.iterrows():
        cand = flog[(flog["date"] == a["date"]) & (flog["issued_on"] < a["date"])]
        if not len(cand):
            continue
        f = cand.sort_values("issued_on").iloc[-1]
        prev = act[act["date"] < a["date"]].tail(7)["orders"]
        naive = float(prev.mean()) if len(prev) >= 3 else np.nan
        rec = json.loads(f["rec_json"]) if f["rec_json"] else {}
        scale = a["orders"] / max(f["point"], 1e-9)
        up = np.nan
        prof_rec = prof_flat = np.nan
        if rec.get("D") and rec.get("mult"):
            realized = {k: v * scale for k, v in rec["D"].items()}
            ctx = rec.get("ctx", {"idx": 1.0, "promo": 0.0})
            prof_rec, prof_flat = pricing.evaluate_multipliers(
                engine.products, realized, rec["mult"], ctx["idx"] * scale, ctx["promo"], engine.income["price_sens"], trend)
        rows.append(dict(date=a["date"], actual=a["orders"], point=f["point"], lo80=f["lo80"], hi80=f["hi80"],
                         naive=naive, kind=f["kind"], issued_on=f["issued_on"],
                         err_pct=(a["orders"] - f["point"]) / max(f["point"], 1e-9),
                         in80=bool(f["lo80"] <= a["orders"] <= f["hi80"]),
                         profit_rec=prof_rec, profit_flat=prof_flat))
    df = pd.DataFrame(rows)
    if not len(df):
        return df, {}
    ape = df["err_pct"].abs()
    m = dict(n=len(df), mape=float(ape.mean()), bias=float(df["err_pct"].mean()), coverage=float(df["in80"].mean()))
    v = df.dropna(subset=["naive"])
    if len(v) >= 3:
        mae_ai = float((v["actual"] - v["point"]).abs().mean())
        mae_naive = float((v["actual"] - v["naive"]).abs().mean())
        m["skill"] = 1 - mae_ai / max(mae_naive, 1e-9)
        m["mae_ai"], m["mae_naive"] = mae_ai, mae_naive
    pv = df.dropna(subset=["profit_rec"])
    if len(pv):
        m["uplift_total"] = float((pv["profit_rec"] - pv["profit_flat"]).sum())
        m["uplift_pct"] = float((pv["profit_rec"].sum() / max(pv["profit_flat"].sum(), 1e-9)) - 1)
    return df, m


def verdict(m: dict) -> list[tuple[str, str]]:
    """Plain-language grading: list of (status, sentence)."""
    out = []
    if not m:
        return [("info", "Log a few real days (or load the demo) and this page will grade the AI against reality.")]
    if m["n"] < 7:
        out.append(("info", f"Only {m['n']} graded day(s) so far — treat everything below as a hint, not a verdict."))
    out.append(("good" if m["mape"] < 0.10 else "warn" if m["mape"] < 0.18 else "bad",
                f"Average miss: {m['mape']:.1%}. " + ("Tight enough to plan stock around." if m["mape"] < 0.10 else "Useful, but keep a safety buffer." if m["mape"] < 0.18 else "Too loose — add factors you know about.")))
    if abs(m["bias"]) > 0.04:
        out.append(("warn", f"Bias {m['bias']:+.1%}: the AI is systematically {'under' if m['bias'] > 0 else 'over'}-predicting. It is correcting, but check for a missing factor."))
    cov = m["coverage"]
    out.append(("good" if 0.65 <= cov <= 0.95 else "warn",
                f"{cov:.0%} of days landed inside the 80% range (ideal ≈ 80%). " + ("Well calibrated." if 0.65 <= cov <= 0.95 else "Over-confident bands." if cov < 0.65 else "Bands are wider than they need to be.")))
    if "skill" in m:
        s = m["skill"]
        out.append(("good" if s > 0.1 else "warn", f"Versus gut feel (last-7-day average): {s:+.0%} {'lower' if s > 0 else 'higher'} error."))
    if "uplift_total" in m:
        out.append(("good" if m["uplift_total"] > 0 else "warn",
                    f"Recommended prices vs. flat prices, using what really happened: {m['uplift_total']:+,.0f} ₹ ({m['uplift_pct']:+.1%}) profit."))
    return out
