"""SQLite schema and connection helpers (single source of truth for all state)."""
import sqlite3
from contextlib import contextmanager

from .config import settings, now_str


# --------------------------------------------------------------- database ---
SCHEMA = """
CREATE TABLE IF NOT EXISTS branches(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS items(
    branch TEXT NOT NULL, name TEXT NOT NULL, sku TEXT, unit TEXT NOT NULL DEFAULT 'pcs',
    qty REAL NOT NULL DEFAULT 0, min_stock REAL NOT NULL DEFAULT 0,
    baseline_burn REAL NOT NULL DEFAULT 0, shelf_life_days INTEGER,
    needs_review INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(branch, name));
CREATE TABLE IF NOT EXISTS movements(
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, branch TEXT NOT NULL, item TEXT NOT NULL,
    change REAL NOT NULL, source TEXT NOT NULL, note TEXT, synced INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_mov_item ON movements(branch, item, ts);
CREATE INDEX IF NOT EXISTS idx_mov_sync ON movements(synced);
CREATE TABLE IF NOT EXISTS cash_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('collected','owed')), entity TEXT NOT NULL,
    amount REAL NOT NULL, settled REAL NOT NULL DEFAULT 0, descr TEXT);
CREATE INDEX IF NOT EXISTS idx_cash_branch ON cash_events(branch, type, ts);
CREATE TABLE IF NOT EXISTS promises(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    person TEXT NOT NULL, task TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, done_ts TEXT);
CREATE TABLE IF NOT EXISTS risks(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    text TEXT NOT NULL, source TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, branch TEXT NOT NULL,
    raw TEXT NOT NULL, digest TEXT NOT NULL, extractor TEXT, deltas_json TEXT);
CREATE TABLE IF NOT EXISTS festivals(
    name TEXT NOT NULL, date TEXT NOT NULL, surge_multiplier REAL NOT NULL,
    supplier_blackout_days INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(name, date));
CREATE TABLE IF NOT EXISTS trust_entries(
    id INTEGER PRIMARY KEY AUTOINCREMENT, branch TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('owed_to_us','we_owe','favour_given','favour_owed','word')),
    counterparty TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'other', description TEXT NOT NULL DEFAULT '',
    amount REAL, settled REAL NOT NULL DEFAULT 0, cp_amount REAL, cp_note TEXT NOT NULL DEFAULT '',
    created_on TEXT NOT NULL, due_on TEXT, resolved_on TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','kept','broken','forgiven')),
    disputed INTEGER NOT NULL DEFAULT 0,
    proof_owner INTEGER NOT NULL DEFAULT 0, proof_cp INTEGER,
    source_ref TEXT UNIQUE, salt TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_trust_branch ON trust_entries(branch, status);
CREATE TABLE IF NOT EXISTS trust_parties(
    token TEXT PRIMARY KEY, branch TEXT NOT NULL, name_key TEXT NOT NULL, name TEXT NOT NULL, created_on TEXT NOT NULL,
    UNIQUE(branch, name_key));
CREATE TABLE IF NOT EXISTS trust_proofs(
    id TEXT PRIMARY KEY, branch TEXT NOT NULL, created_on TEXT NOT NULL, packet TEXT NOT NULL,
    open_key_hash TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, leaves TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS presence_profiles(
    branch TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '', tagline TEXT NOT NULL DEFAULT '',
    about TEXT NOT NULL DEFAULT '', area TEXT NOT NULL DEFAULT '', hours TEXT NOT NULL DEFAULT '', languages TEXT NOT NULL DEFAULT 'en,hi,gu',
    show_products INTEGER NOT NULL DEFAULT 0, product_names TEXT NOT NULL DEFAULT '[]', show_trust INTEGER NOT NULL DEFAULT 0,
    proof_id TEXT, published INTEGER NOT NULL DEFAULT 0, autonomy TEXT NOT NULL DEFAULT 'suggest' CHECK(autonomy IN ('off','suggest')),
    budget_cap REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS presence_drafts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, branch TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('about','offer','trust_line')),
    lang TEXT NOT NULL, text TEXT NOT NULL, why TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','published','rejected')),
    created_on TEXT NOT NULL, published_on TEXT, spend REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS presence_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, branch TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

HUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS hub_movements(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, ts TEXT NOT NULL,
    branch TEXT NOT NULL, item TEXT NOT NULL, change REAL NOT NULL, source TEXT, note TEXT);
"""


@contextmanager
def db(path=None):
    conn = sqlite3.connect(path or settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def meta_get(c, key, default=None):
    r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def meta_set(c, key, value):
    c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, str(value)))


def ensure_branch(c, branch):
    c.execute("INSERT OR IGNORE INTO branches(name) VALUES(?)", (branch,))


def add_risk(c, branch, text, source="auto"):
    """Store a risk once (an identical unresolved risk is not duplicated)."""
    text = text.strip()
    if not text:
        return
    if c.execute("SELECT 1 FROM risks WHERE branch=? AND text=? AND resolved=0", (branch, text)).fetchone():
        return
    c.execute("INSERT INTO risks(ts,branch,text,source) VALUES(?,?,?,?)", (now_str(), branch, text, source))
