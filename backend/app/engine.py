"""
Festive Inventory Prediction Engine
===================================
Predicts stock-outs for small businesses while accounting for festival demand
surges, supplier shutdowns and perishable spoilage.

Rules implemented (all dates are calendar days):
  * Surge:      burn rate x surge_multiplier for the 7 days leading up to the
                festival, plus the festival day itself (INCLUDE_FESTIVAL_DAY).
  * Blackout:   adjusted lead time = standard lead time + supplier_blackout_days.
  * Deadline:   stock must ARRIVE at least 48 hours before the surge begins, and
                also before the shelf runs empty -> whichever is earlier wins.
  * Perishable: if the batch would outlive its shelf life after the festival the
                order is capped and staged deliveries are recommended.

Run this file to see the self-test (normal vs festive reorder dates).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# ==== ENGINE START ====
SURGE_DAYS = 7              # days of surge before the festival
ARRIVAL_BUFFER_DAYS = 2     # stock must land 48h before the surge starts
SAFETY_FACTOR = 1.10        # 10% buffer on festival demand
HORIZON_DAYS = 400          # simulation horizon for stock-out search
LOOKAHEAD_DAYS = 120        # only festivals within this window are considered
INCLUDE_FESTIVAL_DAY = True # festival day itself is a surge day


def _to_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _surge_window(fd: date):
    start = fd - timedelta(days=SURGE_DAYS)
    end = fd if INCLUDE_FESTIVAL_DAY else fd - timedelta(days=1)
    return start, end


def _rate(day: date, base: float, start: date, end: date, mult: float) -> float:
    return base * mult if start <= day <= end else base


def _days_until_stockout(stock, base, today, start, end, mult) -> Optional[float]:
    """Fractional days from the start of `today` until stock hits zero."""
    if base <= 0:
        return None
    remaining = float(stock)
    if remaining <= 0:
        return 0.0
    for i in range(HORIZON_DAYS):
        r = _rate(today + timedelta(days=i), base, start, end, mult)
        if remaining <= r:
            return i + remaining / r
        remaining -= r
    return None


def _demand(base, first: date, last: date, start, end, mult) -> float:
    total, d = 0.0, first
    while d <= last:
        total += _rate(d, base, start, end, mult)
        d += timedelta(days=1)
    return total


def _floor1(x: float) -> float:
    return math.floor(x * 10 + 1e-9) / 10


def _num(x: float):
    x = float(x)
    return int(x) if x.is_integer() else round(x, 2)


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _urgency(must: Optional[date], today: date) -> str:
    if must is None:
        return "LOW"
    days = (must - today).days
    if days <= 2:
        return "CRITICAL"
    if days <= 5:
        return "HIGH"
    if days <= 10:
        return "MEDIUM"
    return "LOW"


def _analyse(stock, base, fest, lead, today, shelf_life) -> Dict[str, Any]:
    fd, mult, blackout = fest["date"], fest["mult"], fest["blackout"]
    start, end = _surge_window(fd)
    lead_adj = lead + blackout
    arrive_by = start - timedelta(days=ARRIVAL_BUFFER_DAYS)
    by_surge = arrive_by - timedelta(days=lead_adj)

    t_out = _days_until_stockout(stock, base, today, start, end, mult)
    stockout = today + timedelta(days=int(math.floor(t_out))) if t_out is not None else None
    by_stock = stockout - timedelta(days=lead_adj) if stockout else None

    demand_fest = _demand(base, today, fd, start, end, mult)
    post_cover = base * lead
    qty_raw = max(0, math.ceil((demand_fest + post_cover) * SAFETY_FACTOR - stock - 1e-9))
    needs = qty_raw > 0

    if needs:
        must = min([by_surge] + ([by_stock] if by_stock else []))
    else:
        must = by_stock

    qty, overstock, staged_every = qty_raw, False, None
    if shelf_life and needs:
        ref = max(must, today) if must else today
        arrival = ref + timedelta(days=lead_adj)
        age_at_fest = max(0, (fd - arrival).days)
        remaining = shelf_life - age_at_fest
        leftover = stock + qty_raw - demand_fest
        sellable = base * max(remaining, 0)
        if leftover > sellable + 1e-9:
            overstock = True
            need_fest = max(0, math.ceil(demand_fest - stock - 1e-9))
            cap = max(0, math.floor(sellable + demand_fest - stock + 1e-9))
            qty = max(need_fest, min(qty_raw, cap))
        if age_at_fest > shelf_life:
            staged_every = max(1, int(shelf_life) - 1)

    return dict(fest=fest, start=start, end=end, lead_adj=lead_adj, arrive_by=arrive_by,
                by_surge=by_surge, by_stock=by_stock, stockout=stockout, must=must,
                needs=needs, qty=qty, qty_raw=qty_raw, overstock=overstock,
                staged_every=staged_every)


def _record(item, stock, base, lead, today, shelf, a: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    days_normal = stock / base
    normal_reorder = today + timedelta(days=int(math.floor(days_normal))) - timedelta(days=lead)
    rec: Dict[str, Any] = {
        "item": item,
        "current_stock": _num(stock),
        "baseline_burn": _num(base),
    }
    if a is None:
        must = normal_reorder
        rec.update({
            "festive_burn": _num(base),
            "days_left_normal": _floor1(days_normal),
            "days_left_festive": _floor1(days_normal),
            "festival_name": None,
            "supplier_lead_time_adjusted": f"{lead} days ({lead} normal + 0 holiday lag)",
            "must_order_by": must.isoformat(),
            "normal_reorder_date": normal_reorder.isoformat(),
            "recommended_order_qty": None,
            "perishable": bool(shelf),
            "overstock_risk": False,
            "urgency": _urgency(must, today),
            "alert": (f"No upcoming festival. At normal pace stock lasts {_fmt(_floor1(days_normal))} days; "
                      f"reorder by {must.strftime('%A')}, {must.isoformat()}."),
        })
        return rec

    f, mult, blackout = a["fest"], a["fest"]["mult"], a["fest"]["blackout"]
    must = a["must"]
    days_fest = stock / (base * mult)
    parts: List[str] = []
    if mult > 1:
        parts.append(f"{f['name']} surge ({mult:g}x from {a['start'].strftime('%d %b')}) would exhaust stock in "
                     f"{_fmt(_floor1(days_fest))} days instead of {_fmt(_floor1(days_normal))}.")
    if blackout > 0:
        parts.append(f"Suppliers are shut or slow for {blackout} days around the festival, so lead time grows "
                     f"from {lead} to {a['lead_adj']} days.")
    if a["needs"]:
        wd = must.strftime("%A")
        if must < today:
            so = f" and expect shortages from {a['stockout'].strftime('%d %b')}" if a["stockout"] else ""
            parts.append(f"Your last safe order date ({wd} {must.strftime('%d %b')}) has already passed: "
                         f"order TODAY with express delivery{so}.")
        elif must == today:
            parts.append(f"Order TODAY ({wd}): this is your last safe order date.")
        else:
            parts.append(f"Your last chance to order is {wd}, {must.strftime('%d %b %Y')}.")
        parts.append(f"Suggested order quantity: {a['qty']:g}.")
    else:
        parts.append("Current stock covers this festival; no festival order needed.")
    if a["overstock"]:
        parts.append(f"Perishable overstock guard: order reduced from {a['qty_raw']:g} to {a['qty']:g} so "
                     f"leftover stock does not spoil after the festival.")
    if a["staged_every"]:
        parts.append(f"Shelf life ({shelf} days) is shorter than the gap between delivery and the festival: "
                     f"take staged deliveries about every {a['staged_every']} days instead of one big order.")

    rec.update({
        "festive_burn": _num(base * mult),
        "days_left_normal": _floor1(days_normal),
        "days_left_festive": _floor1(days_fest),
        "festival_name": f["name"],
        "festival_date": f["date"].isoformat(),
        "surge_window": f"{a['start'].isoformat()} to {a['end'].isoformat()}",
        "supplier_lead_time_adjusted": f"{a['lead_adj']} days ({lead} normal + {blackout} holiday lag)",
        "must_order_by": must.isoformat() if must else None,
        "must_order_by_weekday": must.strftime("%A") if must else None,
        "normal_reorder_date": normal_reorder.isoformat(),
        "stock_must_arrive_by": a["arrive_by"].isoformat(),
        "projected_stockout_date": a["stockout"].isoformat() if a["stockout"] else None,
        "recommended_order_qty": a["qty"],
        "perishable": bool(shelf),
        "overstock_risk": a["overstock"],
        "staged_delivery_every_days": a["staged_every"],
        "urgency": _urgency(must, today),
        "alert": " ".join(parts),
    })
    return rec


def predict_inventory(stock: Dict[str, float],
                      baseline_burn: Dict[str, float],
                      festivals: List[Dict[str, Any]],
                      lead_time_days: int = 3,
                      today: Any = None,
                      perishables: Optional[Dict[str, int]] = None,
                      lookahead_days: int = LOOKAHEAD_DAYS) -> List[Dict[str, Any]]:
    """Return one prediction record per item (most urgent upcoming festival wins).

    festivals: [{"name","date","surge_multiplier","supplier_blackout_days"}]
    perishables: {item: shelf_life_days}
    """
    today_d = _to_date(today) if today else date.today()
    perishables = perishables or {}
    if lead_time_days < 0:
        raise ValueError("lead_time_days must be >= 0")

    upcoming = []
    for f in festivals or []:
        fd = _to_date(f["date"])
        mult = float(f.get("surge_multiplier", 1.0))
        blackout = int(f.get("supplier_blackout_days", 0))
        if mult <= 0:
            raise ValueError(f"surge_multiplier must be > 0 ({f.get('name')})")
        if blackout < 0:
            raise ValueError(f"supplier_blackout_days must be >= 0 ({f.get('name')})")
        if today_d <= fd <= today_d + timedelta(days=lookahead_days):
            upcoming.append({"name": f["name"], "date": fd, "mult": mult, "blackout": blackout})

    results: List[Dict[str, Any]] = []
    for item, qty in stock.items():
        qty = max(0.0, float(qty))
        base = float(baseline_burn.get(item, 0) or 0)
        shelf = perishables.get(item)
        if base <= 0:
            results.append({"item": item, "current_stock": _num(qty), "baseline_burn": 0,
                            "urgency": "NO_DATA", "festival_name": None, "must_order_by": None,
                            "alert": "No sales history yet, so no prediction is possible."})
            continue
        analyses = [_analyse(qty, base, f, lead_time_days, today_d, shelf) for f in upcoming]
        if analyses:
            best = min(analyses, key=lambda a: (not a["needs"], a["must"] or date.max, a["fest"]["date"]))
        else:
            best = None
        results.append(_record(item, qty, base, lead_time_days, today_d, shelf, best))
    return results
# ==== ENGINE END ====


# ==== SELF-TEST ====
def _run_self_test() -> None:
    today = "2026-10-16"
    stock = {"Ghee": 20, "Flour": 50, "Gift Boxes": 30, "Fresh Mithai": 15}
    burn = {"Ghee": 1.5, "Flour": 4.0, "Gift Boxes": 2.0, "Fresh Mithai": 3.0}
    diwali = {"name": "Diwali", "date": "2026-11-01", "surge_multiplier": 2.8, "supplier_blackout_days": 4}
    shelf = {"Fresh Mithai": 4}

    normal = predict_inventory(stock, burn, [], 3, today, shelf)
    festive = predict_inventory(stock, burn, [diwali], 3, today, shelf)

    print(f"Today: {today} | Diwali: {diwali['date']} | lead time 3d + 4d blackout\n")
    print(f"{'Item':<14}{'Normal reorder':<16}{'Festive deadline':<18}{'Moved earlier by':<18}{'Urgency':<10}Qty")
    for n, f in zip(normal, festive):
        diff = (_to_date(n["must_order_by"]) - _to_date(f["must_order_by"])).days
        print(f"{f['item']:<14}{n['must_order_by']:<16}{f['must_order_by']:<18}{str(diff) + ' days':<18}"
              f"{f['urgency']:<10}{f['recommended_order_qty']}")
    print("\nFull JSON for Gift Boxes:")
    gb = next(r for r in festive if r["item"] == "Gift Boxes")
    print(json.dumps(gb, indent=2))

    # ---- assertions ----
    assert gb["supplier_lead_time_adjusted"] == "7 days (3 normal + 4 holiday lag)"
    assert gb["festive_burn"] == 5.6 and gb["days_left_normal"] == 15.0 and gb["days_left_festive"] == 5.3
    assert gb["stock_must_arrive_by"] == "2026-10-23"          # 48h before surge start 2026-10-25
    assert gb["must_order_by"] == "2026-10-16" and gb["urgency"] == "CRITICAL"
    assert gb["normal_reorder_date"] == "2026-10-28"
    for n, f in zip(normal, festive):
        assert _to_date(f["must_order_by"]) < _to_date(n["must_order_by"]), f["item"]

    # blackout days push the deadline earlier by exactly that many days
    item_s, item_b = {"Atta": 80}, {"Atta": 4.0}
    d0 = dict(diwali, supplier_blackout_days=0)
    r0 = predict_inventory(item_s, item_b, [d0], 3, today)[0]
    r4 = predict_inventory(item_s, item_b, [diwali], 3, today)[0]
    assert (_to_date(r0["must_order_by"]) - _to_date(r4["must_order_by"])).days == 4

    # perishable guard: batch cannot be held 9 days with 4-day shelf life
    mi = next(r for r in festive if r["item"] == "Fresh Mithai")
    assert mi["overstock_risk"] is True and mi["staged_delivery_every_days"] == 3
    assert mi["recommended_order_qty"] < 99
    assert next(r for r in festive if r["item"] == "Ghee")["overstock_risk"] is False

    # already inside the surge window -> overdue, still CRITICAL
    late = predict_inventory({"Gift Boxes": 30}, {"Gift Boxes": 2.0}, [diwali], 3, "2026-10-28")[0]
    assert late["urgency"] == "CRITICAL" and _to_date(late["must_order_by"]) < _to_date("2026-10-28")

    # past festivals ignored, no-festival path works, zero burn handled
    past = predict_inventory({"X": 10}, {"X": 1}, [dict(diwali, date="2026-10-01")], 3, today)[0]
    assert past["festival_name"] is None
    assert predict_inventory({"Y": 5}, {}, [diwali], 3, today)[0]["urgency"] == "NO_DATA"

    # plenty of stock -> no order needed
    big = predict_inventory({"Z": 1000}, {"Z": 2.0}, [diwali], 3, today)[0]
    assert big["recommended_order_qty"] == 0 and big["urgency"] == "LOW"
    print("\nAll self-tests passed.")


if __name__ == "__main__":
    _run_self_test()
