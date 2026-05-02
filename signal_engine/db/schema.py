from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from signal_engine.utils import get_db_path

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        date DATE NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        volume INTEGER,
        source TEXT,
        quality_score REAL DEFAULT 1.0,
        UNIQUE(symbol, date)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT UNIQUE NOT NULL,
        symbol TEXT NOT NULL,
        event_type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        raw_signal_strength REAL,
        source TEXT,
        quality_score REAL,
        metadata TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE NOT NULL,
        symbol TEXT NOT NULL,
        confidence REAL NOT NULL,
        drivers TEXT,
        generated_at TEXT,
        expires_at TEXT,
        status TEXT DEFAULT 'ACTIVE'
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT,
        symbol TEXT,
        message TEXT,
        sent_at TEXT,
        channel TEXT DEFAULT 'telegram'
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_membership (
        symbol TEXT NOT NULL,
        sector TEXT NOT NULL,
        index_name TEXT,
        PRIMARY KEY(symbol, sector)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT,
        symbol TEXT,
        signal_date TEXT,
        return_3d REAL,
        return_5d REAL,
        return_10d REAL,
        hit_3d INTEGER,
        hit_5d INTEGER,
        hit_10d INTEGER,
        evaluated_at TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON prices(symbol, date);",
    "CREATE INDEX IF NOT EXISTS idx_events_symbol ON events(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);",
]


def init_db(db_path: str | Path) -> sqlite3.Connection:
    target = Path(db_path)
    if target.parent and str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    for statement in SCHEMA_STATEMENTS:
        cursor.execute(statement)
    conn.commit()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise the signal engine SQLite database.")
    parser.add_argument("--db-path", default=str(get_db_path()))
    args = parser.parse_args()
    init_db(args.db_path)
    print(Path(args.db_path).resolve())


if __name__ == "__main__":
    main()
