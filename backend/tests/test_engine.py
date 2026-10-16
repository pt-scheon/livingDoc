import pytest

from app import engine as fe


def test_self_test_passes():
    fe._run_self_test()


def test_blackout_moves_deadline_by_exactly_the_blackout():
    d = {"name": "Diwali", "date": "2026-11-01", "surge_multiplier": 2.8, "supplier_blackout_days": 4}
    r4 = fe.predict_inventory({"A": 80}, {"A": 4.0}, [d], 3, "2026-10-16")[0]
    r0 = fe.predict_inventory({"A": 80}, {"A": 4.0}, [dict(d, supplier_blackout_days=0)], 3, "2026-10-16")[0]
    assert (fe._to_date(r0["must_order_by"]) - fe._to_date(r4["must_order_by"])).days == 4


def test_invalid_inputs_rejected():
    bad = {"name": "X", "date": "2026-11-01", "surge_multiplier": 0, "supplier_blackout_days": 1}
    with pytest.raises(ValueError):
        fe.predict_inventory({"A": 1}, {"A": 1}, [bad], 3, "2026-10-16")
    with pytest.raises(ValueError):
        fe.predict_inventory({"A": 1}, {"A": 1}, [], -1, "2026-10-16")
