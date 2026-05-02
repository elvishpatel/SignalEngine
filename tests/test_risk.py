from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import fresh_runtime_dir
from signal_engine.db.schema import init_db
from signal_engine.risk.filter import RiskFilter


def _seed_env(conn, symbol_volumes, symbol_closes, market_closes):
    conn.execute("DELETE FROM prices")
    conn.execute("DELETE FROM sector_membership")
    conn.execute("INSERT INTO sector_membership(symbol, sector, index_name) VALUES ('MARKET', 'NIFTY500', 'NIFTY 500')")
    start = date(2024, 1, 1)
    for idx, volume in enumerate(symbol_volumes):
        current = start + timedelta(days=idx)
        conn.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume, source, quality_score) VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', 1.0)",
            ("SBIN", current.isoformat(), symbol_closes[idx], symbol_closes[idx], symbol_closes[idx], symbol_closes[idx], volume),
        )
        conn.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume, source, quality_score) VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', 1.0)",
            ("MARKET", current.isoformat(), market_closes[idx], market_closes[idx], market_closes[idx], market_closes[idx], 1000000),
        )
    conn.commit()


def _base_signal(confidence=5.0, expires_at="2099-01-01T16:00:00"):
    return {
        "signal_id": "sig",
        "symbol": "SBIN",
        "confidence": confidence,
        "drivers": ["VOLUME_SPIKE"],
        "generated_at": "2024-01-20T16:00:00",
        "expires_at": expires_at,
    }


def test_rejects_illiquid_signal():
    conn = init_db(fresh_runtime_dir("risk1") / "risk1.db")
    _seed_env(conn, [50000] * 20, [100 + i for i in range(20)], [100 + i for i in range(20)])
    assert RiskFilter().passes(_base_signal(), conn) is False


def test_rejects_high_volatility_signal():
    conn = init_db(fresh_runtime_dir("risk2") / "risk2.db")
    closes = [100 if i % 2 == 0 else 120 for i in range(20)]
    _seed_env(conn, [200000] * 20, closes, [100 + i for i in range(20)])
    assert RiskFilter().passes(_base_signal(), conn) is False


def test_rejects_bearish_market_regime():
    conn = init_db(fresh_runtime_dir("risk3") / "risk3.db")
    market = [120 - i * 2 for i in range(20)]
    _seed_env(conn, [200000] * 20, [100 + i for i in range(20)], market)
    assert RiskFilter().passes(_base_signal(), conn) is False


def test_rejects_low_confidence_signal():
    conn = init_db(fresh_runtime_dir("risk4") / "risk4.db")
    _seed_env(conn, [200000] * 20, [100 + i for i in range(20)], [100 + i for i in range(20)])
    assert RiskFilter().passes(_base_signal(confidence=2.5), conn) is False


def test_rejects_expired_signal():
    conn = init_db(fresh_runtime_dir("risk5") / "risk5.db")
    _seed_env(conn, [200000] * 20, [100 + i for i in range(20)], [100 + i for i in range(20)])
    assert RiskFilter().passes(_base_signal(expires_at="2000-01-01T16:00:00"), conn) is False
