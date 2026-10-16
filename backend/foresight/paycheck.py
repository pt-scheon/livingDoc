"""When do people get paid, and when do they spend it?

Model
-----
* The local population is a mix of pay segments (private salaried, government,
  daily/weekly wage, gig, pension) set by the local income level.
* Each segment has a pay schedule (last working day / 1st / 5th… of month, or
  every Saturday / Monday for weekly earners).  Weekend paydays shift to the
  previous working day.
* Money is spent after payday following a decaying kernel (fast for weekly wage
  earners, slower for monthly salaried).
* wave_idx = (money spent today) / (average money spent per day).  1.0 = a normal
  day, 1.6 = a day when spending is 60% above normal.

All schedules below are ASSUMPTIONS and editable by changing the segments here
or the income level in the UI.
"""
from __future__ import annotations

import calendar
import datetime as dt

import numpy as np
import pandas as pd

KERNEL_DAYS = 46

# dom_profile key 0 => last working day of the month
SEGMENTS = {
    "private": dict(label="Private-sector salaried", income_weight=1.00, schedule="monthly",
                    dom_profile={0: 0.30, 1: 0.20, 3: 0.10, 5: 0.20, 7: 0.12, 10: 0.08},
                    kernel=(0.45, 3.0, 0.35, 10.0, 0.20, 25.0)),
    "govt": dict(label="Government / PSU salaried", income_weight=1.20, schedule="monthly",
                 dom_profile={0: 0.50, 1: 0.50},
                 kernel=(0.45, 3.0, 0.35, 10.0, 0.20, 25.0)),
    "pension": dict(label="Pensioners", income_weight=0.70, schedule="monthly",
                    dom_profile={1: 1.0},
                    kernel=(0.30, 4.0, 0.50, 12.0, 0.20, 25.0)),
    "wage": dict(label="Daily / weekly wage earners", income_weight=0.60, schedule="weekly", weekday=5,  # Saturday
                 kernel=(0.60, 1.2, 0.40, 3.5, 0.0, 1.0)),
    "gig": dict(label="Gig / self-employed (weekly payouts)", income_weight=0.80, schedule="weekly", weekday=0,  # Monday
                kernel=(0.50, 2.0, 0.40, 6.0, 0.10, 15.0)),
}


def _kernel(params) -> np.ndarray:
    a1, t1, a2, t2, a3, t3 = params
    d = np.arange(KERNEL_DAYS)
    k = a1 * np.exp(-d / t1) + a2 * np.exp(-d / t2) + a3 * np.exp(-d / t3)
    return k / k.sum()


def _shift_to_working_day(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def last_working_day(year: int, month: int) -> dt.date:
    return _shift_to_working_day(dt.date(year, month, calendar.monthrange(year, month)[1]))


def pay_events(start: dt.date, end: dt.date, mix: dict, bonus_dates=()) -> list[tuple[dt.date, str, float]]:
    """All (date, segment, money_mass) pay events relevant to [start, end] (incl. a 60-day look-back)."""
    lo = start - dt.timedelta(days=60)
    events = []
    for seg, share in mix.items():
        if share <= 0 or seg not in SEGMENTS:
            continue
        spec = SEGMENTS[seg]
        weight = share * spec["income_weight"]
        if spec["schedule"] == "monthly":
            y, m = lo.year, lo.month
            while dt.date(y, m, 1) <= end + dt.timedelta(days=31):
                for dom, frac in spec["dom_profile"].items():
                    if dom == 0:
                        d = last_working_day(y, m)
                    else:
                        d = _shift_to_working_day(dt.date(y, m, min(dom, calendar.monthrange(y, m)[1])))
                    events.append((d, seg, weight * frac))
                m += 1
                if m == 13:
                    y, m = y + 1, 1
        else:  # weekly: 7/30.4 of monthly income arrives each week
            d = lo
            while d <= end:
                if d.weekday() == spec["weekday"]:
                    events.append((d, seg, weight * 7 / 30.4))
                d += dt.timedelta(days=1)
    # festival bonus: one-off extra pay for salaried segments (assumed ≈ 35% of a month's pay for the average salaried household)
    for b in bonus_dates:
        for seg in ("private", "govt"):
            share = mix.get(seg, 0)
            if share > 0:
                events.append((_shift_to_working_day(b), seg, share * SEGMENTS[seg]["income_weight"] * 0.35))
    return events


def spend_wave(start: dt.date, end: dt.date, mix: dict, bonus_dates=()) -> pd.DataFrame:
    """Daily DataFrame for [start, end]: paid_mass, wave_raw, wave_idx, segment columns."""
    lo = start - dt.timedelta(days=60)
    idx = pd.date_range(lo, end, freq="D")
    n = len(idx)
    wave = np.zeros(n)
    paid = np.zeros(n)
    seg_wave = {s: np.zeros(n) for s in mix}
    kernels = {s: _kernel(SEGMENTS[s]["kernel"]) for s in mix if s in SEGMENTS}
    for d, seg, mass in pay_events(start, end, mix, bonus_dates):
        i = (pd.Timestamp(d) - idx[0]).days
        if 0 <= i < n:
            paid[i] += mass
        if seg not in kernels:
            continue
        k = kernels[seg]
        j0 = max(i, 0)
        j1 = min(n, i + KERNEL_DAYS)
        if j1 > j0:
            seg_wave[seg][j0:j1] += mass * k[j0 - i:j1 - i]
    wave = sum(seg_wave.values())
    avg_per_day = sum(share * SEGMENTS[s]["income_weight"] for s, share in mix.items() if s in SEGMENTS) / 30.4
    df = pd.DataFrame({"date": idx, "paid_mass": paid, "wave_raw": wave}).set_index("date")
    for s, v in seg_wave.items():
        df[f"wave_{s}"] = v / max(avg_per_day, 1e-9)
    df["wave_idx"] = df["wave_raw"] / max(avg_per_day, 1e-9)
    df["paid_idx"] = df["paid_mass"] / max(avg_per_day, 1e-9)  # share of a typical day's money that is paid today
    return df.loc[pd.Timestamp(start):pd.Timestamp(end)]


def peak_days(df: pd.DataFrame, n: int = 3, min_gap: int = 4) -> list[pd.Timestamp]:
    """Top-n spending-wave days, at least `min_gap` days apart."""
    order = df["wave_idx"].sort_values(ascending=False).index
    chosen: list[pd.Timestamp] = []
    for d in order:
        if all(abs((d - c).days) >= min_gap for c in chosen):
            chosen.append(d)
        if len(chosen) == n:
            break
    return sorted(chosen)


def paycheck_density_by_dom(mix: dict) -> pd.DataFrame:
    """Average 'money paid' by day-of-month over a reference year (for the anatomy chart)."""
    start, end = dt.date(2026, 1, 1), dt.date(2026, 12, 31)
    df = spend_wave(start, end, mix)
    g = df.groupby(df.index.day)[["paid_idx", "wave_idx"]].mean()
    g.index.name = "day_of_month"
    return g
