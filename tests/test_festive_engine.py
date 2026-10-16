import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import festive_engine as fe  # noqa: E402


def test_self_test_passes():
    fe._run_self_test()


def test_blackout_moves_deadline():
    d = {"name": "Diwali", "date": "2026-11-01", "surge_multiplier": 2.8, "supplier_blackout_days": 4}
    r4 = fe.predict_inventory({"A": 80}, {"A": 4.0}, [d], 3, "2026-10-16")[0]
    r0 = fe.predict_inventory({"A": 80}, {"A": 4.0}, [dict(d, supplier_blackout_days=0)], 3, "2026-10-16")[0]
    assert (fe._to_date(r0["must_order_by"]) - fe._to_date(r4["must_order_by"])).days == 4


def test_invalid_inputs_rejected():
    import pytest
    bad = {"name": "X", "date": "2026-11-01", "surge_multiplier": 0, "supplier_blackout_days": 1}
    with pytest.raises(ValueError):
        fe.predict_inventory({"A": 1}, {"A": 1}, [bad], 3, "2026-10-16")


def test_engine_copy_inside_app_is_identical():
    """livingdoc_app.py embeds the engine so it stays single-file; guard against drift."""
    root = Path(__file__).resolve().parent.parent
    grab = lambda t: t.split("# ==== ENGINE START ====")[1].split("# ==== ENGINE END ====")[0].strip()
    assert grab((root / "festive_engine.py").read_text()) == grab((root / "livingdoc_app.py").read_text())
