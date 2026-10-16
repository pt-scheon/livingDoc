"""SQLite persistence: profile, actuals, owner factors, festivals, forecast log, trend cache."""
from __future__ import annotations

import json
import os
import sqlite3
import datetime as dt
from contextlib import contextmanager

import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS actuals(
    date TEXT PRIMARY KEY, orders REAL, revenue REAL, note TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS owner_factors(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, start TEXT, end TEXT,
    effect_pct REAL, confidence REAL, scope TEXT, note TEXT, created_on TEXT,
    posterior_pct REAL, n_obs INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS festivals(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, start TEXT, end TEXT,
    lift REAL, lead INTEGER, tail INTEGER, kind TEXT, aff TEXT);
CREATE TABLE IF NOT EXISTS competitor_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, rival TEXT, start TEXT, end TEXT,
    discount_pct REAL, note TEXT);
CREATE TABLE IF NOT EXISTS forecast_log(
    issued_on TEXT, date TEXT, mu REAL, sigma REAL, point REAL, lo80 REAL, hi80 REAL,
    kind TEXT, rec_json TEXT, PRIMARY KEY(issued_on, date));
CREATE TABLE IF NOT EXISTS trend_cache(day TEXT PRIMARY KEY, payload TEXT);
"""


def default_path() -> str:
    return os.environ.get("FORESIGHT_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "foresight.db"))


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._mem = sqlite3.connect(":memory:") if self.path == ":memory:" else None
        with self.conn() as c:
            c.executescript(SCHEMA)
        self._seed_festivals()

    # -- plumbing --------------------------------------------------------
    @contextmanager
    def conn(self):
        c = self._mem or sqlite3.connect(self.path, timeout=30)
        try:
            if self._mem is None:
                c.execute("PRAGMA journal_mode=WAL")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            if self._mem is None:
                c.close()

    def _q(self, sql, params=()):
        with self.conn() as c:
            return pd.read_sql_query(sql, c, params=params)

    def _x(self, sql, params=()):
        with self.conn() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    # -- key/value (profile, model state, ...) -----------------------------
    def get_kv(self, key, default=None):
        with self.conn() as c:
            row = c.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_kv(self, key, value):
        self._x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (key, json.dumps(value)))

    def get_profile(self) -> dict:
        prof = self.get_kv("profile")
        if prof is None:
            prof = config.default_profile("sweets")
            self.set_kv("profile", prof)
        return prof

    def set_profile(self, prof: dict):
        self.set_kv("profile", prof)

    # -- actuals -----------------------------------------------------------
    def upsert_actual(self, date, orders, revenue=None, note="", source="owner"):
        self._x("INSERT OR REPLACE INTO actuals VALUES(?,?,?,?,?)",
                (str(date), float(orders), None if revenue is None else float(revenue), note, source))

    def actuals(self) -> pd.DataFrame:
        df = self._q("SELECT * FROM actuals ORDER BY date")
        if len(df):
            df["date"] = pd.to_datetime(df["date"])
        return df

    def delete_actual(self, date):
        self._x("DELETE FROM actuals WHERE date=?", (str(date),))

    # -- owner factors -----------------------------------------------------
    def add_factor(self, name, start, end, effect_pct, confidence=0.6, scope="all", note=""):
        return self._x(
            "INSERT INTO owner_factors(name,start,end,effect_pct,confidence,scope,note,created_on,posterior_pct,n_obs,active) "
            "VALUES(?,?,?,?,?,?,?,?,NULL,0,1)",
            (name, str(start), str(end), float(effect_pct), float(confidence), scope, note, dt.date.today().isoformat()))

    def factors(self, active_only=False) -> pd.DataFrame:
        df = self._q("SELECT * FROM owner_factors" + (" WHERE active=1" if active_only else "") + " ORDER BY start")
        if len(df):
            df["start"] = pd.to_datetime(df["start"])
            df["end"] = pd.to_datetime(df["end"])
        return df

    def update_factor(self, fid, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE owner_factors SET {cols} WHERE id=?", (*[
            (str(v) if k in ("start", "end") else v) for k, v in fields.items()], int(fid)))

    def delete_factor(self, fid):
        self._x("DELETE FROM owner_factors WHERE id=?", (int(fid),))

    # -- festivals -----------------------------------------------------------
    def _seed_festivals(self):
        with self.conn() as c:
            n = c.execute("SELECT COUNT(*) FROM festivals").fetchone()[0]
        if n == 0:
            self.replace_festivals(config.FESTIVALS_DEFAULT)

    def festivals(self) -> list[dict]:
        df = self._q("SELECT * FROM festivals ORDER BY start")
        rows = []
        for r in df.to_dict("records"):
            r["aff"] = json.loads(r["aff"]) if r.get("aff") else {}
            rows.append(r)
        return rows

    def replace_festivals(self, rows: list[dict]):
        with self.conn() as c:
            c.execute("DELETE FROM festivals")
            for r in rows:
                aff = r.get("aff", {})
                aff = aff if isinstance(aff, str) else json.dumps(aff)
                c.execute("INSERT INTO festivals(name,start,end,lift,lead,tail,kind,aff) VALUES(?,?,?,?,?,?,?,?)",
                          (r["name"], str(r["start"]), str(r["end"]), float(r["lift"]), int(r.get("lead", 3)),
                           int(r.get("tail", 1)), r.get("kind", "festival"), aff))

    # -- competitor events -----------------------------------------------------
    def add_competitor_event(self, rival, start, end, discount_pct, note=""):
        return self._x("INSERT INTO competitor_events(rival,start,end,discount_pct,note) VALUES(?,?,?,?,?)",
                       (rival, str(start), str(end), float(discount_pct), note))

    def competitor_events(self) -> pd.DataFrame:
        df = self._q("SELECT * FROM competitor_events ORDER BY start")
        if len(df):
            df["start"] = pd.to_datetime(df["start"])
            df["end"] = pd.to_datetime(df["end"])
        return df

    def delete_competitor_event(self, eid):
        self._x("DELETE FROM competitor_events WHERE id=?", (int(eid),))

    # -- forecast log (what we *said* before we knew) -----------------------------
    def log_forecasts(self, issued_on, rows: list[dict], kind="forecast"):
        with self.conn() as c:
            for r in rows:
                c.execute("INSERT OR REPLACE INTO forecast_log VALUES(?,?,?,?,?,?,?,?,?)",
                          (str(issued_on), str(r["date"])[:10], r["mu"], r["sigma"], r["point"], r["lo80"], r["hi80"],
                           kind, json.dumps(r.get("rec", {}))))

    def forecast_log(self) -> pd.DataFrame:
        df = self._q("SELECT * FROM forecast_log ORDER BY date, issued_on")
        if len(df):
            df["date"] = pd.to_datetime(df["date"])
            df["issued_on"] = pd.to_datetime(df["issued_on"])
        return df

    # -- trend cache ---------------------------------------------------------------
    def get_trends(self, day):
        with self.conn() as c:
            row = c.execute("SELECT payload FROM trend_cache WHERE day=?", (str(day),)).fetchone()
        return json.loads(row[0]) if row else None

    def latest_trends(self):
        with self.conn() as c:
            row = c.execute("SELECT day, payload FROM trend_cache ORDER BY day DESC LIMIT 1").fetchone()
        return (row[0], json.loads(row[1])) if row else (None, None)

    def set_trends(self, day, payload):
        self._x("INSERT OR REPLACE INTO trend_cache VALUES(?,?)", (str(day), json.dumps(payload)))
