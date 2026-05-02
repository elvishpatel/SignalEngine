from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from tests.conftest import fresh_runtime_dir
from signal_engine.db.schema import init_db
from signal_engine.producers.bhavcopy import parse_bhavcopy_csv, store_prices
from signal_engine.producers.bulk_deals import parse_bulk_deals_csv


def _seed_prices(conn):
    rows = []
    start = date(2024, 1, 1)
    for idx in range(20):
        current = start + timedelta(days=idx)
        rows.append(
            {
                "symbol": "SBIN",
                "date": current.isoformat(),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100000,
                "source": "seed",
                "quality_score": 1.0,
            }
        )
    store_prices(pd.DataFrame(rows), conn)


def test_bhavcopy_parser_with_mock_csv():
    csv = "SYMBOL,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TOTTRDVAL\nSBIN,100,110,95,108,250000,1000000\n"
    frame = parse_bhavcopy_csv(csv, date(2024, 1, 15))
    assert len(frame.index) == 1
    row = frame.iloc[0]
    assert row["symbol"] == "SBIN"
    assert row["date"] == "2024-01-15"
    assert float(row["close"]) == 108.0
    assert int(row["volume"]) == 250000


def test_bulk_deal_event_schema_output():
    conn = init_db(fresh_runtime_dir("producers") / "events.db")
    _seed_prices(conn)
    csv = "Date,Symbol,SecurityName,ClientName,BuyOrSell,Quantity,Price\n15-Jan-2024,SBIN,State Bank of India,ABC Capital,BUY,200000,700\n"
    events = parse_bulk_deals_csv(csv, conn, trade_date=date(2024, 1, 15))
    assert len(events) == 1
    event = events[0]
    assert set(event.keys()) == {
        "event_id",
        "symbol",
        "event_type",
        "timestamp",
        "raw_signal_strength",
        "source",
        "quality_score",
        "metadata",
    }
    assert event["symbol"] == "SBIN"
    assert event["event_type"] == "BULK_DEAL"
    assert event["source"] == "nse_bulk_deals"
    assert event["metadata"]["client"] == "ABC Capital"
