"""Orchestrates features → model → forecast → pricing, and the learn-from-reality loop."""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import numpy as np
import pandas as pd

from . import calendar_feats, competition, config, owner, paycheck, pricing, trends, weather
from .model import DemandModel, FEATURES, design, prior_beta, training_weights, Z80

ASSUMED_DAYS = 120


class Engine:
    def __init__(self, store, today=None):
        self.store = store
        self.today = pd.Timestamp(today or dt.date.today()).normalize()
        self.profile = store.get_profile()
        self.festivals = store.festivals()
        self.income = config.INCOME_LEVELS[self.profile["income_key"]]
        self.products = self.profile["products"]
        self.cats = [p["category"] for p in self.products]
        rev = {p["name"]: float(p["base_units"]) * float(p["price"]) for p in self.products}
        tot = sum(rev.values()) or 1.0
        self.prod_w = {k: v / tot for k, v in rev.items()}
        self.cat_w: dict[str, float] = {}
        for p in self.products:
            self.cat_w[p["category"]] = self.cat_w.get(p["category"], 0.0) + self.prod_w[p["name"]]
        self.anchor = pd.Timestamp(self.profile["anchor"]).normalize()
        self.ass = self.profile["assumptions"]
        self.prior = prior_beta(self.income["payday_beta"], self.ass["growth_pct_month"])
        self.train: pd.DataFrame | None = None
        self.model = self._load_or_fit()

    # ------------------------------------------------------------------ features
    def raw_features(self, dates) -> pd.DataFrame:
        dates = pd.DatetimeIndex(dates).normalize().unique().sort_values()
        loc = self.profile["location"]
        w = weather.get_weather(loc["lat"], loc["lon"], dates.min(), dates.max(), self.profile.get("use_live_weather", True)).reindex(dates)
        w["rain_mm"] = w["rain_mm"].fillna(0.0)
        w[["tmax", "tmin", "rain_prob"]] = w[["tmax", "tmin", "rain_prob"]].ffill().bfill()
        wf = weather.weather_features(w)

        diwali = [pd.Timestamp(f["start"]).date() for f in self.festivals if "diwali" in f["name"].lower()]
        bonus = [d - dt.timedelta(days=8) for d in diwali]
        pay = paycheck.spend_wave(dates.min().date(), dates.max().date(), self.income["mix"], bonus).reindex(dates)

        mat = calendar_feats.festival_matrix(dates, self.festivals)
        catF = calendar_feats.category_effect(mat, self.festivals, self.cats)
        f_store = sum(catF[c] * self.cat_w.get(c, 0.0) for c in catF.columns)

        comp = competition.promo_pressure(dates, self.store.competitor_events())
        own = owner.factor_effects(dates, self.store.factors(), self.cats, self.cat_w)
        store_frac = own["store_frac"].clip(lower=-0.9)

        df = pd.DataFrame(index=dates)
        df.index.name = "date"
        df["dow"] = dates.dayofweek
        df["payday"] = np.log(pay["wave_idx"].clip(lower=0.15))   # log: diminishing returns on payday spikes
        df["festival"] = f_store
        df["heat"] = wf["heat"]
        df["rain"] = wf["rain"]
        df["competition"] = comp
        df["trend"] = (dates - self.anchor).days / 30.4
        # extras (not model inputs)
        df["tmax"], df["tmin"], df["rain_mm"], df["wsource"] = w["tmax"], w["tmin"], w["rain_mm"], w["source"]
        df["wave_idx"], df["paid_idx"] = pay["wave_idx"], pay["paid_idx"]
        df["owner_frac"] = store_frac
        df["owner_log"] = np.log1p(store_frac)
        df["owner_var"] = own["var"]
        df["sentiment_log"] = np.where(dates >= self.today, np.log1p(self.ass.get("sentiment_pct", 0.0) / 100.0), 0.0)
        df["fest_name"] = calendar_feats.active_label(mat)
        self._last_mat, self._last_catF, self._last_own = mat, catF, own
        return df

    # ------------------------------------------------------------------ training
    def _assumed_y(self, feats: pd.DataFrame) -> np.ndarray:
        """Simulated 'assumed history': what the starting beliefs say recent days looked like (flagged as assumed)."""
        rng = np.random.default_rng(11)
        beta_true = {k: self.prior[k] * rng.uniform(0.7, 1.3) for k in FEATURES}
        X = design(feats)
        xbar = X.mean()
        mu = np.log(self.profile["base_orders"]) + sum(beta_true[k] * (X[k] - xbar[k]) for k in FEATURES)
        return (mu + rng.normal(0, 0.08, len(X))).to_numpy()

    def _training_frame(self) -> pd.DataFrame:
        real = self.store.actuals()
        real = real[real["date"] < self.today + pd.Timedelta(days=1)] if len(real) else real
        real_dates = pd.DatetimeIndex(real["date"]) if len(real) else pd.DatetimeIndex([])
        assumed = pd.date_range(self.today - pd.Timedelta(days=ASSUMED_DAYS), self.today - pd.Timedelta(days=1))
        assumed = assumed.difference(real_dates)
        all_dates = assumed.union(real_dates)
        feats = self.raw_features(all_dates)
        feats["is_real"] = feats.index.isin(real_dates)
        y = pd.Series(np.nan, index=feats.index)
        a_mask = ~feats["is_real"]
        y[a_mask] = self._assumed_y(feats[a_mask])
        if len(real):
            r = real.set_index("date")["orders"].astype(float).clip(lower=1.0)
            idx = feats.index[feats["is_real"]]
            y[idx] = np.log(r.reindex(idx).to_numpy()) - feats.loc[idx, "owner_log"].to_numpy() - feats.loc[idx, "sentiment_log"].to_numpy()
        feats["y_log"] = y
        return feats

    def _signature(self) -> str:
        p = self.profile
        act = self.store.actuals()
        fac = self.store.factors()
        ev = self.store.competitor_events()
        payload = dict(
            inc=p["income_key"], ass=p["assumptions"], base=p["base_orders"], ncomp=p["n_competitors"],
            loc=p["location"], live=p.get("use_live_weather", True), anchor=p["anchor"],
            n=len(act), last=str(act["date"].max()) if len(act) else "", s=float(act["orders"].sum()) if len(act) else 0.0,
            fest=[(f["name"], f["start"], f["end"], f["lift"], f["lead"], f["tail"], json.dumps(f["aff"], sort_keys=True)) for f in self.festivals],
            fac=[(int(r.id), r.effect_pct, r.confidence, None if pd.isna(r.posterior_pct) else r.posterior_pct, str(r.start), str(r.end), r.scope, int(r.active)) for r in fac.itertuples()] if len(fac) else [],
            ev=[(str(r.start), str(r.end), r.discount_pct) for r in ev.itertuples()] if len(ev) else [],
            prods=[(q["name"], q["category"], q["price"], q["base_units"]) for q in self.products],
            day=str(self.today.date()),
        )
        return hashlib.md5(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def _load_or_fit(self) -> DemandModel:
        self.train = self._training_frame()
        sig = self._signature()
        cached = self.store.get_kv("model")
        if cached and cached.get("sig") == sig:
            m = DemandModel.from_json(cached["json"])
        else:
            m = self._fit()
            self.store.set_kv("model", dict(sig=sig, json=m.to_json()))
        self.tmax_bar = float(self.train["tmax"].mean())
        self.rain_bar = float(self.train["rain_mm"].mean())
        return m

    def _fit(self) -> DemandModel:
        tr = self.train
        n_real = int(tr["is_real"].sum())
        m = DemandModel(self.prior, self.ass.get("prior_strength", 25.0))
        w = training_weights(tr["is_real"].to_numpy(), n_real)
        m.fit(design(tr), tr["y_log"].to_numpy(), w, n_real=n_real, n_assumed=int((~tr["is_real"]).sum()))
        return m

    def refit(self):
        """Re-read everything (new actuals / factors) and relearn."""
        self.profile = self.store.get_profile()
        self.festivals = self.store.festivals()
        self.model = self._load_or_fit()

    # ------------------------------------------------------------------ forecast
    def _frame(self, dates) -> pd.DataFrame:
        feats = self.raw_features(dates)
        X = design(feats)
        mu = self.model.mu(X) + feats["owner_log"].to_numpy() + feats["sentiment_log"].to_numpy()
        h = np.maximum((feats.index - self.today).days.to_numpy(), 0)
        sig = self.model.sigma_h(h, feats["owner_var"].to_numpy())
        b = DemandModel.bands(mu, sig)
        out = feats.copy()
        out["mu"], out["sigma"] = mu, sig
        for c in b.columns:
            out[c] = b[c].to_numpy()
        out["typical"] = float(np.exp(self.model.typical_log()))
        out["index"] = out["point"] / out["typical"]
        out["point_no_owner"] = np.exp(self.model.mu(X) + feats["sentiment_log"].to_numpy())
        return out

    def forecast(self, horizon: int = 28, history: int = 28) -> pd.DataFrame:
        dates = pd.date_range(self.today - pd.Timedelta(days=history), self.today + pd.Timedelta(days=horizon - 1))
        fc = self._frame(dates)
        fc["is_future"] = fc.index >= self.today
        act = self.store.actuals()
        fc["actual"] = np.nan
        fc["actual_kind"] = ""
        if len(act):
            a = act.set_index("date")["orders"]
            idx = fc.index.intersection(a.index)
            fc.loc[idx, "actual"] = a.loc[idx].to_numpy()
            fc.loc[idx, "actual_kind"] = "real"
        # assumed history for days without a real number (flagged, shown hollow)
        miss = fc.index[(fc["actual"].isna()) & (~fc["is_future"])]
        tr = self.train
        for d in miss:
            if d in tr.index and not tr.loc[d, "is_real"]:
                fc.loc[d, "actual"] = float(np.exp(tr.loc[d, "y_log"]))
                fc.loc[d, "actual_kind"] = "assumed"
        fc["revenue"] = fc["point"] * float(self.profile["avg_ticket"])
        return fc

    # ------------------------------------------------------------------ explanation
    def explain(self, date) -> pd.Series:
        """% effect of each driver on one day vs. a typical day."""
        date = pd.Timestamp(date).normalize()
        fc = self._frame([date])
        X = design(fc)
        c = self.model.contributions(X).iloc[0]
        out = {
            "Weekday": c["Weekday"], "Payday wave": c["Payday"],
            "Festival / season": c["Festival"], "Weather": c["Weather"],
            "Rival promotions": c["Competition"], "Market growth": c["Trend"],
        }
        if abs(float(fc["sentiment_log"].iloc[0])) > 1e-9:
            out["Market sentiment (assumed)"] = float(fc["sentiment_log"].iloc[0])
        for name, s in self._last_own["by_factor"].items():
            v = float(s.iloc[0])
            if abs(v) > 1e-9:
                out[f"You: {name}"] = float(np.log1p(v))
        ser = pd.Series(out)
        return np.expm1(ser)   # fractional effect

    # ------------------------------------------------------------------ pricing
    def trend_scores(self, payload=None) -> dict[str, float]:
        payload = payload or self.store.get_trends(self.today.date()) or self.store.latest_trends()[1]
        if payload:
            return {k: float(v) for k, v in payload["scores"].items()}
        return trends.assumed_scores(self.products, self.festivals, self.today.date())

    def product_demand(self, fc: pd.DataFrame, trend: dict[str, float]) -> dict[str, pd.Series]:
        catF = self._last_catF.reindex(fc.index)
        own_cat = self._last_own["per_cat"].reindex(fc.index)
        f_store = fc["festival"]
        o_store = fc["owner_frac"]
        out = {}
        for p in self.products:
            c = p["category"]
            rel_f = (1 + catF[c]) / (1 + f_store)
            rel_o = (1 + own_cat[c]) / (1 + o_store)
            wthr = np.exp(float(p["temp_sens"]) * (fc["tmax"] - self.tmax_bar) / 10.0 + float(p["rain_sens"]) * (fc["rain_mm"] - self.rain_bar) / 10.0)
            out[p["name"]] = float(p["base_units"]) * fc["index"] * rel_f * rel_o * wthr * trends.boost(trend.get(p["name"], 0.0))
        return out

    def pricing_plan(self, fc: pd.DataFrame, trend: dict[str, float] | None = None) -> pd.DataFrame:
        trend = trend if trend is not None else self.trend_scores()
        dates = fc.index
        # product_demand relies on matrices from the last raw_features call covering exactly fc.index
        D = self.product_demand(fc, trend)
        prof = self.profile
        return pricing.plan(dates, self.products, D, trend, fc["index"], fc["competition"],
                            int(prof["n_competitors"]), self.income["price_sens"], float(prof["comp_price_idx"]),
                            float(prof["surge_cap"]), float(prof["discount_floor"]), fc["sigma"])

    def full_plan(self, fc: pd.DataFrame, trend=None) -> pd.DataFrame:
        """Pricing plan for the future part of a forecast frame."""
        fut = fc[fc["is_future"]]
        # rebuild matrices for exactly the future dates
        f2 = self._frame(fut.index)
        f2["is_future"] = True
        return self.pricing_plan(f2, trend)

    # ------------------------------------------------------------------ logging / learning
    def log_forecasts(self, fc: pd.DataFrame, plan: pd.DataFrame, kind="forecast"):
        rows = []
        for d, r in fc[fc["is_future"]].iterrows():
            pl = plan[plan["date"] == d]
            rec = dict(mult={x.product: x.mult for x in pl.itertuples()}, D={x.product: x.demand_at_base for x in pl.itertuples()},
                       ctx=dict(idx=float(r["index"]), promo=float(r["competition"])))
            rows.append(dict(date=d, mu=r["mu"], sigma=r["sigma"], point=r["point"], lo80=r["lo80"], hi80=r["hi80"], rec=rec))
        self.store.log_forecasts(self.today.date(), rows, kind)

    def log_actual(self, date, orders: float, revenue: float | None = None, note: str = "", source: str = "owner") -> dict:
        """Record what really happened. Learns from it and returns what changed in the AI's beliefs."""
        date = pd.Timestamp(date).normalize()
        before = self.model
        # 1. if we never forecast this day, freeze the *current* model's forecast as a back-cast (honest: made before learning it)
        flog = self.store.forecast_log()
        has = len(flog) and ((flog["date"] == date) & (flog["issued_on"] < date)).any()
        if not has:
            fr = self._frame([date])
            fr["is_future"] = True
            plan = self.pricing_plan(fr)
            r = fr.iloc[0]
            rec = dict(mult={x.product: x.mult for x in plan.itertuples()}, D={x.product: x.demand_at_base for x in plan.itertuples()},
                       ctx=dict(idx=float(r["index"]), promo=float(r["competition"])))
            self.store.log_forecasts((date - pd.Timedelta(days=1)).date(),
                                     [dict(date=date, mu=r["mu"], sigma=r["sigma"], point=r["point"], lo80=r["lo80"], hi80=r["hi80"], rec=rec)],
                                     kind="backcast")
        pred_without = None
        # 2. save the actual
        self.store.upsert_actual(date.date(), orders, revenue if revenue is not None else orders * float(self.profile["avg_ticket"]), note, source)
        # 3. relearn owner-factor beliefs, then refit the demand model
        act = self.store.actuals()
        if len(self.store.factors()):
            span = pd.date_range(act["date"].min(), act["date"].max())
            fr = self._frame(span)
            pred_without = pd.Series(fr["point_no_owner"].to_numpy(), index=span)
        changes = owner.update_posteriors(self.store, pred_without, act, self.cat_w) if pred_without is not None else []
        self.refit()
        return dict(factor_changes=changes, n_real=self.model.n_real,
                    beta_shift={k: self.model.beta[k] - before.beta[k] for k in FEATURES})

    def learned_vs_prior(self) -> pd.DataFrame:
        from .model import FEATURE_LABELS
        return pd.DataFrame({
            "driver": [FEATURE_LABELS[k] for k in FEATURES],
            "assumed (prior)": [self.model.prior[k] for k in FEATURES],
            "learned now": [self.model.beta[k] for k in FEATURES],
        })

    # ------------------------------------------------------------------ narrative
    def brief(self, fc: pd.DataFrame, plan: pd.DataFrame) -> dict:
        fut = fc[fc["is_future"]]
        today_row = fut.iloc[0]
        top = self.explain(self.today)
        top = top[top.abs() > 0.015].sort_values(key=lambda s: -s.abs()).head(3)
        reasons = ", ".join(f"{k.lower()} {v:+.0%}" for k, v in top.items()) or "nothing unusual"
        peak = fut["point"].idxmax()
        pk = paycheck.peak_days(fut.assign(wave_idx=fut["wave_idx"]), 3)
        pr = plan[plan["date"] == self.today]
        return dict(
            today_orders=float(today_row["point"]), today_vs_typical=float(today_row["index"] - 1),
            lo80=float(today_row["lo80"]), hi80=float(today_row["hi80"]), reasons=reasons,
            peak_day=peak, peak_orders=float(fut.loc[peak, "point"]), peak_vs_typical=float(fut.loc[peak, "index"] - 1),
            payday_peaks=pk, today_plan=pr,
            surges=int((pr["label"] == "SURGE").sum()), sales=int((pr["label"] == "SALE").sum()),
        )
