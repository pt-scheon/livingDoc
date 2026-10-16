"""Foresight's own unit tests (model, pricing, owner learning, scorecard, trends), run against the vendored package."""
import datetime as dt
import numpy as np
import pandas as pd
import pytest

from foresight import calendar_feats, config, demo, owner, paycheck, pricing, scorecard, trends
from foresight.engine import Engine
from foresight.model import DemandModel, FEATURES, design, prior_beta, training_weights
from foresight.store import Store

TODAY = "2026-10-17"


@pytest.fixture()
def store():
    return Store(":memory:")


@pytest.fixture()
def engine(store):
    return Engine(store, today=TODAY)


# ---------------------------------------------------------------- paycheck
def test_wave_is_normalised_to_one_on_average():
    mix = config.INCOME_LEVELS["middle"]["mix"]
    df = paycheck.spend_wave(dt.date(2026, 3, 1), dt.date(2026, 8, 31), mix)
    assert 0.9 < df["wave_idx"].mean() < 1.1


def test_weekend_payday_shifts_to_previous_working_day():
    # 1 Nov 2026 is a Sunday -> pay lands Friday 30 Oct, never on a weekend
    mix = {"govt": 1.0}
    events = paycheck.pay_events(dt.date(2026, 10, 25), dt.date(2026, 11, 5), mix)
    assert all(d.weekday() < 5 for d, _, _ in events)
    assert dt.date(2026, 10, 30) in {d for d, _, _ in events}


def test_low_income_has_weekly_saturday_pay():
    mix = config.INCOME_LEVELS["low"]["mix"]
    events = [d for d, s, _ in paycheck.pay_events(dt.date(2026, 10, 1), dt.date(2026, 10, 31), mix) if s == "wage"]
    assert events and all(d.weekday() == 5 for d in events)


def test_peak_days_are_spaced():
    mix = config.INCOME_LEVELS["middle"]["mix"]
    df = paycheck.spend_wave(dt.date(2026, 10, 17), dt.date(2026, 11, 30), mix)
    pk = paycheck.peak_days(df, 3, min_gap=4)
    assert len(pk) == 3 and all(abs((a - b).days) >= 4 for i, a in enumerate(pk) for b in pk[i + 1:])


# ---------------------------------------------------------------- festivals
def test_festival_kernel_shape():
    s = e = dt.date(2026, 11, 8)
    k = lambda d: calendar_feats.kernel(d, s, e, 1.0, 14, 4)
    assert k(s) == 1.0
    assert 0 < k(s - dt.timedelta(days=1)) < 1.0            # build-up
    assert k(s - dt.timedelta(days=3)) < k(s - dt.timedelta(days=1))
    assert k(s - dt.timedelta(days=30)) == 0.0
    assert k(s + dt.timedelta(days=1)) > 0                  # tail
    assert k(s + dt.timedelta(days=6)) < 0                  # hangover


# ---------------------------------------------------------------- model
def test_ridge_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    dates = pd.date_range("2026-01-01", periods=400)
    df = pd.DataFrame(index=dates)
    df["dow"] = dates.dayofweek
    df["payday"] = rng.normal(0, 0.5, len(df))
    df["festival"] = rng.uniform(0, 1, len(df))
    df["heat"] = rng.uniform(0, 2, len(df))
    df["rain"] = rng.uniform(0, 3, len(df))
    df["competition"] = rng.uniform(0, 1, len(df))
    df["trend"] = np.arange(len(df)) / 30.4
    X = design(df)
    truth = {k: 0.0 for k in FEATURES}
    truth.update(payday=0.4, festival=0.9, rain=-0.1, dow_Sat=0.2)
    y = 4.5 + sum(truth[k] * X[k] for k in FEATURES) + rng.normal(0, 0.05, len(X))
    m = DemandModel(prior_beta(0.3, 1.0), prior_strength=5).fit(X, y.to_numpy(), np.ones(len(X)))
    assert abs(m.beta["payday"] - 0.4) < 0.05
    assert abs(m.beta["festival"] - 0.9) < 0.07
    assert abs(m.beta["dow_Sat"] - 0.2) < 0.05
    assert abs(m.sigma - 0.05) < 0.02


def test_real_days_outweigh_assumed_days():
    w = training_weights(np.array([True, False]), 40)
    assert w[0] > 4 * w[1]


def test_bands_widen_with_horizon(engine):
    s = engine.model.sigma_h(np.array([0, 7, 28]))
    assert s[0] < s[1] < s[2]


# ---------------------------------------------------------------- forecast / engine
def test_engine_forecast_smoke(engine):
    fc = engine.forecast(28, 14)
    fut = fc[fc["is_future"]]
    assert len(fut) == 28 and (fut["point"] > 0).all()
    assert (fut["lo80"] < fut["point"]).all() and (fut["point"] < fut["hi80"]).all()
    # Diwali build-up must raise demand above a quiet mid-month day
    assert fut.loc["2026-11-06", "point"] > 1.5 * fut.loc["2026-10-23", "point"]


def test_explain_sums_to_forecast(engine):
    fc = engine.forecast(28, 14)
    eff = engine.explain("2026-11-06")
    implied = fc["typical"].iloc[0] * np.prod(1 + eff.values)
    assert abs(implied - fc.loc["2026-11-06", "point"]) / fc.loc["2026-11-06", "point"] < 0.02


def test_owner_factor_changes_forecast_and_widens_band(store, engine):
    base = engine.forecast(14, 7).loc["2026-10-20"]
    store.add_factor("Wedding next door", "2026-10-20", "2026-10-20", 40, 0.5)
    e2 = Engine(store, today=TODAY)
    new = e2.forecast(14, 7).loc["2026-10-20"]
    assert new["point"] > base["point"] * 1.15
    assert (new["hi80"] - new["lo80"]) / new["point"] > (base["hi80"] - base["lo80"]) / base["point"]


def test_weather_changes_forecast(engine, monkeypatch):
    from foresight import weather
    f1 = engine.forecast(10, 3)
    # force a very rainy week via the cache and recompute
    key = next(iter(weather._CACHE))
    ts, df = weather._CACHE[key]
    df = df.copy(); df["rain_mm"] = 40.0
    weather._CACHE.clear()
    monkeypatch.setattr(weather, "get_weather", lambda *a, **k: df.reindex(pd.date_range(a[2], a[3])).ffill().bfill())
    store = engine.store
    e2 = Engine(store, today=TODAY)
    f2 = e2.forecast(10, 3)
    assert f2["point"].iloc[5] < f1["point"].iloc[5]


# ---------------------------------------------------------------- pricing
PROD = dict(name="Kaju", category="sweets", cost=150, price=230, base_units=40, elasticity=230 / 80, supply_per_day=64,
            perishable=True, essential=False, temp_sens=0, rain_sens=0, keywords="kaju")


def rec(D=40, index=1.0, promo=0.0, trend=0.0, **kw):
    args = dict(prod=PROD, D=D, index=index, promo=promo, income_price_sens=1.0, n_comp=6, comp_price_idx=1.0,
                surge_cap=0.12, discount_floor=0.8, trend_score=trend)
    args.update(kw)
    return pricing.recommend(**args)


def test_normal_day_holds_price():
    assert rec()["label"] == "HOLD"


def test_busy_day_surges_and_respects_cap_and_cost():
    r = rec(D=120, index=2.0)
    assert r["label"] == "SURGE" and r["mult"] <= 1.12 + 1e-6
    assert r["price"] > PROD["cost"]


def test_capacity_shortage_pushes_price_up():
    assert rec(D=200, index=1.0)["mult"] >= rec(D=40, index=1.0)["mult"]


def test_rival_promo_triggers_sale_never_below_floor():
    r = rec(D=30, index=0.8, promo=0.5)
    assert r["label"] == "SALE" and r["mult"] >= 0.8 - 1e-6


def test_essentials_never_surge():
    p = dict(PROD, essential=True, elasticity=0.5)
    r = rec(prod=p, D=500, index=2.5)
    assert r["mult"] <= 1.0


def test_trending_item_on_weak_day_gets_capped_driver_sale():
    r = rec(D=30, index=0.8, trend=1.0)
    assert r["label"] == "SALE" and r["mult"] >= 0.88 - 1e-6


def test_surge_ceiling_tracks_rival_prices():
    r = rec(D=300, index=2.5, comp_price_idx=0.95, surge_cap=0.30)
    assert r["mult"] <= 0.95 * 1.06 + 1e-6      # 6 rivals -> 6% headroom over cheaper rivals


# ---------------------------------------------------------------- owner learning
def test_factor_belief_moves_toward_reality(store, engine):
    store.add_factor("Cousin's wedding", "2026-10-10", "2026-10-12", 50, 0.4)   # owner over-estimates
    e = Engine(store, today=TODAY)
    for d in pd.date_range("2026-10-01", "2026-10-16"):
        base = float(e._frame([d])["point_no_owner"].iloc[0])
        boost = 1.10 if pd.Timestamp("2026-10-10") <= d <= pd.Timestamp("2026-10-12") else 1.0   # reality: only +10%
        e.log_actual(d, round(base * boost), source="test")
    f = store.factors().iloc[0]
    assert f.n_obs == 3
    assert f.posterior_pct < 50 * (0.4 + 0.6 * 0.4)       # belief fell below the prior
    assert f.posterior_pct > 0


def test_unknown_text_has_no_suggestion_and_known_text_matches():
    assert owner.suggest_from_text("xyzzy") == []
    assert owner.suggest_from_text("my cousin's wedding is on our street")[0]["name"].startswith("Wedding")


# ---------------------------------------------------------------- learn / score loop
def test_logging_creates_prequential_backcast_and_scores(store, engine):
    engine.log_actual("2026-10-15", 150, source="test")
    flog = store.forecast_log()
    row = flog[flog["date"] == "2026-10-15"].iloc[0]
    assert row["kind"] == "backcast" and row["issued_on"] < pd.Timestamp("2026-10-15")
    e2 = Engine(store, today=TODAY)
    e2.log_actual("2026-10-16", 160, source="test")
    df, m = scorecard.evaluate(store, Engine(store, today=TODAY))
    assert m["n"] == 2 and 0 <= m["coverage"] <= 1


def test_demo_improves_over_gut_feel(store, engine):
    demo.load_demo(engine, 21)
    e2 = Engine(store, today=TODAY)
    df, m = scorecard.evaluate(store, e2)
    assert m["n"] == 21
    assert m["mape"] < 0.20
    assert m["skill"] > 0                                  # beats last-7-day-average baseline
    demo.clear_demo(e2)
    assert len(store.actuals()) == 0


# ---------------------------------------------------------------- trends
def test_trend_scoring_and_fallback(store):
    prods = config.PRESETS["sweets"]["products"]
    results = [dict(title="Kaju katli demand surges", body="mithai and kaju katli sell fast", url="u1", query="q")] * 12
    s = trends.score_products(results, prods)
    top = max(s, key=s.get)
    assert top.startswith("Kaju") and 0 < s[top] <= 1.5
    assert all(v == 0 for v in trends.score_products([], prods).values())
    a = trends.assumed_scores(prods, config.FESTIVALS_DEFAULT, dt.date(2026, 10, 17))
    assert set(a) == {p["name"] for p in prods}
