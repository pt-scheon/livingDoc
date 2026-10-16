"""Weather intake.

Live source: Open-Meteo (free, no API key) — https://open-meteo.com
  * forecast API gives past_days + 16 forecast days
  * geocoding API turns a city name into lat/lon
Fallback: an *assumed* monthly climatology (flagged `source="assumed"` so the UI is honest about it).
"""
from __future__ import annotations

import datetime as dt
import math
import time

import numpy as np
import pandas as pd

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Assumed climatology for a hot semi-arid Indian city (Ahmedabad-like). Index 0 = Jan.
_TMAX = [28, 31, 36, 40, 42, 38, 33, 31, 33, 36, 32, 29]
_TMIN = [13, 16, 21, 25, 28, 28, 26, 25, 24, 21, 17, 13]
_RAIN = [0.1, 0.1, 0.1, 0.1, 0.5, 4.0, 10.0, 8.0, 4.0, 0.7, 0.3, 0.1]   # mm / day

_CACHE: dict = {}
_TTL = 3 * 3600


def climatology(dates: pd.DatetimeIndex, seed: int = 7) -> pd.DataFrame:
    """Smoothly interpolated monthly means + seeded noise so charts look natural but are reproducible."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in dates:
        m = d.month - 1
        frac = (d.day - 1) / 30.0
        m2 = (m + 1) % 12
        tmax = _TMAX[m] * (1 - frac) + _TMAX[m2] * frac
        tmin = _TMIN[m] * (1 - frac) + _TMIN[m2] * frac
        rain_mean = _RAIN[m] * (1 - frac) + _RAIN[m2] * frac
        # rainy days: ~ exponential amounts on a random subset
        wet = rng.random() < min(0.9, rain_mean / 6 + 0.03)
        rain = float(rng.exponential(max(rain_mean, 0.05) * (1 / max(min(0.9, rain_mean / 6 + 0.03), 0.03)))) if wet else 0.0
        rows.append((d, tmax + rng.normal(0, 1.3), tmin + rng.normal(0, 1.0), min(rain, 80.0),
                     min(0.95, rain_mean / 6 + 0.05)))
    df = pd.DataFrame(rows, columns=["date", "tmax", "tmin", "rain_mm", "rain_prob"]).set_index("date")
    df["source"] = "assumed"
    return df


def geocode(name: str, timeout: float = 6.0) -> list[dict]:
    """Return candidate places [{name, lat, lon}] from Open-Meteo geocoding. [] when offline."""
    if requests is None:
        return []
    try:
        r = requests.get(GEOCODE_URL, params={"name": name, "count": 5, "language": "en", "format": "json"}, timeout=timeout)
        r.raise_for_status()
        out = []
        for x in r.json().get("results", []) or []:
            label = ", ".join(p for p in (x.get("name"), x.get("admin1"), x.get("country")) if p)
            out.append(dict(name=label, lat=float(x["latitude"]), lon=float(x["longitude"])))
        return out
    except Exception:
        return []


def _fetch_live(lat: float, lon: float, past_days: int, timeout: float = 8.0) -> pd.DataFrame | None:
    if requests is None:
        return None
    try:
        r = requests.get(FORECAST_URL, params=dict(
            latitude=lat, longitude=lon, timezone="auto", past_days=int(min(max(past_days, 0), 92)), forecast_days=16,
            daily="temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"), timeout=timeout)
        r.raise_for_status()
        j = r.json()["daily"]
        df = pd.DataFrame({
            "date": pd.to_datetime(j["time"]),
            "tmax": j["temperature_2m_max"], "tmin": j["temperature_2m_min"],
            "rain_mm": j["precipitation_sum"], "rain_prob": [(p or 0) / 100 for p in j["precipitation_probability_max"]],
        }).set_index("date")
        df["source"] = "live"
        return df.dropna(subset=["tmax"])
    except Exception:
        return None


def get_weather(lat: float, lon: float, start, end, use_live: bool = True) -> pd.DataFrame:
    """Daily weather for [start, end]: live where the API covers it, assumed climatology elsewhere."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    dates = pd.date_range(start, end, freq="D")
    key = (round(lat, 3), round(lon, 3), use_live, start.date(), end.date())
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1].copy()

    live = None
    if use_live:
        past = max(0, (pd.Timestamp(dt.date.today()) - start).days + 1)
        live = _fetch_live(lat, lon, past)
    clim = climatology(dates)
    if live is not None:
        merged = clim.copy()
        common = merged.index.intersection(live.index)
        for c in ("tmax", "tmin", "rain_mm", "rain_prob", "source"):
            merged.loc[common, c] = live.loc[common, c]
        out = merged
    else:
        out = clim
    out["rain_mm"] = out["rain_mm"].fillna(0.0)
    _CACHE[key] = (time.time(), out.copy())
    return out


def weather_status(df: pd.DataFrame) -> str:
    n_live = int((df["source"] == "live").sum())
    if n_live == 0:
        return "assumed climatology (live weather API not reachable or switched off)"
    return f"live Open-Meteo forecast for {n_live} of {len(df)} days; assumed climatology for the rest"


def weather_features(df: pd.DataFrame) -> pd.DataFrame:
    """Model inputs: heat stress above 36 °C (per 5 °C), rain index (per 10 mm, capped), temp deviation from 30 °C."""
    out = pd.DataFrame(index=df.index)
    out["heat"] = np.clip((df["tmax"] - 36.0) / 5.0, 0, 3)
    out["rain"] = np.clip(df["rain_mm"], 0, 50) / 10.0
    out["temp_dev"] = (df["tmax"] - 30.0) / 10.0
    return out
