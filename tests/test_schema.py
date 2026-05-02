from __future__ import annotations

from tests.conftest import fresh_runtime_dir
from signal_engine.db.schema import init_db


def test_init_db_creates_all_tables():
    db_path = fresh_runtime_dir("schema") / "schema.db"
    conn = init_db(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected_tables = {"prices", "events", "signals", "alerts", "sector_membership", "backtest_results"}
    assert expected_tables.issubset(tables)
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_prices_symbol_date", "idx_events_symbol", "idx_signals_status"}.issubset(indexes)
