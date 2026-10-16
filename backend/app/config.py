"""Runtime configuration (environment variables) and time helpers."""
import os
from dataclasses import dataclass, field
from datetime import datetime


def _env(name, default):
    return os.environ.get(name, default)


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: _env("LIVINGDOC_DB", "livingdoc.db"))
    hub_path: str = field(default_factory=lambda: _env("LIVINGDOC_HUB", "livingdoc_hub.db"))  # shared by all branches
    scanner_inbox: str = field(default_factory=lambda: _env("LIVINGDOC_SCANNER_INBOX", "scanner_inbox"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "ollama"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "llama3.1"))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "45")))
    sync_interval_seconds: int = field(default_factory=lambda: int(_env("LIVINGDOC_SYNC_SECONDS", "3600")))
    scanner_poll_seconds: int = field(default_factory=lambda: int(_env("LIVINGDOC_SCANNER_POLL_SECONDS", "10")))
    supplier_lead_days: int = field(default_factory=lambda: int(_env("LIVINGDOC_LEAD_DAYS", "3")))
    cors_origins: str = field(default_factory=lambda: _env("LIVINGDOC_CORS_ORIGINS", "*"))
    background_workers: bool = field(default_factory=lambda: _env("LIVINGDOC_WORKERS", "1") == "1")
    default_branch: str = "Main Store"
    currency: str = "\u20b9"


settings = Settings()


def now_dt() -> datetime:
    return datetime.now().replace(microsecond=0)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(s: str) -> datetime:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
