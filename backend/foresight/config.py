"""Defaults, presets and assumptions.

Everything in this file is an ASSUMPTION the owner can override in the UI
(Setup tab).  Nothing here is presented as measured fact.
"""
from __future__ import annotations

import copy
import datetime as dt

DEFAULT_LOCATION = {"name": "Ahmedabad, Gujarat, India", "lat": 23.0225, "lon": 72.5714}

# --------------------------------------------------------------------------
# Local income levels -> who gets paid how, and how strongly spending follows payday
# mix keys are the pay-segments defined in paycheck.SEGMENTS
# --------------------------------------------------------------------------
INCOME_LEVELS = {
    "low": dict(
        label="Low  (≈ ₹10–18k per household / month)",
        monthly=14000,
        mix=dict(private=0.20, govt=0.05, wage=0.50, gig=0.20, pension=0.05),
        payday_beta=0.55, price_sens=1.30,
    ),
    "lower_middle": dict(
        label="Lower-middle  (≈ ₹18–35k)",
        monthly=26000,
        mix=dict(private=0.35, govt=0.10, wage=0.30, gig=0.20, pension=0.05),
        payday_beta=0.42, price_sens=1.15,
    ),
    "middle": dict(
        label="Middle  (≈ ₹35–70k)",
        monthly=50000,
        mix=dict(private=0.50, govt=0.20, wage=0.10, gig=0.15, pension=0.05),
        payday_beta=0.32, price_sens=1.00,
    ),
    "upper_middle": dict(
        label="Upper-middle  (≈ ₹70k–1.5L)",
        monthly=100000,
        mix=dict(private=0.60, govt=0.20, wage=0.02, gig=0.15, pension=0.03),
        payday_beta=0.22, price_sens=0.85,
    ),
    "high": dict(
        label="High  (> ₹1.5L)",
        monthly=200000,
        mix=dict(private=0.55, govt=0.10, wage=0.00, gig=0.32, pension=0.03),
        payday_beta=0.12, price_sens=0.70,
    ),
}

# --------------------------------------------------------------------------
# Festival / season calendar (Gujarat-leaning).  Dates are ASSUMED — verify and
# edit them in the Setup tab.  lift = peak demand uplift for an average shop;
# aff = how strongly each product category responds (1.0 = average).
# --------------------------------------------------------------------------
FESTIVALS_DEFAULT = [
    dict(name="Navratri / Garba", start="2026-10-11", end="2026-10-19", lift=0.45, lead=7, tail=2, kind="festival",
         aff=dict(apparel=1.8, snacks=1.3, beverages=1.2, sweets=0.9, gifts=0.8, decor=1.2, grocery=0.8, electronics=0.6)),
    dict(name="Dussehra", start="2026-10-20", end="2026-10-20", lift=0.35, lead=3, tail=2, kind="festival",
         aff=dict(sweets=1.7, snacks=1.6, gifts=1.0, apparel=0.8, grocery=0.9, decor=0.7)),
    dict(name="Karwa Chauth", start="2026-10-29", end="2026-10-29", lift=0.12, lead=3, tail=1, kind="festival",
         aff=dict(sweets=1.3, apparel=1.5, gifts=1.5, decor=0.8)),
    dict(name="Dhanteras", start="2026-11-06", end="2026-11-06", lift=0.60, lead=5, tail=1, kind="festival",
         aff=dict(gifts=1.6, electronics=1.6, decor=1.3, sweets=1.0, apparel=0.9, grocery=0.9)),
    dict(name="Diwali", start="2026-11-08", end="2026-11-08", lift=1.00, lead=14, tail=4, kind="festival",
         aff=dict(sweets=1.7, gifts=1.6, decor=1.6, apparel=1.4, snacks=1.3, electronics=1.2, grocery=1.1, beverages=0.8)),
    dict(name="Gujarati New Year", start="2026-11-10", end="2026-11-10", lift=0.50, lead=1, tail=3, kind="festival",
         aff=dict(sweets=1.5, apparel=1.4, gifts=1.3, snacks=1.2, grocery=1.0)),
    dict(name="Bhai Dooj", start="2026-11-11", end="2026-11-11", lift=0.30, lead=1, tail=1, kind="festival",
         aff=dict(sweets=1.6, gifts=1.6, apparel=1.0)),
    dict(name="Wedding season", start="2026-11-21", end="2026-12-15", lift=0.25, lead=5, tail=5, kind="season",
         aff=dict(apparel=1.7, gifts=1.4, sweets=1.3, decor=1.1, snacks=1.0, grocery=1.0)),
    dict(name="Christmas & New Year", start="2026-12-24", end="2026-12-31", lift=0.20, lead=3, tail=2, kind="festival",
         aff=dict(beverages=1.4, snacks=1.3, sweets=1.1, gifts=1.2, apparel=1.0)),
    dict(name="Uttarayan (Makar Sankranti)", start="2027-01-14", end="2027-01-15", lift=0.80, lead=7, tail=1, kind="festival",
         aff=dict(sweets=1.8, snacks=1.6, beverages=0.8, grocery=1.0, apparel=0.8)),
    dict(name="Holi", start="2027-03-22", end="2027-03-22", lift=0.50, lead=5, tail=1, kind="festival",
         aff=dict(sweets=1.6, snacks=1.5, beverages=1.4, apparel=1.1, grocery=1.0)),
]

# --------------------------------------------------------------------------
# Business presets.  Product columns:
#   cost/price (₹), base_units = typical units/day at current price,
#   elasticity (>1 = price sensitive), supply_per_day = what you can sell per day,
#   perishable (leftovers lose value), essential (never surged),
#   temp_sens / rain_sens = response to heat (+10°C) / rain (+10 mm),
#   keywords = used for the daily web-trend search
# --------------------------------------------------------------------------
_P = dict


PRESETS = {
    "sweets": dict(
        label="Sweet & snack shop",
        base_orders=140, avg_ticket=210,
        products=[
            _P(name="Kaju Katli (250g box)", category="sweets", cost=150, price=230, base_units=40, elasticity=1.4,
               supply_per_day=60, perishable=True, essential=False, temp_sens=-0.02, rain_sens=0.0,
               keywords="kaju katli,dry fruit sweets,mithai"),
            _P(name="Mohanthal (250g)", category="sweets", cost=70, price=120, base_units=35, elasticity=1.5,
               supply_per_day=50, perishable=True, essential=False, temp_sens=-0.02, rain_sens=0.0,
               keywords="mohanthal,gujarati sweets,mithai"),
            _P(name="Fafda-Jalebi (plate)", category="snacks", cost=28, price=70, base_units=90, elasticity=1.2,
               supply_per_day=130, perishable=True, essential=False, temp_sens=-0.05, rain_sens=0.12,
               keywords="fafda jalebi,gujarati breakfast"),
            _P(name="Chikki / til sweets", category="sweets", cost=35, price=60, base_units=30, elasticity=1.6,
               supply_per_day=45, perishable=False, essential=False, temp_sens=-0.20, rain_sens=0.02,
               keywords="chikki,til gud,winter sweets"),
            _P(name="Premium gift hamper", category="gifts", cost=450, price=799, base_units=8, elasticity=1.8,
               supply_per_day=15, perishable=False, essential=False, temp_sens=0.0, rain_sens=0.0,
               keywords="gift hamper,diwali gift box,corporate gifts"),
            _P(name="Cold coffee", category="beverages", cost=22, price=70, base_units=40, elasticity=1.3,
               supply_per_day=65, perishable=True, essential=False, temp_sens=0.18, rain_sens=-0.12,
               keywords="cold coffee,iced coffee,cafe drinks"),
        ],
    ),
    "kirana": dict(
        label="Kirana / grocery store",
        base_orders=220, avg_ticket=340,
        products=[
            _P(name="Atta 5 kg", category="grocery", cost=190, price=215, base_units=35, elasticity=0.5,
               supply_per_day=60, perishable=False, essential=True, temp_sens=0.0, rain_sens=0.0,
               keywords="atta,wheat flour"),
            _P(name="Cooking oil 1 L", category="grocery", cost=128, price=145, base_units=40, elasticity=0.6,
               supply_per_day=70, perishable=False, essential=True, temp_sens=0.0, rain_sens=0.0,
               keywords="cooking oil,groundnut oil,sunflower oil"),
            _P(name="Namkeen / packaged snacks", category="snacks", cost=14, price=20, base_units=90, elasticity=1.3,
               supply_per_day=140, perishable=False, essential=False, temp_sens=0.0, rain_sens=0.06,
               keywords="namkeen,packaged snacks,chips"),
            _P(name="Soft drinks 750 ml", category="beverages", cost=32, price=40, base_units=60, elasticity=1.2,
               supply_per_day=95, perishable=False, essential=False, temp_sens=0.20, rain_sens=-0.10,
               keywords="soft drinks,cold drinks,soda"),
            _P(name="Dry fruits pack", category="gifts", cost=280, price=360, base_units=15, elasticity=1.6,
               supply_per_day=28, perishable=False, essential=False, temp_sens=-0.05, rain_sens=0.0,
               keywords="dry fruits,almonds,cashew gift"),
            _P(name="Diyas & decor set", category="decor", cost=60, price=110, base_units=12, elasticity=1.7,
               supply_per_day=25, perishable=False, essential=False, temp_sens=0.0, rain_sens=0.0,
               keywords="diya,diwali decor,rangoli,led lights"),
        ],
    ),
    "apparel": dict(
        label="Clothing boutique",
        base_orders=45, avg_ticket=1450,
        products=[
            _P(name="Kurta set", category="apparel", cost=650, price=1199, base_units=14, elasticity=1.7,
               supply_per_day=20, perishable=False, essential=False, temp_sens=0.0, rain_sens=-0.05,
               keywords="kurta set,ethnic wear,festive kurta"),
            _P(name="Chaniya choli", category="apparel", cost=1600, price=2999, base_units=6, elasticity=1.9,
               supply_per_day=10, perishable=False, essential=False, temp_sens=0.0, rain_sens=-0.05,
               keywords="chaniya choli,garba outfit,navratri dress"),
            _P(name="Men's shirt", category="apparel", cost=450, price=899, base_units=12, elasticity=1.6,
               supply_per_day=18, perishable=False, essential=False, temp_sens=0.05, rain_sens=-0.05,
               keywords="men's shirt,formal shirt,party wear men"),
            _P(name="Kids ethnic wear", category="apparel", cost=400, price=799, base_units=8, elasticity=1.5,
               supply_per_day=14, perishable=False, essential=False, temp_sens=0.0, rain_sens=-0.04,
               keywords="kids ethnic wear,kids kurta,festive kids clothes"),
            _P(name="Jackets & sweaters", category="apparel", cost=700, price=1399, base_units=4, elasticity=1.6,
               supply_per_day=8, perishable=False, essential=False, temp_sens=-0.30, rain_sens=0.02,
               keywords="winter jacket,sweater,hoodie"),
            _P(name="Dupatta & accessories", category="gifts", cost=120, price=299, base_units=20, elasticity=1.8,
               supply_per_day=32, perishable=False, essential=False, temp_sens=0.0, rain_sens=0.0,
               keywords="dupatta,artificial jewellery,festive accessories"),
        ],
    ),
}

# Calibration: we assume the owner's current price is roughly right on a normal day, so for non-essentials
# elasticity = price / (price - cost)  (Lerner rule).  Supply is treated as daily CAPACITY (≈ 1.6× a normal day).
for _preset in PRESETS.values():
    for _p in _preset["products"]:
        if not _p["essential"]:
            _p["elasticity"] = round(_p["price"] / (_p["price"] - _p["cost"]), 2)
        _p["supply_per_day"] = int(round(_p["base_units"] * 1.6))

# --------------------------------------------------------------------------
# Market-trend assumptions (editable) — these seed the model's prior beliefs
# --------------------------------------------------------------------------
DEFAULT_ASSUMPTIONS = dict(
    growth_pct_month=1.0,     # underlying market growth, % per month
    sentiment_pct=0.0,        # extra consumer-sentiment shift applied from today on, %
    prior_strength=25.0,      # how many "days of evidence" the starting beliefs are worth
)


def default_profile(preset: str = "sweets") -> dict:
    p = PRESETS[preset]
    return dict(
        business_name="My Shop",
        preset=preset,
        location=dict(DEFAULT_LOCATION),
        income_key="middle",
        n_competitors=6,
        comp_price_idx=1.00,      # rivals' typical price ÷ mine (1.0 = same)
        base_orders=p["base_orders"],
        avg_ticket=p["avg_ticket"],
        surge_cap=0.12,           # max surge above normal price (fairness guardrail)
        discount_floor=0.80,      # deepest sale allowed
        use_live_weather=True,
        assumptions=dict(DEFAULT_ASSUMPTIONS),
        products=copy.deepcopy(p["products"]),
        anchor=dt.date.today().isoformat(),
    )
