"""Local-only watchlist; no cloud accounts or credentials."""
from __future__ import annotations
import sqlite3
import math
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from engine import normalize_symbol

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "watchlist.sqlite3"


def _legacy_country(symbol: str) -> str:
    """Preserve legacy symbols, with the prior US default for bare tickers."""
    if symbol.endswith(".NGX"):
        return "Nigeria"
    from markets import MARKETS
    for country, market in MARKETS.items():
        if any(suffix and symbol.endswith(suffix) for suffix in market["suffixes"]):
            return country
    return "United States"


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    try:
        db.execute("BEGIN IMMEDIATE")
        columns = db.execute("PRAGMA table_info(watchlist)").fetchall()
        if columns and "country" not in {column[1] for column in columns}:
            rows = db.execute("SELECT symbol,added_at,thesis,target_price FROM watchlist").fetchall()
            db.execute("""CREATE TABLE watchlist_v3 (
                country TEXT NOT NULL, symbol TEXT NOT NULL, added_at TEXT NOT NULL,
                thesis TEXT NOT NULL DEFAULT '', target_price REAL,
                PRIMARY KEY(country,symbol))""")
            db.executemany("INSERT INTO watchlist_v3 VALUES (?,?,?,?,?)",
                           [(_legacy_country(row[0]), *row) for row in rows])
            db.execute("DROP TABLE watchlist")
            db.execute("ALTER TABLE watchlist_v3 RENAME TO watchlist")
        else:
            db.execute("""CREATE TABLE IF NOT EXISTS watchlist (
                country TEXT NOT NULL, symbol TEXT NOT NULL, added_at TEXT NOT NULL,
                thesis TEXT NOT NULL DEFAULT '', target_price REAL,
                PRIMARY KEY(country,symbol))""")
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise
    return db


def _country(country: str) -> str:
    from markets import MARKETS
    if country not in MARKETS:
        raise ValueError("Choose a supported listing country for this watchlist entry.")
    return country


def save(symbol: str, thesis: str = "", target_price: float | None = None,
         country: str = "United States") -> None:
    sym = normalize_symbol(symbol)
    country = _country(country)
    if target_price is not None and (not math.isfinite(float(target_price)) or float(target_price) <= 0):
        raise ValueError("Review price must be finite and positive, or left blank.")
    with closing(connect()) as db, db:
        db.execute("""INSERT INTO watchlist (country,symbol,added_at,thesis,target_price)
                      VALUES (?,?,?,?,?) ON CONFLICT(country,symbol) DO UPDATE SET
                      thesis=excluded.thesis, target_price=excluded.target_price""",
                   (country, sym, datetime.now(timezone.utc).date().isoformat(), thesis[:600], target_price))


def remove(symbol: str, country: str = "United States") -> None:
    with closing(connect()) as db, db:
        db.execute("DELETE FROM watchlist WHERE country=? AND symbol=?", (_country(country), normalize_symbol(symbol)))


def all_items() -> pd.DataFrame:
    with closing(connect()) as db, db:
        return pd.read_sql_query("SELECT country,symbol,added_at,thesis,target_price FROM watchlist ORDER BY country,symbol", db)
