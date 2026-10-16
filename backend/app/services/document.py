"""Builds the living document from SQLite state: structured JSON for the UI and Markdown for export."""
from datetime import date, timedelta

from ..config import settings, now_dt, now_str, parse_ts
from ..database import db, meta_get
from ..engine import predict_inventory
from ..i18n import tr
from ..textutil import fmt_money, fmt_qty, md_esc
from .inventory import burn_info



def gather_burns(c, branch):
    burns = {}
    for it in c.execute("SELECT name, baseline_burn FROM items WHERE branch=?", (branch,)).fetchall():
        burns[it["name"]] = burn_info(c, branch, it["name"], it["baseline_burn"])
    return burns


def forecast_rows(c, branch, burns, today=None):
    items = c.execute("SELECT name, qty, shelf_life_days FROM items WHERE branch=?", (branch,)).fetchall()
    fest = [{"name": f["name"], "date": f["date"], "surge_multiplier": f["surge_multiplier"],
             "supplier_blackout_days": f["supplier_blackout_days"]} for f in c.execute("SELECT * FROM festivals")]
    lead = int(meta_get(c, "lead_days", settings.supplier_lead_days))
    res = predict_inventory({i["name"]: i["qty"] for i in items}, {n: b["burn"] for n, b in burns.items()}, fest,
                            lead, today or date.today(), {i["name"]: i["shelf_life_days"] for i in items if i["shelf_life_days"]})
    return [r for r in res if r["urgency"] in ("CRITICAL", "HIGH", "MEDIUM")], lead


def detect_auto_risks(c, branch, lang, burns, lead):
    """Risks computed from current state (never stored): stock, debts, stale promises, scanner/sync health."""
    out, now = [], now_dt()
    for it in c.execute("SELECT * FROM items WHERE branch=? ORDER BY name", (branch,)).fetchall():
        b = burns[it["name"]]
        if it["qty"] <= 0:
            out.append(tr(lang, "risk_out", item=it["name"]))
        elif b["burn"] > 0 and it["qty"] / b["burn"] < lead:
            out.append(tr(lang, "risk_runout", item=it["name"], days=f"{it['qty'] / b['burn']:.1f}", lead=lead))
        if it["needs_review"]:
            out.append(tr(lang, "risk_review", item=it["name"]))
        if it["qty"] > 0 and b["history_days"] >= 14 and b["out30"] <= 0:
            out.append(tr(lang, "risk_dead", item=it["name"], qty=fmt_qty(it["qty"]), unit=it["unit"]))
    debts = c.execute("SELECT entity, amount-settled AS bal, ts FROM cash_events WHERE branch=? AND type='owed' AND amount-settled>0.004", (branch,)).fetchall()
    by_entity = {}
    for d in debts:
        age = (now - parse_ts(d["ts"])).days
        if age >= 7:
            out.append(tr(lang, "risk_overdue", entity=d["entity"], amount=fmt_money(d["bal"]), days=age))
        by_entity[d["entity"]] = by_entity.get(d["entity"], 0) + d["bal"]
    total = sum(by_entity.values())
    if total >= 1000 and by_entity:
        who, amt = max(by_entity.items(), key=lambda kv: kv[1])
        if amt / total >= 0.6 and len(by_entity) > 1:
            out.append(tr(lang, "risk_conc", pct=round(100 * amt / total), entity=who))
    for p in c.execute("SELECT person, task, ts FROM promises WHERE branch=? AND done=0", (branch,)).fetchall():
        age = (now - parse_ts(p["ts"])).days
        if age >= 3:
            out.append(tr(lang, "risk_promise", person=p["person"], task=p["task"], days=age))
    last_scan = c.execute("SELECT MAX(ts) m FROM movements WHERE source='scanner' AND branch=?", (branch,)).fetchone()["m"]
    if last_scan and (now - parse_ts(last_scan)).total_seconds() > 24 * 3600:
        out.append(tr(lang, "risk_scan_silent", hours=int((now - parse_ts(last_scan)).total_seconds() // 3600)))
    waiting = c.execute("SELECT COUNT(*) n FROM movements WHERE synced=0").fetchone()["n"]
    last_sync = meta_get(c, "last_sync")
    if waiting and last_sync and (now - parse_ts(last_sync)).total_seconds() > 3 * 3600:
        out.append(tr(lang, "risk_sync", n=waiting))
    w1 = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected' AND ts>=?",
                   (branch, (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"))).fetchone()["s"]
    w0 = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected' AND ts>=? AND ts<?",
                   (branch, (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S"),
                    (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"))).fetchone()["s"]
    if w0 > 0 and w1 < 0.7 * w0:
        out.append(tr(lang, "risk_sales_drop", pct=round(100 * (1 - w1 / w0))))
    return out


def noted_risks(c, branch, limit=10):
    """Risks recorded from notes / scanner problems; the owner can mark them resolved."""
    return [{"id": r["id"], "text": r["text"], "source": r["source"]} for r in c.execute(
        "SELECT id, text, source FROM risks WHERE branch=? AND resolved=0 ORDER BY id DESC LIMIT ?", (branch, limit))]


def build_document(branch, lang="en"):
    """Everything the UI shows, as structured data, computed from SQLite (no AI involved)."""
    with db() as c:
        burns = gather_burns(c, branch)
        items = c.execute("SELECT * FROM items WHERE branch=? ORDER BY name", (branch,)).fetchall()
        fc, lead = forecast_rows(c, branch, burns)
        auto = detect_auto_risks(c, branch, lang, burns, lead)
        noted = noted_risks(c, branch)
        total_col = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected'", (branch,)).fetchone()["s"]
        today_col = c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_events WHERE branch=? AND type='collected' AND ts>=?",
                              (branch, date.today().strftime("%Y-%m-%d"))).fetchone()["s"]
        debts = c.execute("""SELECT entity, SUM(amount-settled) bal, MIN(ts) first FROM cash_events
                             WHERE branch=? AND type='owed' AND amount-settled>0.004 GROUP BY lower(entity) ORDER BY bal DESC""", (branch,)).fetchall()
        proms = c.execute("SELECT id, person, task, done FROM promises WHERE branch=? ORDER BY done, id DESC LIMIT 25", (branch,)).fetchall()
        last_sync = meta_get(c, "last_sync")
    inventory = []
    for it in items:
        b = burns[it["name"]]["burn"]
        inventory.append({
            "name": it["name"], "sku": it["sku"], "unit": it["unit"], "qty": it["qty"], "min_stock": it["min_stock"],
            "daily_burn": round(b, 2), "days_left": round(it["qty"] / b, 1) if b > 0 else None,
            "status": "out" if it["qty"] <= 0 else ("low" if it["qty"] <= it["min_stock"] else "ok"),
            "needs_review": bool(it["needs_review"]), "perishable": bool(it["shelf_life_days"])})
    risks = ([{"id": None, "kind": "auto", "text": t} for t in auto]
             + [{"id": r["id"], "kind": "noted", "text": r["text"]} for r in noted])
    return {
        "branch": branch, "lang": lang, "generated_at": now_str(), "currency": settings.currency,
        "inventory": inventory,
        "cash": {"total_collected": total_col, "collected_today": today_col,
                 "pending_total": sum(d["bal"] for d in debts),
                 "debts": [{"entity": d["entity"], "balance": d["bal"], "since": parse_ts(d["first"]).strftime("%Y-%m-%d")} for d in debts]},
        "promises": [{"id": p["id"], "person": p["person"], "task": p["task"], "done": bool(p["done"])} for p in proms],
        "forecast": sorted(fc, key=lambda r: r["must_order_by"])[:10], "lead_days": lead,
        "risks": risks, "last_sync": last_sync,
    }


def render_doc(branch, lang="en") -> str:
    """Markdown export of the same document (used by the download button and tests)."""
    d = build_document(branch, lang)
    L = lambda k, **kw: tr(lang, k, **kw)
    md = [f"# 📄 {L('title')}", f"*{md_esc(branch)} · {L('updated')}: {now_dt().strftime('%d %b %Y, %H:%M')}*", ""]
    md += [f"## {L('inventory')}", "",
           f"| {L('item')} | {L('qty')} | {L('unit')} | {L('min')} | {L('days_left')} | {L('status')} |", "|---|---:|---|---:|---:|---|"]
    for it in d["inventory"]:
        dl = f"{it['days_left']:.1f}" if it["days_left"] is not None else "-"
        md.append(f"| {md_esc(it['name'])} | {fmt_qty(it['qty'])} | {md_esc(it['unit'])} | {fmt_qty(it['min_stock'])} | {dl} | {L(it['status'])} |")
    cash = d["cash"]
    md += ["", f"## {L('cash')}", "", f"- **{L('total_collected')}:** {fmt_money(cash['total_collected'])}",
           f"- **{L('collected_today')}:** {fmt_money(cash['collected_today'])}",
           f"- **{L('pending')}:** {fmt_money(cash['pending_total'])}"]
    if cash["debts"]:
        for x in cash["debts"]:
            md.append(f"  - {md_esc(x['entity'])}: {fmt_money(x['balance'])} ({L('since')} {parse_ts(x['since']).strftime('%d %b')})")
    else:
        md.append(f"  - {L('no_pending')}")
    md += ["", f"## {L('promises')}", ""]
    md += [f"- [{'x' if p['done'] else ' '}] **{md_esc(p['person'])}**: {md_esc(p['task'])}" for p in d["promises"]] or [f"*{L('no_promises')}*"]
    md += ["", f"## {L('forecast')}", ""]
    if d["forecast"]:
        md += [f"| {L('item')} | {L('festival')} | {L('order_by')} | {L('order_qty')} | {L('urgency')} |", "|---|---|---|---:|---|"]
        for r in d["forecast"]:
            q = r["recommended_order_qty"]
            md.append(f"| {md_esc(r['item'])} | {md_esc(r['festival_name'] or L('regular'))} | {r['must_order_by']} | "
                      f"{'-' if q is None else fmt_qty(q)} | {L(r['urgency'])} |")
    else:
        md.append(f"*{L('no_forecast')}*")
    md += ["", f"## {L('risks')}", ""]
    md += [f"- ⚠️ {md_esc(r['text'] if r['kind'] == 'auto' else L('risk_noted', text=r['text']))}" for r in d["risks"]] or [f"*{L('no_risks')}*"]
    return "\n".join(md)
