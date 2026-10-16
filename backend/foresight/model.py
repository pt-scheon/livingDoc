"""The demand model: a Bayesian-ridge log-linear model that starts from *assumed market trends*
and is pulled toward reality as the owner logs real days.

    log(orders_t) = b0 + Σ_k β_k · x_k,t  + owner_offset_t

* Priors (β₀) encode the assumed market trends: Saturdays are busier, paydays lift spending,
  festivals lift demand, heat and rain suppress footfall, rival promotions steal customers,
  and the market grows g % a month.
* Cold start: the model is trained on a window of *assumed* history simulated from those priors
  (clearly flagged).  Real logged days weigh 5× and the assumed rows fade out over the first 30 real days, so the model gradually forgets the assumptions that reality disproves.
* The fit is a weighted ridge regression shrunk toward the priors — closed form, instant, and each
  coefficient can be inspected by the owner.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

DOW_COLS = ["dow_Tue", "dow_Wed", "dow_Thu", "dow_Fri", "dow_Sat", "dow_Sun"]
FEATURES = DOW_COLS + ["payday", "festival", "heat", "rain", "competition", "trend"]

FEATURE_LABELS = {
    "dow_Tue": "Tuesday", "dow_Wed": "Wednesday", "dow_Thu": "Thursday", "dow_Fri": "Friday",
    "dow_Sat": "Saturday", "dow_Sun": "Sunday", "payday": "Payday spending wave",
    "festival": "Festival / season", "heat": "Heat (above 36 °C)", "rain": "Rain (per 10 mm)",
    "competition": "Rival promotions", "trend": "Market growth (per month)",
}

Z80 = 1.2816
Z50 = 0.6745


def prior_beta(payday_beta: float, growth_pct_month: float) -> dict:
    """The starting beliefs ("assumed market trends")."""
    return {
        "dow_Tue": -0.02, "dow_Wed": -0.03, "dow_Thu": -0.01, "dow_Fri": 0.06, "dow_Sat": 0.16, "dow_Sun": 0.12,
        "payday": float(payday_beta),
        "festival": 0.55,
        "heat": -0.07,
        "rain": -0.06,
        "competition": -0.22,
        "trend": float(np.log1p(growth_pct_month / 100.0)),
    }


def design(df: pd.DataFrame) -> pd.DataFrame:
    """Turn raw feature columns (dow, payday, festival, heat, rain, competition, trend) into the model's X."""
    X = pd.DataFrame(index=df.index)
    for i, c in enumerate(DOW_COLS, start=1):
        X[c] = (df["dow"] == i).astype(float)
    for c in ("payday", "festival", "heat", "rain", "competition", "trend"):
        X[c] = df[c].astype(float)
    return X[FEATURES]


class DemandModel:
    def __init__(self, prior: dict, prior_strength: float = 25.0):
        self.prior = dict(prior)
        self.prior_strength = prior_strength
        self.beta = dict(prior)
        self.b0 = 0.0
        self.sigma = 0.10
        self.xbar = {k: 0.0 for k in FEATURES}
        self.n_real = 0
        self.n_assumed = 0
        self.fitted = False

    # -- fitting ----------------------------------------------------------------
    def fit(self, X: pd.DataFrame, y_log: np.ndarray, weights: np.ndarray, n_real: int = 0, n_assumed: int = 0):
        Xv = X[FEATURES].to_numpy(float)
        w = np.asarray(weights, float)
        y = np.asarray(y_log, float)
        n = len(y)
        Xa = np.c_[np.ones(n), Xv]
        wsum = w.sum()
        mean = (w[:, None] * Xv).sum(0) / wsum
        var = (w[:, None] * (Xv - mean) ** 2).sum(0) / wsum
        lam = np.r_[0.0, self.prior_strength * np.maximum(var, 1e-3)]     # intercept unpenalised
        beta0 = np.r_[0.0, [self.prior[k] for k in FEATURES]]
        A = Xa.T @ (w[:, None] * Xa) + np.diag(lam)
        b = Xa.T @ (w * y) + lam * beta0
        sol = np.linalg.solve(A, b)
        self.b0 = float(sol[0])
        self.beta = {k: float(v) for k, v in zip(FEATURES, sol[1:])}
        res = y - Xa @ sol
        dof = max(wsum - Xa.shape[1], 5.0)
        self.sigma = float(np.clip(np.sqrt((w * res ** 2).sum() / dof), 0.05, 0.40))
        self.xbar = {k: float(m) for k, m in zip(FEATURES, mean)}
        self.n_real, self.n_assumed, self.fitted = int(n_real), int(n_assumed), True
        return self

    # -- prediction ----------------------------------------------------------------
    def mu(self, X: pd.DataFrame) -> np.ndarray:
        return self.b0 + X[FEATURES].to_numpy(float) @ np.array([self.beta[k] for k in FEATURES])

    def typical_log(self) -> float:
        return self.b0 + sum(self.beta[k] * self.xbar[k] for k in FEATURES)

    def contributions(self, X: pd.DataFrame) -> pd.DataFrame:
        """log-effect of each feature group vs. a typical day. Columns: Weekday, Payday, Festival, Weather, Competition, Trend."""
        c = pd.DataFrame(index=X.index)
        c["Weekday"] = sum(self.beta[k] * (X[k] - self.xbar[k]) for k in DOW_COLS)
        c["Payday"] = self.beta["payday"] * (X["payday"] - self.xbar["payday"])
        c["Festival"] = self.beta["festival"] * (X["festival"] - self.xbar["festival"])
        c["Weather"] = sum(self.beta[k] * (X[k] - self.xbar[k]) for k in ("heat", "rain"))
        c["Competition"] = self.beta["competition"] * (X["competition"] - self.xbar["competition"])
        c["Trend"] = self.beta["trend"] * (X["trend"] - self.xbar["trend"])
        return c

    def sigma_h(self, horizon_days: np.ndarray, owner_var: np.ndarray | None = None) -> np.ndarray:
        """Predictive σ grows with horizon (weather and the unknown unknowns)."""
        h = np.maximum(np.asarray(horizon_days, float), 0)
        extra = 0.011 * h + np.where(h > 15, 0.03, 0.0)
        # Early on the model is mostly running on assumptions → wider bands; fades as real days accumulate
        model_unc = 0.08 * max(0.25, 1.0 - self.n_real / 60.0)
        var = self.sigma ** 2 + extra ** 2 + model_unc ** 2
        if owner_var is not None:
            var = var + owner_var
        return np.sqrt(var)

    @staticmethod
    def bands(mu: np.ndarray, sigma: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame({
            "point": np.exp(mu), "lo50": np.exp(mu - Z50 * sigma), "hi50": np.exp(mu + Z50 * sigma),
            "lo80": np.exp(mu - Z80 * sigma), "hi80": np.exp(mu + Z80 * sigma)})

    # -- (de)serialisation ------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(dict(prior=self.prior, prior_strength=self.prior_strength, beta=self.beta, b0=self.b0,
                               sigma=self.sigma, xbar=self.xbar, n_real=self.n_real, n_assumed=self.n_assumed,
                               fitted=self.fitted))

    @classmethod
    def from_json(cls, s: str):
        d = json.loads(s)
        m = cls(d["prior"], d.get("prior_strength", 25.0))
        for k in ("beta", "b0", "sigma", "xbar", "n_real", "n_assumed", "fitted"):
            setattr(m, k, d[k])
        return m


def training_weights(is_real: np.ndarray, n_real: int) -> np.ndarray:
    """Real days weigh 5×. Assumed days fade from 1.0 → 0.1 over the first 30 real days."""
    fade = max(0.10, 1.0 - 0.9 * n_real / 30.0)
    return np.where(is_real, 5.0, fade)
