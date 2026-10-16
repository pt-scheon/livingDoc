"""Festival / season effects as smooth demand kernels (build-up → peak → tail → slump)."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd


def _d(x) -> dt.date:
    return pd.Timestamp(x).date()


def kernel(day: dt.date, start: dt.date, end: dt.date, lift: float, lead: int, tail: int) -> float:
    """Demand uplift (fraction, e.g. 0.4 = +40%) of one festival on one day."""
    if start <= day <= end:
        return lift
    if day < start:
        x = (start - day).days
        if lead > 0 and x <= lead:
            return lift * 0.85 * (1 - x / (lead + 1)) ** 1.6   # shopping build-up
        return 0.0
    x = (day - end).days
    if x <= tail:
        return lift * 0.35 * (1 - (x - 1) / max(tail, 1))      # lingering demand
    if x <= tail + 3:
        return -0.12 * lift                                     # post-festival hangover
    return 0.0


def festival_matrix(dates: pd.DatetimeIndex, festivals: list[dict]) -> pd.DataFrame:
    """date × festival-name matrix of kernel values."""
    cols = {}
    for f in festivals:
        s, e = _d(f["start"]), _d(f["end"])
        vals = [kernel(d.date(), s, e, float(f["lift"]), int(f.get("lead", 3)), int(f.get("tail", 1))) for d in dates]
        name = f["name"]
        while name in cols:
            name += "*"
        cols[name] = vals
    return pd.DataFrame(cols, index=dates)


def category_effect(mat: pd.DataFrame, festivals: list[dict], categories: list[str]) -> pd.DataFrame:
    """date × category matrix: sum over festivals of kernel × category affinity."""
    out = pd.DataFrame(0.0, index=mat.index, columns=sorted(set(categories)))
    names = list(mat.columns)
    for name, f in zip(names, festivals):
        aff = f.get("aff", {}) or {}
        for c in out.columns:
            out[c] += mat[name] * float(aff.get(c, 1.0))
    return out


def active_label(mat: pd.DataFrame, threshold: float = 0.12) -> pd.Series:
    """Name of the strongest active festival per date ('' if none)."""
    if mat.shape[1] == 0:
        return pd.Series("", index=mat.index)
    best = mat.idxmax(axis=1)
    top = mat.max(axis=1)
    return best.where(top >= threshold, "")


def festival_spans(festivals: list[dict], start: dt.date, end: dt.date) -> list[dict]:
    """Festivals whose peak window overlaps [start, end] (for chart shading)."""
    spans = []
    for f in festivals:
        s, e = _d(f["start"]), _d(f["end"])
        if e >= start and s <= end:
            spans.append(dict(name=f["name"], start=s, end=e, lift=f["lift"]))
    return spans
