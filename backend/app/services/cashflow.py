"""Promise -> cash-flow predictor.

Turns the open money promises in the trust ledger into a day-by-day cash forecast with an honest range.

Model (every number below is an editable assumption, returned with the forecast):
* Money owed TO us arrives only if the promise is kept. P(kept) = the counterparty's trust score (new people: 80%),
  shrunk for lateness: x exp(-days overdue / 120), and x 0.6 if the counterparty disputes the figure.
* If kept, it arrives on the due date plus a random delay (exponential; mean = that person's own average delay, or 3 days).
  Already overdue: it arrives in the future with a mean delay of max(7, half the days already overdue).
* The amount counted is the CONSERVATIVE figure: the lower of the two views when they differ.
* Money WE owe is assumed paid on its due date (or today if overdue): outflows are certain, inflows are not.
* Favours and spoken words carry no cash.
* The range comes from 2,000 seeded simulations of those draws (same ledger -> same answer).
* Optional: add expected sales from the Foresight forecast (forecast orders x average bill: an assumption).
"""
from __future__ import annotations

import hashlib
import math
from datetime import timedelta

import numpy as np

from . import trust

SIMS = 2000
SHORTFALL_P = 0.20            # warn on the first day with at least this chance of the balance being below zero
PRIOR_DELAY = 3.0
OVERDUE_DECAY_DAYS = 120.0
DISPUTE_FACTOR = 0.6


def predict(branch: str, horizon: int = 60, opening_cash: float | None = None, include_sales: bool = False) -> dict:
    horizon = max(7, min(int(horizon), 120))
    data = trust.ledger(branch)
    with_raw = data["entries"]
    scores = {p["key"]: p for p in data["parties"]}
    start = trust.today()
    days = [start + timedelta(days=i) for i in range(horizon)]
    seed_src = "|".join(f"{e['id']}:{e['conservative_amount']}:{e['status']}:{e['due_effective']}" for e in with_raw) + f"|{start}|{horizon}"
    rng = np.random.default_rng(int(hashlib.sha256(seed_src.encode()).hexdigest()[:12], 16))

    inflow = np.zeros((SIMS, horizon))
    outflow = np.zeros(horizon)
    items = []
    for e in with_raw:
        if e["status"] != "open" or e["kind"] not in ("owed_to_us", "we_owe"):
            continue
        amt = e["conservative_amount"]
        if amt <= 0:
            continue
        due = trust._d(e["due_effective"]) or start
        sc = scores.get(trust.key_of(e["counterparty"]), {})
        flags = []
        if e["kind"] == "we_owe":
            idx = max((due - start).days, 0)
            if idx < horizon:
                outflow[idx] += amt
            items.append(dict(id=e["id"], counterparty=e["counterparty"], kind=e["kind"], amount=amt, p_kept=1.0, p_in_window=1.0 if idx < horizon else 0.0,
                              expected_date=days[min(idx, horizon - 1)].isoformat() if idx < horizon else None, overdue_days=e["overdue_days"], flags=["committed"]))
            continue
        p = sc.get("score", trust.PRIOR_P)
        od = e["overdue_days"]
        if od > 0:
            p *= math.exp(-od / OVERDUE_DECAY_DAYS)
            flags.append("overdue")
        if e["disputed_effective"]:
            p *= DISPUTE_FACTOR
            flags.append("disputed")
        if e["amount"] is not None and e["cp_amount"] is not None and amt < e["open_amount"] - 0.004:
            flags.append("lower_figure_used")
        if sc.get("resolved", 0) == 0:
            flags.append("no_history")
        mean_delay = sc.get("avg_delay_days") if sc.get("avg_delay_days") not in (None, 0) else PRIOR_DELAY
        base = max((due - start).days, 0)
        if od > 0:
            mean_delay = max(7.0, od / 2.0)
        kept = rng.random(SIMS) < p
        delay = rng.exponential(max(mean_delay, 0.5), SIMS)
        pay = base + np.floor(delay).astype(int)
        hit = kept & (pay < horizon)
        rows = np.nonzero(hit)[0]
        inflow[rows, pay[rows]] += amt
        med = None
        if hit.any():
            med = days[int(np.median(pay[hit]))].isoformat()
        items.append(dict(id=e["id"], counterparty=e["counterparty"], kind=e["kind"], amount=amt, p_kept=round(p, 3),
                          p_in_window=round(float(hit.mean()), 3), expected_date=med, overdue_days=od, flags=flags))

    sales = np.zeros(horizon)
    sales_note = None
    if include_sales:
        try:
            from . import forecasting
            f = forecasting.forecast(branch, horizon, 0)
            ticket = float(f["meta"]["assumptions"]["avg_ticket"])
            for i, d in enumerate(f["days"][:horizon]):
                sales[i] = d["point"] * ticket
            sales_note = "Expected sales = Foresight forecast orders x average bill (an assumption), shown separately from promises."
        except Exception as ex:          # the promise forecast must work even if the sales forecast cannot
            sales_note = f"Sales forecast unavailable ({ex}); showing promises only."
    net = inflow - outflow[None, :] + sales[None, :]
    cum = np.cumsum(net, axis=1) + (opening_cash or 0.0)
    p10, p50, p90 = (np.percentile(cum, q, axis=0) for q in (10, 50, 90))
    exp_in, exp_out = inflow.mean(axis=0), outflow
    p_neg = (cum < 0).mean(axis=0)
    short_idx = int(np.argmax(p_neg >= SHORTFALL_P)) if opening_cash is not None and (p_neg >= SHORTFALL_P).any() else None
    total_in_exp = float(inflow.sum(axis=1).mean())
    receivable_total = sum(i["amount"] for i in items if i["kind"] == "owed_to_us")
    by_party: dict[str, float] = {}
    for i in items:
        if i["kind"] == "owed_to_us":
            by_party[i["counterparty"]] = by_party.get(i["counterparty"], 0.0) + i["amount"] * i["p_in_window"]
    top = max(by_party.items(), key=lambda kv: kv[1], default=(None, 0.0))
    share = top[1] / total_in_exp if total_in_exp > 0 else 0.0
    warnings = []
    if short_idx is not None:
        warnings.append(dict(code="shortfall", date=days[short_idx].isoformat(), p=round(float(p_neg[short_idx]), 2)))
    if len(by_party) >= 2 and share > 0.5:
        warnings.append(dict(code="concentration", who=top[0], share=round(share, 2)))
    if any("overdue" in i["flags"] for i in items):
        warnings.append(dict(code="overdue_inflows", n=sum(1 for i in items if "overdue" in i["flags"])))
    if any("disputed" in i["flags"] for i in items):
        warnings.append(dict(code="disputed_inflows", n=sum(1 for i in items if "disputed" in i["flags"])))
    return dict(
        branch=branch, start=start.isoformat(), horizon=horizon, opening_cash=opening_cash, simulations=SIMS,
        days=[dict(date=d.isoformat(), in_expected=round(float(exp_in[i]), 2), out_expected=round(float(exp_out[i]), 2),
                   sales_expected=round(float(sales[i]), 2), net_p10=round(float(p10[i]), 2), net_p50=round(float(p50[i]), 2),
                   net_p90=round(float(p90[i]), 2), p_negative=round(float(p_neg[i]), 3)) for i, d in enumerate(days)],
        items=sorted(items, key=lambda i: -i["amount"]),
        summary=dict(expected_in=round(total_in_exp, 2), committed_out=round(float(outflow.sum()), 2), receivable_considered=round(receivable_total, 2),
                     at_risk=round(max(receivable_total - total_in_exp, 0.0), 2), top_dependency=top[0], top_share=round(share, 3),
                     first_shortfall=days[short_idx].isoformat() if short_idx is not None else None,
                     end_p10=round(float(p10[-1]), 2), end_p50=round(float(p50[-1]), 2), end_p90=round(float(p90[-1]), 2)),
        warnings=warnings,
        assumptions=dict(prior_reliability=trust.PRIOR_P, prior_weight=trust.PRIOR_N, late_weight=trust.LATE_WEIGHT, default_terms_days=trust.DEFAULT_TERMS_DAYS,
                         prior_delay_days=PRIOR_DELAY, overdue_decay_days=OVERDUE_DECAY_DAYS, dispute_factor=DISPUTE_FACTOR,
                         shortfall_probability=SHORTFALL_P, outflows="paid on the due date (certain)", favours="no cash value counted",
                         amount_used="lower of the two figures for money owed to us", sales=sales_note, opening_cash_given=opening_cash is not None),
    )
