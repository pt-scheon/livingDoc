import json
from pathlib import Path

from app.config import settings
from app.database import db
from app.services import extraction, ledger, scanner, sync
from app.services.document import build_document, forecast_rows, gather_burns, render_doc
from app.services.extraction import process_note, sanitize_deltas, parse_json_loose
from app.services.inventory import audit_stock

B = "Main Store"


def qty(item, branch=B):
    with db() as c:
        return c.execute("SELECT qty FROM items WHERE branch=? AND name=?", (branch, item)).fetchone()["qty"]


def test_seed_is_consistent(env):
    with db() as c:
        assert audit_stock(c) == []
        assert c.execute("SELECT COUNT(*) n FROM items").fetchone()["n"] >= 8
    doc = render_doc(B, "en")
    for h in ("Current Inventory", "Cash & Invoices", "Handshakes & Promises", "Quiet Breakage Warnings"):
        assert h in doc
    assert "LOW STOCK" in doc  # Sugar is seeded below its minimum


def test_structured_document_shape(env):
    d = build_document(B, "en")
    assert {"inventory", "cash", "promises", "forecast", "risks"} <= set(d)
    assert all(r["status"] in ("ok", "low", "out") for r in d["inventory"])
    assert d["cash"]["pending_total"] == sum(x["balance"] for x in d["cash"]["debts"])
    assert any(r["kind"] == "noted" and r["id"] for r in d["risks"])


def test_messy_note_example(env):
    coffee0, milk0 = qty("Coffee Beans"), qty("Milk")
    res = process_note("Sold 4 milks, used 2 coffee beans, Dave paid $500 cash, reminded me to order beans", B)
    assert res["ok"]
    assert qty("Milk") == milk0 - 4 and qty("Coffee Beans") == coffee0 - 2
    with db() as c:
        dave = c.execute("SELECT SUM(amount-settled) s FROM cash_events WHERE type='owed' AND entity='Dave'").fetchone()["s"]
        assert dave == 700  # 1200 owed - 500 paid, settled FIFO
        assert c.execute("SELECT COUNT(*) n FROM promises WHERE task LIKE 'order beans%' AND done=0").fetchone()["n"] == 1
        assert audit_stock(c) == []


def test_duplicate_note_not_applied_twice(env):
    process_note("Sold 1 milk", B)
    after = qty("Milk")
    assert process_note("Sold 1 milk", B)["error"] == "duplicate"
    assert qty("Milk") == after


def test_stock_never_negative_and_flagged(env):
    process_note("Sold 500 coffee beans", B)
    assert qty("Coffee Beans") == 0
    with db() as c:
        assert audit_stock(c) == []
        assert c.execute("SELECT COUNT(*) n FROM risks WHERE text LIKE '%Coffee Beans%'").fetchone()["n"] == 1
    assert "out of stock" in render_doc(B, "en")


def test_llm_output_is_sanitised():
    d = sanitize_deltas({"inventory_deltas": [{"item": "Milk", "change": "-2"}, {"item": "", "change": 1}, "junk", {"item": "X", "change": "abc"}],
                         "cash_events": [{"type": "PAID", "entity": "Ann", "amount": "$1,200.50"}, {"type": "weird", "amount": 5}],
                         "promises": [{"person": "Bob", "task": "call", "completed": "yes"}, {"task": ""}],
                         "quiet_risk": 42})
    assert d["inventory_deltas"] == [{"item": "Milk", "change": -2.0}]
    assert d["cash_events"][0]["type"] == "collected" and d["cash_events"][0]["amount"] == 1200.5
    assert d["promises"] == [{"person": "Bob", "task": "call", "completed": True}]
    assert d["quiet_risk"] == ""
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_llm_path_is_used_and_garbage_falls_back(env, monkeypatch):
    monkeypatch.setattr(extraction, "_LLM_DOWN_UNTIL", 0.0)
    good = json.dumps({"inventory_deltas": [{"item": "Sugar", "change": -3}], "cash_events": [], "promises": [], "quiet_risk": ""})
    monkeypatch.setattr(extraction, "_http_chat", lambda m: good)
    s0 = qty("Sugar")
    res = process_note("teen kilo chini bechi", B)  # Hinglish: only an LLM could read this
    assert res["extractor"] == "llm" and qty("Sugar") == s0 - 3
    monkeypatch.setattr(extraction, "_http_chat", lambda m: "I am not JSON at all")
    res = process_note("Sold 1 milk please", B)
    assert res["ok"] and res["extractor"].startswith("rules")


def test_promise_completion_matches_open_one(env):
    process_note("Remind me to order beans", B)
    with db() as c:
        ledger.add_promise(c, B, "Me", "order beans", completed=True)
        assert c.execute("SELECT COUNT(*) n FROM promises WHERE task LIKE 'order beans%'").fetchone()["n"] == 1
        assert c.execute("SELECT done FROM promises WHERE task LIKE 'order beans%'").fetchone()["done"] == 1


def write_scan(name, payload, suffix=".json"):
    p = Path(settings.scanner_inbox)
    p.mkdir(parents=True, exist_ok=True)
    (p / (name + suffix)).write_text(payload if isinstance(payload, str) else json.dumps(payload))


def test_scanner_in_out_duplicates_and_sku_learning(env):
    g0 = qty("Ghee")
    write_scan("a", [{"event_id": "e1", "sku": "ITM-GHEE", "qty": 3, "direction": "out"},
                     {"event_id": "e1", "sku": "ITM-GHEE", "qty": 3, "direction": "out"},
                     {"event_id": "e2", "sku": "ITM-GHEE", "qty": 10, "direction": "in"}])
    s = scanner.process_scanner_inbox(B, min_age=0)
    assert s["applied"] == 2 and s["duplicate"] == 1
    assert qty("Ghee") == g0 + 7
    write_scan("b", {"sku": "NEW-123", "item": "Sugar", "qty": 1, "direction": "out"})
    scanner.process_scanner_inbox(B, min_age=0)
    with db() as c:
        assert c.execute("SELECT sku FROM items WHERE name='Sugar' AND branch=?", (B,)).fetchone()["sku"] == "ITM-SUGAR"
    assert list(Path(settings.scanner_inbox).glob("*.json")) == []


def test_scanner_problems_are_handled(env):
    write_scan("bad", "{not json")
    write_scan("mixed", [{"sku": "Z-9", "qty": 2, "direction": "in"},
                         {"sku": "ITM-MILK", "qty": 0, "direction": "out"},
                         {"sku": "ITM-MILK", "qty": 1, "direction": "sideways"}])
    s = scanner.process_scanner_inbox(B, min_age=0)
    assert s["failed_files"] == 1 and s["skipped"] == 2 and s["applied"] == 1
    assert (Path(settings.scanner_inbox) / "failed").exists()
    with db() as c:
        assert c.execute("SELECT needs_review FROM items WHERE name='Unknown SKU Z-9'").fetchone()["needs_review"] == 1
        assert audit_stock(c) == []
    assert "added automatically" in render_doc(B, "en")


def test_csv_scan_and_oversell_clamps(env):
    write_scan("c", "sku,qty,direction,event_id\nITM-CUPS,100000,out,x1\n", ".csv")
    scanner.process_scanner_inbox(B, min_age=0)
    assert qty("Paper Cups") == 0
    with db() as c:
        assert audit_stock(c) == []


def test_branch_sync_converges(env, monkeypatch):
    g_branch2 = qty("Ghee", "Navrangpura Branch")
    scanner.ingest_events([{"event_id": "s1", "item": "Ghee", "qty": 2, "direction": "out", "branch": "Navrangpura Branch"}], B)
    assert sync.sync_with_hub()["pushed"] >= 1
    monkeypatch.setattr(settings, "db_path", str(env / "store2.db"))
    from app.services import seed
    seed.init_db()
    assert sync.sync_with_hub()["pulled"] >= 1
    assert qty("Ghee", "Navrangpura Branch") == g_branch2 - 2
    assert sync.sync_with_hub() == {"pushed": 0, "pulled": 0}


def test_forecast_and_languages(env):
    with db() as c:
        rows, lead = forecast_rows(c, B, gather_burns(c, B))
    assert rows and all(r["urgency"] in ("CRITICAL", "HIGH", "MEDIUM") for r in rows)
    assert "बकाया रकम" in render_doc(B, "hi")
    assert "બાકી" in render_doc(B, "gu")


def test_markdown_injection_is_escaped(env):
    process_note("Remind me to call | evil <b>x</b>", B)
    assert "<b>" not in render_doc(B, "en")
