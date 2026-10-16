"""Demo mode: simulate the last N days of REAL sales from a hidden market that differs from the AI's assumptions.

The hidden world is stronger on paydays, much more rain-sensitive, busier on Saturdays and contains one event the
model cannot know about (a college fest, +30% for 3 days).  Each simulated day is forecast by the AI BEFORE it is
learned (prequential evaluation), so the Scorecard shows honest out-of-sample accuracy and you can watch the AI's
beliefs move — then add the college fest as an owner factor and watch the AI accommodate it.

Rows are tagged source='demo' so they can be cleared with one click.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .model import FEATURES, design

HIDDEN_EVENT_OFFSETS = (9, 8, 7)     # days before today
HIDDEN_EVENT_LIFT = 0.30


def load_demo(engine, days: int = 21, seed: int = 5) -> dict:
    rng = np.random.default_rng(seed)
    today = engine.today
    dates = pd.date_range(today - pd.Timedelta(days=days), today - pd.Timedelta(days=1))
    store = engine.store
    # frozen reference: the model's beliefs at the start
    start_beta = dict(engine.model.beta)
    hidden = dict(start_beta)
    hidden["payday"] *= 1.7
    hidden["rain"] *= 2.2
    hidden["festival"] *= 1.2
    hidden["dow_Sat"] += 0.06
    hidden["dow_Sun"] += 0.04
    hidden["trend"] = 0.0
    feats = engine.raw_features(dates)
    X = design(feats)
    xbar = engine.model.xbar
    base = float(np.exp(engine.model.typical_log()))
    mu = np.log(base) + sum(hidden[k] * (X[k] - xbar[k]) for k in FEATURES)
    event_days = {today - pd.Timedelta(days=o) for o in HIDDEN_EVENT_OFFSETS}
    changes = []
    for i, d in enumerate(dates):
        orders = float(np.exp(mu.iloc[i] + rng.normal(0, 0.06)))
        if d in event_days:
            orders *= 1 + HIDDEN_EVENT_LIFT
        orders = max(5.0, round(orders))
        rev = orders * float(engine.profile["avg_ticket"]) * rng.uniform(0.95, 1.05)
        changes = engine.log_actual(d, orders, round(rev), note="demo", source="demo")
    return dict(days=days, event_dates=sorted(d.date() for d in event_days))


def clear_demo(engine):
    act = engine.store.actuals()
    if len(act):
        for r in act[act["source"] == "demo"].itertuples():
            engine.store.delete_actual(r.date.date())
    with engine.store.conn() as c:
        c.execute("DELETE FROM forecast_log WHERE kind='backcast'")
    engine.refit()
