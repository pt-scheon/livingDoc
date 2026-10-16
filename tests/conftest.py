import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import livingdoc_app as app  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """Fresh seeded database, hub and scanner inbox per test; LLM forced offline so the rule parser is used."""
    monkeypatch.setattr(app, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(app, "HUB_PATH", str(tmp_path / "hub.db"))
    monkeypatch.setattr(app, "SCANNER_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setattr(app, "_LLM_DOWN_UNTIL", time.time() + 3600)
    app.init_db()
    return app
