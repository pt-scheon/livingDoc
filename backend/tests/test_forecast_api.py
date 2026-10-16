"""API tests for the Forecast & Pricing module (/api/forecast, /api/pricing, /api/factors, /api/scorecard, ...)."""
from datetime import date, timedelta

import pytest
from foresight import scorecard as fsc

from app.database import db
from app.services import forecasting

B = "Main Store"
Q = {"branch": B}
TODAY = date.today()


def d(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def fc(client, **kw):
    r = client.get("/api/forecast", params={**Q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def price_rows(client, **kw):
    r = client.get("/api/pricing", params={**Q, **kw})
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def future(j):
    return [x for x in j["days"] if x["is_future"]]


# ------------------------------------------------------------------ forecast
def test_forecast_shape_and_honest_labels(client):
    j = fc(client, horizon=21, history=7)
    assert len(future(j)) == 21 and j["branch"] == B
    x = future(j)[0]
    assert x["lo80"] < x["point"] < x["hi80"] and x["lo50"] < x["point"] < x["hi50"]
    m = j["meta"]
    assert m["weather"]["live_enabled"] is False and "assumed" in m["weather"]["status"]
    assert m["model"]["n_real"] == 0 and m["model"]["n_assumed"] > 0
    a = m["assumptions"]
    assert a["festival_dates"] == a["pay_schedules"] == "assumed" and a["prices_assumed"] >= 1
    assert m["trends"]["source"] == "assumed" and m["actuals"]["demo"] == 0
    assert isinstance(j["festivals"], list)      # spans overlapping the window, for the UI to draw and label


def test_forecast_unknown_branch_and_bounds(client):
    assert client.get("/api/forecast", params={"branch": "Nope"}).status_code == 404
    assert client.get("/api/forecast", params={**Q, "horizon": 0}).status_code == 422
    assert client.get("/api/forecast", params={**Q, "horizon": 500}).status_code == 422


def test_forecast_is_frozen_into_the_log_for_grading(client):
    fc(client, horizon=5, history=0)
    store = forecasting.get_store(B)
    log = store.forecast_log()
    assert len(log) == 5 and set(log["kind"]) == {"forecast"}


def test_each_branch_has_its_own_foresight_store(client):
    fc(client)
    client.post("/api/actuals", params=Q, json={"date": d(-1), "orders": 150})
    other = client.get("/api/actuals", params={"branch": "Navrangpura Branch"}).json()["actuals"]
    assert other == []
    assert forecasting.store_path(B) != forecasting.store_path("Navrangpura Branch")


# ------------------------------------------------------------------ pricing
def test_pricing_maps_inventory_and_respects_stock(client):
    items = {i["name"]: i for i in client.get("/api/items", params=Q).json()["items"]}
    rows = price_rows(client, date=d(0), days=3)
    assert {r["product"] for r in rows} == set(items) and len(rows) == 3 * len(items)
    for r in rows:
        assert r["supply"] == pytest.approx(items[r["product"]]["qty"])      # capacity = real stock
        assert r["label"] in ("SURGE", "SALE", "HOLD") and r["reason_code"]
        assert r["assumed_prices"] is True


def test_essentials_are_never_surged(client):
    rows = price_rows(client, date=d(0), days=28)
    ess = [r for r in rows if r["essential"]]
    assert {r["product"] for r in ess} >= {"Flour", "Sugar", "Milk"}
    assert all(r["label"] != "SURGE" and r["mult"] <= 1.0 + 1e-9 for r in ess)


def test_out_of_stock_gives_no_price_advice(client):
    client.put("/api/items", json={"branch": B, "name": "Sugar", "counted": 0})
    r = next(x for x in price_rows(client, days=1) if x["product"] == "Sugar")
    assert r["supply"] == 0 and r["label"] == "HOLD" and r["reason_code"] == "out_of_stock" and r["mult"] == 1.0


def test_item_without_daily_use_is_reported_not_silently_dropped(client):
    client.put("/api/items", json={"branch": B, "name": "Mystery Spice", "unit": "kg", "counted": 3})
    j = fc(client, horizon=3, history=0)
    assert "Mystery Spice" in j["meta"]["skipped_products"]
    assert "Mystery Spice" not in {r["product"] for r in price_rows(client)}


def test_explain_matches_forecast(client):
    day = d(7)
    e = client.get("/api/explain", params={**Q, "date": day}).json()
    assert e["date"] == day and e["drivers"]
    assert all(set(x) == {"driver", "effect", "kind"} for x in e["drivers"])
    point = next(x["point"] for x in fc(client, horizon=10)["days"] if x["date"] == day)
    assert e["expected_orders"] == pytest.approx(point, rel=0.02)
    assert e["expected_orders"] > 0 and e["typical_orders"] > 0


# ------------------------------------------------------------------ actuals & learning
def test_log_actual_validates_and_learns(client):
    assert client.post("/api/actuals", params=Q, json={"date": d(3), "orders": 100}).status_code == 400    # future
    assert client.post("/api/actuals", params=Q, json={"date": d(-1), "orders": -5}).status_code == 422
    r = client.post("/api/actuals", params=Q, json={"date": d(-1), "orders": 160, "revenue": 33000})
    assert r.status_code == 200 and r.json()["n_real"] == 1
    got = client.get("/api/actuals", params=Q).json()["actuals"]
    assert got[0]["date"] == d(-1) and got[0]["orders"] == 160 and got[0]["source"] == "owner"
    assert fc(client)["meta"]["model"]["n_real"] == 1
    assert client.delete(f"/api/actuals/{d(-1)}", params=Q).status_code == 200
    assert client.delete(f"/api/actuals/{d(-1)}", params=Q).status_code == 404
    assert fc(client)["meta"]["model"]["n_real"] == 0


def test_import_from_livingdoc_is_idempotent_and_clearable(client):
    with db() as c:
        for off in (-3, -2):
            for _ in range(5):
                c.execute("INSERT INTO movements(id,ts,branch,item,change,source,note) VALUES(lower(hex(randomblob(8))),?,?,?,?,?,?)",
                          (f"{d(off)} 11:00:00", B, "Milk", -1, "scanner", "t"))
        c.execute("INSERT INTO cash_events(ts,branch,type,entity,amount,descr) VALUES(?,?,?,?,?,?)",
                  (f"{d(-3)} 20:00:00", B, "collected", "Counter", 2400, "sales"))
    r = client.post("/api/actuals/import", params={**Q, "days": 10}).json()
    assert r["imported"] == 2 and set(r["dates"]) == {d(-3), d(-2)}
    rows = {a["date"]: a for a in client.get("/api/actuals", params=Q).json()["actuals"]}
    with db() as c:
        cash = c.execute("SELECT SUM(amount) s FROM cash_events WHERE branch=? AND type='collected' AND substr(ts,1,10)=?", (B, d(-3))).fetchone()["s"]
    assert rows[d(-3)]["orders"] == 5 and rows[d(-3)]["revenue"] == cash >= 2400 and rows[d(-3)]["source"] == "livingdoc"
    assert client.post("/api/actuals/import", params={**Q, "days": 10}).json()["imported"] == 0
    # an owner-entered number is never overwritten by the import
    client.post("/api/actuals", params=Q, json={"date": d(-2), "orders": 99})
    assert client.delete("/api/actuals", params={**Q, "source": "livingdoc"}).json()["deleted"] == 1
    assert [a["source"] for a in client.get("/api/actuals", params=Q).json()["actuals"]] == ["owner"]
    assert client.delete("/api/actuals", params={**Q, "source": "bogus"}).status_code == 400


# ------------------------------------------------------------------ owner factors / rivals
def test_factor_lifecycle_and_forecast_effect(client):
    base = next(x for x in future(fc(client, horizon=14)) if x["date"] == d(5))
    r = client.post("/api/factors", params=Q, json={"name": "Wedding next door", "start": d(5), "end": d(5),
                                                    "effect_pct": 40, "confidence": 0.6})
    assert r.status_code == 201
    fid = r.json()["id"]
    new = next(x for x in future(fc(client, horizon=14)) if x["date"] == d(5))
    assert new["point"] > base["point"] * 1.15
    assert (new["hi80"] - new["lo80"]) / new["point"] > (base["hi80"] - base["lo80"]) / base["point"]   # wider band
    f = client.get("/api/factors", params=Q).json()
    row = next(x for x in f["factors"] if x["id"] == fid)
    assert row["prior_pct"] == pytest.approx(40 * (0.4 + 0.6 * 0.6)) and row["n_obs"] == 0 and f["library"]
    assert client.delete(f"/api/factors/{fid}", params=Q).status_code == 200
    assert client.delete(f"/api/factors/{fid}", params=Q).status_code == 404
    again = next(x for x in future(fc(client, horizon=14)) if x["date"] == d(5))
    assert again["point"] == pytest.approx(base["point"], rel=1e-6)


def test_factor_validation(client):
    ok = {"name": "x", "start": d(2), "end": d(3), "effect_pct": 10}
    assert client.post("/api/factors", params=Q, json={**ok, "end": d(1)}).status_code == 400
    assert client.post("/api/factors", params=Q, json={**ok, "effect_pct": 900}).status_code == 422
    assert client.post("/api/factors", params=Q, json={**ok, "confidence": 2}).status_code == 422
    assert client.post("/api/factors", params=Q, json={**ok, "scope": "spaceships"}).status_code == 400
    assert client.post("/api/factors", params=Q, json={**ok, "name": "  "}).status_code in (400, 422)


def test_ai_belief_moves_toward_reality(client):
    """Owner says +60%; reality shows ~+5%. Logging the real days must pull the AI's belief down (and show it)."""
    baseline = {x["date"]: x["point"] for x in fc(client, horizon=1, history=14)["days"]}
    baseline = {off: baseline[d(off)] for off in range(-12, 0)}     # what the AI expects with NO factor
    fid = client.post("/api/factors", params=Q, json={"name": "Cousin wedding", "start": d(-6), "end": d(-4),
                                                      "effect_pct": 60, "confidence": 0.3}).json()["id"]
    prior = next(x for x in client.get("/api/factors", params=Q).json()["factors"] if x["id"] == fid)["prior_pct"]
    changes = None
    for off in range(-12, 0):
        base = baseline[off]
        boost = 1.05 if -6 <= off <= -4 else 1.0
        changes = client.post("/api/actuals", params=Q, json={"date": d(off), "orders": round(base * boost)}).json()["factor_changes"]
    row = next(x for x in client.get("/api/factors", params=Q).json()["factors"] if x["id"] == fid)
    assert row["n_obs"] == 3 and row["belief_pct"] < prior and row["belief_pct"] > 0
    assert any(c["factor"] == "Cousin wedding" for c in changes)


def test_rival_promos(client):
    base = next(x for x in future(fc(client, horizon=10)) if x["date"] == d(4))["point"]
    r = client.post("/api/rival-promos", params=Q, json={"rival": "Sweet Hub", "start": d(4), "end": d(4), "discount_pct": 25})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get("/api/rival-promos", params=Q).json()["rival_promos"][0]["rival"] == "Sweet Hub"
    assert next(x for x in future(fc(client, horizon=10)) if x["date"] == d(4))["point"] < base
    assert client.post("/api/rival-promos", params=Q, json={"start": d(4), "end": d(3), "discount_pct": 10}).status_code == 400
    assert client.post("/api/rival-promos", params=Q, json={"start": d(4), "end": d(4), "discount_pct": 0}).status_code == 422
    assert client.delete(f"/api/rival-promos/{rid}", params=Q).status_code == 200
    assert client.delete(f"/api/rival-promos/{rid}", params=Q).status_code == 404


def test_factor_suggestions(client):
    s = client.get("/api/factors/suggest", params={"text": "my cousin's wedding is on our street"}).json()["suggestions"]
    assert s and s[0]["name"].startswith("Wedding")
    assert client.get("/api/factors/suggest", params={"text": "xyzzy"}).json()["suggestions"] == []


# ------------------------------------------------------------------ demo, scorecard
def test_scorecard_empty_then_demo_then_cleared(client):
    sc = client.get("/api/scorecard", params=Q).json()
    assert sc["metrics"] == {} and sc["verdict"][0]["code"] == "empty"
    r = client.post("/api/foresight/demo", params=Q, json={"days": 21})
    assert r.status_code == 200 and len(r.json()["hidden_event_dates"]) == 3
    j = fc(client)
    assert j["meta"]["actuals"]["demo"] == 21 and j["meta"]["actuals"]["by_source"] == {"demo": 21}   # always labelled
    sc = client.get("/api/scorecard", params=Q).json()
    assert sc["metrics"]["n"] == 21 and sc["metrics"]["mape"] < 0.25
    assert all(0 <= x["lo80"] <= x["hi80"] for x in sc["rows"])
    # structured verdict mirrors Foresight's own wording logic (same statuses, same count)
    assert [v["status"] for v in sc["verdict"]] == [s for s, _ in fsc.verdict(sc["metrics"])]
    assert client.post("/api/foresight/demo", params=Q, json={"days": 21}).status_code == 400    # never overwrite days
    assert client.delete("/api/foresight/demo", params=Q).json()["deleted"] == 21
    assert fc(client)["meta"]["actuals"]["total"] == 0
    assert client.get("/api/scorecard", params=Q).json()["metrics"] == {}


def test_demo_refuses_to_overwrite_real_days(client):
    client.post("/api/actuals", params=Q, json={"date": d(-2), "orders": 120})
    assert client.post("/api/foresight/demo", params=Q, json={"days": 14}).status_code == 400
    assert client.get("/api/actuals", params=Q).json()["actuals"][0]["source"] == "owner"


def test_learned_vs_prior(client):
    client.post("/api/foresight/demo", params=Q, json={"days": 21})
    dr = client.get("/api/foresight/learned", params=Q).json()["drivers"]
    pay = next(x for x in dr if x["driver"].startswith("Payday"))
    assert pay["learned"] != pay["assumed"]


# ------------------------------------------------------------------ trends
def test_trends_offline_are_labelled_assumed(client):
    t = client.get("/api/trends", params=Q).json()
    assert t["source"] == "assumed" and t["fresh"] is False and t["scores"]
    r = client.post("/api/trends/refresh", params=Q).json()
    assert r["source"] == "assumed" and r["n_results"] == 0
    t = client.get("/api/trends", params=Q).json()
    assert t["fresh"] is True and t["source"] == "assumed" and t["day"] == TODAY.isoformat()


def test_trends_web_results_are_scored_and_labelled_web(client, monkeypatch):
    from foresight import trends
    hit = [dict(title="Kaju katli demand surges", body="gift hamper and coffee beans sell fast", url=f"u{i}", query="q") for i in range(12)]
    monkeypatch.setattr(trends, "_search", lambda *a, **k: hit)
    r = client.post("/api/trends/refresh", params={**Q, "force": True}).json()
    assert r["source"] == "web"
    t = client.get("/api/trends", params=Q).json()
    assert t["source"] == "web" and t["headlines"] and all(0 <= x["score"] <= 1.5 for x in t["scores"])


# ------------------------------------------------------------------ setup: profile, products, festivals
def test_product_settings_flow_into_pricing(client):
    r = client.put("/api/foresight/products/Ghee", params=Q, json={"price": 700, "cost": 500})
    assert r.status_code == 200
    p = r.json()
    assert p["assumed_prices"] is False and p["elasticity"] == pytest.approx(700 / 200, rel=1e-3) and p["elasticity_auto"]
    row = next(x for x in price_rows(client) if x["product"] == "Ghee")
    assert row["base_price"] == 700 and row["assumed_prices"] is False
    over = client.put("/api/foresight/products/Ghee", params=Q, json={"elasticity": 2.0}).json()
    assert over["elasticity"] == 2.0 and over["elasticity_auto"] is False
    client.put("/api/foresight/products/Ghee", params=Q, json={"price": 720})
    assert next(p for p in client.get("/api/foresight/profile", params=Q).json()["products"] if p["name"] == "Ghee")["elasticity"] == 2.0
    assert client.put("/api/foresight/products/Ghee", params=Q, json={"cost": 900}).status_code == 400
    assert client.put("/api/foresight/products/Ghee", params=Q, json={"category": "weapons"}).status_code == 400
    assert client.put("/api/foresight/products/Nope", params=Q, json={"price": 5}).status_code == 404
    off = client.put("/api/foresight/products/Ghee", params=Q, json={"tracked": False}).json()
    assert off["tracked"] is False
    assert "Ghee" not in {x["product"] for x in price_rows(client)}


def test_profile_update_and_validation(client):
    r = client.put("/api/foresight/profile", params=Q, json={"n_competitors": 2, "surge_cap": 0.05,
                                                             "location": {"name": "Surat", "lat": 21.17, "lon": 72.83},
                                                             "assumptions": {"growth_pct_month": 2.0}})
    assert r.status_code == 200
    p = r.json()["profile"]
    assert p["n_competitors"] == 2 and p["surge_cap"] == 0.05 and p["location"]["name"] == "Surat" and p["assumptions"]["growth_pct_month"] == 2.0
    assert client.put("/api/foresight/profile", params=Q, json={"surge_cap": 5}).status_code == 400
    assert client.put("/api/foresight/profile", params=Q, json={"income_key": "royal"}).status_code == 400
    assert client.put("/api/foresight/profile", params=Q, json={"location": {"name": "X", "lat": 99, "lon": 0}}).status_code == 400
    # the switch for live weather cannot be forced on when the deployment forbids it (tests set LIVE=0)
    assert client.put("/api/foresight/profile", params=Q, json={"use_live_weather": True}).json()["profile"]["use_live_weather"] is False
    assert fc(client)["meta"]["location"] == "Surat"


def test_festival_calendar_is_editable_and_resettable(client):
    f = client.get("/api/foresight/festivals", params=Q).json()
    assert any(x["name"] == "Diwali" for x in f["festivals"]) and f["livingdoc_festivals"]
    new = [{"name": "Local Mela", "start": d(6), "end": d(8), "lift": 0.5, "lead": 2, "tail": 1, "aff": {"sweets": 1.5}}]
    assert client.put("/api/foresight/festivals", params=Q, json=new).json()["saved"] == 1
    j = fc(client, horizon=14)
    assert any(x["fest_name"] == "Local Mela" for x in future(j))
    bad = [{"name": "Oops", "start": d(6), "end": d(2)}]
    assert client.put("/api/foresight/festivals", params=Q, json=bad).status_code == 400
    assert client.post("/api/foresight/festivals/reset", params=Q).json()["saved"] >= 5
    assert any(x["name"] == "Diwali" for x in client.get("/api/foresight/festivals", params=Q).json()["festivals"])


# ------------------------------------------------------------------ daily job & misc
def test_daily_refresh_covers_every_branch_and_marks_done(client):
    out = client.post("/api/foresight/daily").json()
    assert set(out) == {"Main Store", "Navrangpura Branch"} and out["Main Store"]["trends"]["source"] == "assumed"
    assert out["Main Store"]["forecast_days"] == 28
    assert forecasting.daily_if_due() is False        # already ran today


def test_bad_state_is_a_400_not_a_crash(client):
    with db() as c:
        c.execute("UPDATE items SET baseline_burn=0 WHERE branch=?", (B,))
    r = client.get("/api/forecast", params=Q)
    assert r.status_code == 400 and "No tracked products" in r.json()["detail"]


def test_openapi_lists_the_new_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/forecast", "/api/pricing", "/api/explain", "/api/actuals", "/api/factors", "/api/rival-promos",
              "/api/scorecard", "/api/trends", "/api/foresight/demo"):
        assert p in paths
