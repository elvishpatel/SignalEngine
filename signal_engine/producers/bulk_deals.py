from __future__ import annotations

import argparse
import io
import logging
from datetime import date
from typing import Any

import pandas as pd
import requests

from signal_engine.db.schema import init_db
from signal_engine.utils import HTTP_HEADERS, get_db_path, load_settings, make_event, parse_date

LOGGER = logging.getLogger(__name__)
BULK_DEALS_URL = "https://archives.nseindia.com/content/equities/bulk.csv"


def download_bulk_deals(session: requests.Session | None = None) -> str | None:
    active_session = session or requests.Session()
    response = active_session.get(BULK_DEALS_URL, headers=HTTP_HEADERS, timeout=30)
    if response.status_code == 404:
        LOGGER.info("Bulk deals file unavailable.")
        return None
    response.raise_for_status()
    return response.text


def _average_volume(db_conn: Any, symbol: str, trade_date: date) -> float:
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT AVG(volume) AS avg_volume
        FROM (
            SELECT volume
            FROM prices
            WHERE symbol = ? AND date <= ?
            ORDER BY date DESC
            LIMIT 20
        )
        """,
        (symbol, trade_date.isoformat()),
    )
    row = cursor.fetchone()
    if row and row[0] is not None:
        return float(row[0])
    return 0.0


def parse_bulk_deals_csv(
    content: str,
    db_conn: Any,
    settings: dict[str, Any] | None = None,
    trade_date: date | str | None = None,
) -> list[dict[str, Any]]:
    if not content or not content.strip():
        return []
    frame = pd.read_csv(io.StringIO(content))
    if frame.empty:
        return []
    frame.columns = [str(column).strip() for column in frame.columns]
    target_date = parse_date(trade_date) if trade_date else None
    events: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        row_date = parse_date(row.get("Date") or row.get("DATE"))
        if target_date and row_date != target_date:
            continue
        symbol = str(row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
        if not symbol:
            continue
        quantity = pd.to_numeric(row.get("Quantity") or row.get("QUANTITY"), errors="coerce")
        price = pd.to_numeric(row.get("Price") or row.get("PRICE"), errors="coerce")
        if pd.isna(quantity) or quantity <= 0:
            continue
        avg_volume = _average_volume(db_conn, symbol, row_date)
        raw_strength = float(quantity) / avg_volume if avg_volume > 0 else 0.0
        quality_score = 1.0 if pd.notna(price) and float(price) > 0 else 0.5
        events.append(
            make_event(
                symbol=symbol,
                event_type="BULK_DEAL",
                timestamp=f"{row_date.isoformat()}T16:00:00",
                raw_signal_strength=raw_strength,
                source="nse_bulk_deals",
                quality_score=quality_score,
                metadata={
                    "client": row.get("ClientName") or row.get("CLIENTNAME"),
                    "buy_or_sell": row.get("BuyOrSell") or row.get("BUYORSELL"),
                    "quantity": int(float(quantity)),
                    "price": float(price) if pd.notna(price) else None,
                    "security_name": row.get("SecurityName") or row.get("SECURITYNAME"),
                    "avg_daily_volume": avg_volume,
                },
            )
        )
    return events


def produce_bulk_deals(
    db_path: str | None = None,
    trade_date: date | str | None = None,
    session: requests.Session | None = None,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_settings = settings or load_settings()
    conn = init_db(db_path or get_db_path(active_settings))
    content = download_bulk_deals(session=session)
    if not content:
        return []
    return parse_bulk_deals_csv(content, conn, settings=active_settings, trade_date=trade_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and parse NSE bulk deals.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--db-path", default=str(get_db_path()))
    args = parser.parse_args()
    events = produce_bulk_deals(db_path=args.db_path, trade_date=args.date)
    print(pd.DataFrame(events).to_json(orient="records"))


if __name__ == "__main__":
    main()
