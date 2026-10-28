"""Local-only watchlist; no cloud accounts or credentials."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from engine import normalize_symbol

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "watchlist.sqlite3"


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.execute("""CREATE TABLE IF NOT EXISTS watchlist (
        symbol TEXT PRIMARY KEY, added_at TEXT NOT NULL, thesis TEXT NOT NULL DEFAULT '',
        target_price REAL)""")
    db.commit()
    return db


def save(symbol: str, thesis: str = "", target_price: float | None = None) -> None:
    sym = normalize_symbol(symbol)
    with connect() as db:
        db.execute("""INSERT INTO watchlist (symbol,added_at,thesis,target_price)
                      VALUES (?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
                      thesis=excluded.thesis, target_price=excluded.target_price""",
                   (sym, datetime.now(timezone.utc).date().isoformat(), thesis[:600], target_price))


def remove(symbol: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM watchlist WHERE symbol=?", (normalize_symbol(symbol),))


def all_items() -> pd.DataFrame:
    with connect() as db:
        return pd.read_sql_query("SELECT symbol,added_at,thesis,target_price FROM watchlist ORDER BY symbol", db)
