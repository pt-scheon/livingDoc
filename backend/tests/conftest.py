import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services import extraction, seed  # noqa: E402


@pytest.fixture(autouse=True)
def foresight_offline(monkeypatch):
    """Tests never touch the network: live weather and the web search are off, so every run is deterministic."""
    from foresight import trends, weather
    monkeypatch.setenv("LIVINGDOC_FORESIGHT_LIVE", "0")
    monkeypatch.setattr(weather, "_fetch_live", lambda *a, **k: None)
    monkeypatch.setattr(trends, "_search", lambda *a, **k: [])
    weather._CACHE.clear()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Fresh seeded database, hub and scanner inbox per test. LLM forced offline (rule parser) unless a test turns it on."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "hub_path", str(tmp_path / "hub.db"))
    monkeypatch.setattr(settings, "scanner_inbox", str(tmp_path / "inbox"))
    monkeypatch.setattr(settings, "background_workers", False)
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(extraction, "_LLM_DOWN_UNTIL", time.time() + 3600)
    monkeypatch.setitem(extraction._STATUS_CACHE, "value", None)
    seed.init_db()
    return tmp_path


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(serve_frontend=False)) as c:
        yield c
