"""REST routes for the Forecast & Pricing module (Foresight). Thin layer over services.forecasting.

All routes take ?branch= (default: the default branch). Handlers are plain `def` so FastAPI runs the
(CPU/IO heavy) engine work in its thread pool instead of blocking the event loop.
"""
from datetime import date as Date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .config import settings
from .services import catalog, forecasting as fs

router = APIRouter(prefix="/api")


def _branch(branch: Optional[str]) -> str:
    b = branch or settings.default_branch
    if not catalog.branch_exists(b):
        raise HTTPException(404, f"Unknown branch {b!r}")
    return b


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except fs.ForecastError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, f"Not found: {e.args[0]}")


# ------------------------------------------------------------------ schemas
class ActualIn(BaseModel):
    date: Date
    orders: float = Field(ge=0, le=1_000_000)
    revenue: Optional[float] = Field(default=None, ge=0)
    note: str = Field(default="", max_length=200)


class FactorIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start: Date
    end: Date
    effect_pct: float = Field(ge=-90, le=300)
    confidence: float = Field(default=0.6, ge=0, le=1)
    scope: str = "all"
    note: str = Field(default="", max_length=200)


class RivalIn(BaseModel):
    rival: str = Field(default="Rival", max_length=80)
    start: Date
    end: Date
    discount_pct: float = Field(gt=0, le=90)
    note: str = Field(default="", max_length=200)


class LocationIn(BaseModel):
    name: str
    lat: float
    lon: float


class AssumptionsIn(BaseModel):
    growth_pct_month: Optional[float] = None
    sentiment_pct: Optional[float] = None
    prior_strength: Optional[float] = None


class ProfileIn(BaseModel):
    business_name: Optional[str] = Field(default=None, max_length=80)
    income_key: Optional[str] = None
    n_competitors: Optional[int] = None
    comp_price_idx: Optional[float] = None
    base_orders: Optional[float] = None
    avg_ticket: Optional[float] = None
    surge_cap: Optional[float] = None
    discount_floor: Optional[float] = None
    use_live_weather: Optional[bool] = None
    location: Optional[LocationIn] = None
    assumptions: Optional[AssumptionsIn] = None


class ProductIn(BaseModel):
    category: Optional[str] = None
    cost: Optional[float] = None
    price: Optional[float] = None
    elasticity: Optional[float] = None
    elasticity_auto: Optional[bool] = None
    essential: Optional[bool] = None
    perishable: Optional[bool] = None
    temp_sens: Optional[float] = None
    rain_sens: Optional[float] = None
    keywords: Optional[str] = Field(default=None, max_length=200)
    tracked: Optional[bool] = None


class FestivalIn(BaseModel):
    name: str
    start: Date
    end: Optional[Date] = None
    lift: float = 0.3
    lead: int = Field(default=3, ge=0, le=60)
    tail: int = Field(default=1, ge=0, le=30)
    kind: str = "festival"
    aff: Dict[str, float] = {}


class DemoIn(BaseModel):
    days: int = Field(default=21, ge=7, le=60)


# ------------------------------------------------------------------ forecast / pricing / explain
@router.get("/forecast", tags=["forecast"])
def get_forecast(branch: Optional[str] = None, horizon: int = Query(28, ge=1, le=90), history: int = Query(28, ge=0, le=90)):
    """Demand forecast with 50/80% bands. Also freezes today's forecast so the scorecard can grade it later."""
    return _run(fs.forecast, _branch(branch), horizon, history)


@router.get("/pricing", tags=["forecast"])
def get_pricing(branch: Optional[str] = None, date: Optional[Date] = None, days: int = Query(1, ge=1, le=28)):
    """Per product and day: SURGE / SALE / HOLD, price, expected units, prep quantity. Capacity = current stock."""
    return _run(fs.pricing_plan, _branch(branch), date, days)


@router.get("/explain", tags=["forecast"])
def get_explain(branch: Optional[str] = None, date: Optional[Date] = None):
    """% effect of each driver on one day, versus a typical day."""
    return _run(fs.explain, _branch(branch), date)


# ------------------------------------------------------------------ actuals (the learning signal)
@router.get("/actuals", tags=["forecast"])
def get_actuals(branch: Optional[str] = None, limit: int = Query(60, ge=1, le=500)):
    return {"actuals": _run(fs.list_actuals, _branch(branch), limit)}


@router.post("/actuals", tags=["forecast"])
def post_actual(body: ActualIn, branch: Optional[str] = None):
    """Log a real day. Returns how the AI's beliefs about owner factors changed."""
    return _run(fs.log_actual, _branch(branch), body.date, body.orders, body.revenue, body.note, "owner")


@router.delete("/actuals/{date}", tags=["forecast"])
def del_actual(date: Date, branch: Optional[str] = None):
    if not _run(fs.delete_actual, _branch(branch), date):
        raise HTTPException(404, "No sales logged for that date.")
    return {"deleted": date.isoformat()}


@router.post("/actuals/import", tags=["forecast"])
def import_actuals(branch: Optional[str] = None, days: int = Query(30, ge=1, le=90)):
    """Log past days from LivingDoc's own data (orders = outflow events, revenue = cash collected). Tagged source=livingdoc."""
    return _run(fs.import_livingdoc, _branch(branch), days)


@router.delete("/actuals", tags=["forecast"])
def clear_actuals(source: str = Query(..., description="demo | livingdoc | owner"), branch: Optional[str] = None):
    return {"deleted": _run(fs.clear_actuals, _branch(branch), source)}


# ------------------------------------------------------------------ owner inputs
@router.get("/factors", tags=["forecast"])
def get_factors(branch: Optional[str] = None):
    return _run(fs.list_factors, _branch(branch))


@router.get("/factors/suggest", tags=["forecast"])
def suggest_factor(text: str = Query(..., min_length=2, max_length=200)):
    from foresight import owner
    return {"suggestions": owner.suggest_from_text(text)}


@router.post("/factors", tags=["forecast"], status_code=201)
def post_factor(body: FactorIn, branch: Optional[str] = None):
    return _run(fs.add_factor, _branch(branch), body.name, body.start, body.end, body.effect_pct, body.confidence,
                body.scope, body.note)


@router.delete("/factors/{fid}", tags=["forecast"])
def del_factor(fid: int, branch: Optional[str] = None):
    if not _run(fs.delete_factor, _branch(branch), fid):
        raise HTTPException(404, "No such factor.")
    return {"deleted": fid}


@router.get("/rival-promos", tags=["forecast"])
def get_rivals(branch: Optional[str] = None):
    return {"rival_promos": _run(fs.list_rivals, _branch(branch))}


@router.post("/rival-promos", tags=["forecast"], status_code=201)
def post_rival(body: RivalIn, branch: Optional[str] = None):
    return {"id": _run(fs.add_rival, _branch(branch), body.rival, body.start, body.end, body.discount_pct, body.note)}


@router.delete("/rival-promos/{rid}", tags=["forecast"])
def del_rival(rid: int, branch: Optional[str] = None):
    if not _run(fs.delete_rival, _branch(branch), rid):
        raise HTTPException(404, "No such rival promotion.")
    return {"deleted": rid}


# ------------------------------------------------------------------ scorecard / trends
@router.get("/scorecard", tags=["forecast"])
def get_scorecard(branch: Optional[str] = None):
    """Grades only forecasts frozen BEFORE the day: MAPE, bias, 80% coverage, skill vs last-7-day average, profit uplift."""
    return _run(fs.scorecard_payload, _branch(branch))


@router.get("/trends", tags=["forecast"])
def get_trends(branch: Optional[str] = None):
    """Today's cached web-trend scores (or clearly labelled assumed scores). Never hits the network."""
    return _run(fs.trends_payload, _branch(branch))


@router.post("/trends/refresh", tags=["forecast"])
def refresh_trends(branch: Optional[str] = None, force: bool = False):
    """Run the (at most once a day) web search now. Falls back to assumed scores offline."""
    return _run(fs.refresh_trends, _branch(branch), force)


# ------------------------------------------------------------------ setup & demo
@router.get("/foresight/profile", tags=["forecast"])
def get_profile(branch: Optional[str] = None):
    return _run(fs.get_profile, _branch(branch))


@router.put("/foresight/profile", tags=["forecast"])
def put_profile(body: ProfileIn, branch: Optional[str] = None):
    return _run(fs.update_profile, _branch(branch), body.model_dump(exclude_none=True))


@router.put("/foresight/products/{name}", tags=["forecast"])
def put_product(name: str, body: ProductIn, branch: Optional[str] = None):
    return _run(fs.update_product, _branch(branch), name, body.model_dump(exclude_none=True))


@router.get("/foresight/festivals", tags=["forecast"])
def get_fest(branch: Optional[str] = None):
    return _run(fs.list_festivals, _branch(branch))


@router.put("/foresight/festivals", tags=["forecast"])
def put_fest(rows: List[FestivalIn], branch: Optional[str] = None):
    return {"saved": _run(fs.replace_festivals, _branch(branch), [r.model_dump(mode="json") for r in rows])}


@router.post("/foresight/festivals/reset", tags=["forecast"])
def reset_fest(branch: Optional[str] = None):
    return {"saved": _run(fs.reset_festivals, _branch(branch))}


@router.get("/foresight/learned", tags=["forecast"])
def get_learned(branch: Optional[str] = None):
    """Starting (assumed) coefficients vs what the model believes now."""
    return {"drivers": _run(fs.learned, _branch(branch))}


@router.post("/foresight/demo", tags=["forecast"])
def post_demo(body: DemoIn = DemoIn(), branch: Optional[str] = None):
    """Load simulated 'real' sales, tagged source=demo. Clear them with DELETE /api/foresight/demo."""
    return _run(fs.load_demo, _branch(branch), body.days)


@router.delete("/foresight/demo", tags=["forecast"])
def del_demo(branch: Optional[str] = None):
    return {"deleted": _run(fs.clear_demo, _branch(branch))}


@router.post("/foresight/daily", tags=["forecast"])
def run_daily(force: bool = False):
    """Same job as scripts/refresh_daily.py: trends + yesterday's import + freeze today's forecast, for every branch."""
    return _run(fs.daily_refresh, force)
