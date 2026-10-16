import json
import time
from pathlib import Path


def qty(app, item, branch="Main Store"):
    with app.db() as c:
        return c.execute("SELECT qty FROM items WHERE branch=? AND name=?", (branch, item)).fetchone()["qty"]


def test_seed_is_consistent(fresh):
    app = fresh
    with app.db() as c:
        assert app.audit_stock(c) == []
        assert c.execute("SELECT COUNT(*) n FROM items").fetchone()["n"] >= 8
    doc = app.render_doc("Main Store", "en")
    for h in ("Current Inventory", "Cash & Invoices", "Handshakes & Promises", "Quiet Breakage Warnings"):
        assert h in doc
    assert "LOW STOCK" in doc  # Sugar is seeded below its minimum


def test_messy_note_example(fresh):
    app = fresh
    coffee0, milk0 = qty(app, "Coffee Beans"), qty(app, "Milk")
    with app.db() as c:
        before = c.execute("SELECT COALESCE(SUM(amount-settled),0) s FROM cash_events WHERE type='owed'").fetchone()["s"]
    res = app.process_note("Sold 4 milks, used 2 coffee beans, Dave paid $500 cash, reminded me to order beans", "Main Store")
    assert res["ok"]
    assert qty(app, "Milk") == milk0 - 4 and qty(app, "Coffee Beans") == coffee0 - 2
    with app.db() as c:
        dave = c.execute("SELECT SUM(amount-settled) s FROM cash_events WHERE type='owed' AND entity='Dave'").fetchone()["s"]
        assert dave == 700  # 1200 owed - 500 paid settles FIFO
        assert c.execute("SELECT COUNT(*) n FROM promises WHERE task LIKE 'order beans%' AND done=0").fetchone()["n"] == 1
        assert app.audit_stock(c) == []


def test_duplicate_note_not_applied_twice(fresh):
    app = fresh
    app.process_note("Sold 1 milk", "Main Store")
    after = qty(app, "Milk")
    assert app.process_note("Sold 1 milk", "Main Store")["error"] == "duplicate"
    assert qty(app, "Milk") == after


def test_stock_never_negative_and_flagged(fresh):
    app = fresh
    app.process_note("Sold 500 coffee beans", "Main Store")
    assert qty(app, "Coffee Beans") == 0
    with app.db() as c:
        assert app.audit_stock(c) == []
        assert c.execute("SELECT COUNT(*) n FROM risks WHERE text LIKE '%Coffee Beans%'").fetchone()["n"] == 1
    assert "out of stock" in app.render_doc("Main Store", "en")


def test_llm_output_is_sanitised(fresh):
    app = fresh
    d = app.sanitize_deltas({"inventory_deltas": [{"item": "Milk", "change": "-2"}, {"item": "", "change": 1}, "junk",
                                                  {"item": "X", "change": "abc"}],
                             "cash_events": [{"type": "PAID", "entity": "Ann", "amount": "$1,200.50"},
                                             {"type": "weird", "amount": 5}],
                             "promises": [{"person": "Bob", "task": "call", "completed": "yes"}, {"task": ""}],
                             "quiet_risk": 42})
    assert d["inventory_deltas"] == [{"item": "Milk", "change": -2.0}]
    assert d["cash_events"][0]["type"] == "collected" and d["cash_events"][0]["amount"] == 1200.5
    assert d["promises"] == [{"person": "Bob", "task": "call", "completed": True}]
    assert d["quiet_risk"] == ""
    assert app.parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_promise_completion_matches_open_one(fresh):
    app = fresh
    app.process_note("Remind me to order beans", "Main Store")
    with app.db() as c:
        app.add_promise(c, "Main Store", "Me", "order beans", completed=True)
        assert c.execute("SELECT COUNT(*) n FROM promises WHERE task LIKE 'order beans%'").fetchone()["n"] == 1
        assert c.execute("SELECT done FROM promises WHERE task LIKE 'order beans%'").fetchone()["done"] == 1


def write_scan(app, name, payload, suffix=".json"):
    p = Path(app.SCANNER_INBOX)
    p.mkdir(parents=True, exist_ok=True)
    (p / (name + suffix)).write_text(payload if isinstance(payload, str) else json.dumps(payload))


def test_scanner_in_out_duplicates_and_sku_learning(fresh):
    app = fresh
    g0 = qty(app, "Ghee")
    write_scan(app, "a", [{"event_id": "e1", "sku": "ITM-GHEE", "qty": 3, "direction": "out"},
                          {"event_id": "e1", "sku": "ITM-GHEE", "qty": 3, "direction": "out"},   # duplicate
                          {"event_id": "e2", "sku": "ITM-GHEE", "qty": 10, "direction": "in"}])
    s = app.process_scanner_inbox("Main Store", min_age=0)
    assert s["applied"] == 2 and s["duplicate"] == 1
    assert qty(app, "Ghee") == g0 + 7
    # unknown barcode with a known name -> mapping is learned
    write_scan(app, "b", {"sku": "NEW-123", "item": "Sugar", "qty": 1, "direction": "out"})
    app.process_scanner_inbox("Main Store", min_age=0)
    with app.db() as c:
        assert c.execute("SELECT sku FROM items WHERE name='Sugar' AND branch='Main Store'").fetchone()["sku"] == "ITM-SUGAR"
    # files are moved out of the inbox
    assert list(Path(app.SCANNER_INBOX).glob("*.json")) == []


def test_scanner_problems_are_handled(fresh):
    app = fresh
    write_scan(app, "bad", "{not json")
    write_scan(app, "mixed", [{"sku": "Z-9", "qty": 2, "direction": "in"},      # unknown sku -> placeholder item
                              {"sku": "ITM-MILK", "qty": 0, "direction": "out"},  # invalid qty
                              {"sku": "ITM-MILK", "qty": 1, "direction": "sideways"}])
    s = app.process_scanner_inbox("Main Store", min_age=0)
    assert s["failed_files"] == 1 and s["skipped"] == 2 and s["applied"] == 1
    assert (Path(app.SCANNER_INBOX) / "failed").exists()
    with app.db() as c:
        assert c.execute("SELECT needs_review FROM items WHERE name='Unknown SKU Z-9'").fetchone()["needs_review"] == 1
        assert app.audit_stock(c) == []
    assert "added automatically" in app.render_doc("Main Store", "en")


def test_csv_scan_and_oversell_clamps(fresh):
    app = fresh
    write_scan(app, "c", "sku,qty,direction,event_id\nITM-CUPS,100000,out,x1\n", ".csv")
    app.process_scanner_inbox("Main Store", min_age=0)
    assert qty(app, "Paper Cups") == 0
    with app.db() as c:
        assert app.audit_stock(c) == []


def test_branch_sync_converges(fresh, tmp_path, monkeypatch):
    app = fresh
    g_branch2 = qty(app, "Ghee", "Navrangpura Branch")
    write_scan(app, "s", {"event_id": "s1", "item": "Ghee", "qty": 2, "direction": "out", "branch": "Navrangpura Branch"})
    app.process_scanner_inbox("Main Store", min_age=0)
    r1 = app.sync_with_hub()
    assert r1["pushed"] >= 1
    # a second store (separate database) pulls the movement through the shared hub
    monkeypatch.setattr(app, "DB_PATH", str(tmp_path / "store2.db"))
    app.init_db()
    r2 = app.sync_with_hub()
    assert r2["pulled"] >= 1
    assert qty(app, "Ghee", "Navrangpura Branch") == g_branch2 - 2
    r3 = app.sync_with_hub()
    assert r3 == {"pushed": 0, "pulled": 0}  # idempotent


def test_forecast_and_languages(fresh):
    app = fresh
    with app.db() as c:
        burns = app.gather_burns(c, "Main Store")
        rows, lead = app.forecast_rows(c, "Main Store", burns)
    assert rows and all(r["urgency"] in ("CRITICAL", "HIGH", "MEDIUM") for r in rows)
    assert "बकाया रकम" in app.render_doc("Main Store", "hi")
    assert "બાકી" in app.render_doc("Main Store", "gu")


def test_markdown_injection_is_escaped(fresh):
    app = fresh
    app.process_note("Remind me to call | evil <b>x</b>", "Main Store")
    doc = app.render_doc("Main Store", "en")
    assert "<b>" not in doc
