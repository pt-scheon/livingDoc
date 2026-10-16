"""Local competition: structural pressure (how many rivals) and temporary pressure (rival promotions)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def promo_pressure(dates: pd.DatetimeIndex, events: pd.DataFrame) -> pd.Series:
    """0 on normal days; a rival running a 10% sale adds 0.3 of pressure (capped at 1.0)."""
    s = pd.Series(0.0, index=dates)
    if events is not None and len(events):
        for e in events.itertuples():
            m = (dates >= e.start) & (dates <= e.end)
            s[m] += float(e.discount_pct) / 100.0 * 3.0
    return s.clip(0, 1.0)


def elasticity_multiplier(n_competitors: int) -> float:
    """More rivals nearby → customers switch more easily → demand is more price-elastic."""
    return 1.0 + 0.04 * max(0, int(n_competitors))


def surge_ceiling(comp_price_idx: float, n_competitors: int = 6) -> float:
    """Highest price multiplier (vs. my normal price) before I'm too far above what rivals charge.
    Headroom is 12% with no rivals and shrinks 1 point per rival (floor 3%)."""
    headroom = min(0.12, max(0.03, 0.12 - 0.01 * int(n_competitors)))
    return max(0.7, float(comp_price_idx) * (1 + headroom))
