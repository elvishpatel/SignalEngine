from __future__ import annotations

import argparse
import io
import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import requests

from signal_engine.db.schema import init_db
from signal_engine.utils import HTTP_HEADERS, get_db_path, load_settings, make_event, parse_date
from signal_engine.validation.quality import QualityValidator

LOGGER = logging.getLogger(__name__)
BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"


def build_bhavcopy_url(trade_date: date) -> str:
    return BHAVCOPY_URL.format(ddmmyyyy=trade_date.strftime("%d%m%Y"))


def _standardize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    mapping = {column: str(column).strip().upper().replace(" ", "_") for column in frame.columns}
    return frame.rename(columns=mapping)


def _pick_column(columns: list[str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise KeyError(f"Could not find any of {candidates} in columns: {columns}")


def download_bhavcopy(trade_date: date, session: requests.Session | None = None) -> str | None:
    active_session = session or requests.Session()
    response = active_session.get(build_bhavcopy_url(trade_date), headers=HTTP_HEADERS, timeout=30)
    if response.status_code == 404:
        LOGGER.info("Bhavcopy unavailable for %s", trade_date.isoformat())
        return None
    response.raise_for_status()
    return response.text


def parse_bhavcopy_csv(content: str, trade_date: date | None = None) -> pd.DataFrame:
    columns = ["symbol", "date", "open", "high", "low", "close", "volume", "source", "quality_score"]
    if not content or not content.strip():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(io.StringIO(content))
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = _standardize_columns(frame)
    raw_columns = list(frame.columns)
    symbol_col = _pick_column(raw_columns, ["SYMBOL"])
    open_col = _pick_column(raw_columns, ["OPEN", "OPEN_PRICE"])
    high_col = _pick_column(raw_columns, ["HIGH", "HIGH_PRICE"])
    low_col = _pick_column(raw_columns, ["LOW", "LOW_PRICE"])
    close_col = _pick_column(raw_columns, ["CLOSE", "CLOSE_PRICE"])
    volume_col = _pick_column(raw_columns, ["TOTTRDQTY", "TTL_TRD_QNTY", "TOTTRD_QTY"])
    if trade_date is None:
        date_col = next((column for column in raw_columns if column in {"DATE", "DATE1", "TIMESTAMP"}), None)
        parsed_date = parse_date(frame.iloc[0][date_col]) if date_col else parse_date(None)
    else:
        parsed_date = trade_date
    return pd.DataFrame(
        {
            "symbol": frame[symbol_col].astype(str).str.strip().str.upper(),
            "date": parsed_date.isoformat(),
            "open": pd.to_numeric(frame[open_col], errors="coerce"),
            "high": pd.to_numeric(frame[high_col], errors="coerce"),
            "low": pd.to_numeric(frame[low_col], errors="coerce"),
            "close": pd.to_numeric(frame[close_col], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_col], errors="coerce"),
            "source": "nse_bhavcopy",
            "quality_score": 1.0,
        }
    )


def store_prices(df: pd.DataFrame, db_conn: Any) -> int:
    if df.empty:
        return 0
    cursor = db_conn.cursor()
    records = [
        (
            row.symbol,
            row.date,
            float(row.open) if pd.notna(row.open) else None,
            float(row.high) if pd.notna(row.high) else None,
            float(row.low) if pd.notna(row.low) else None,
            float(row.close) if pd.notna(row.close) else None,
            int(row.volume) if pd.notna(row.volume) else None,
            row.source,
            float(row.quality_score),
        )
        for row in df.itertuples(index=False)
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO prices(symbol, date, open, high, low, close, volume, source, quality_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    db_conn.commit()
    return cursor.rowcount if cursor.rowcount != -1 else len(records)


def process_bhavcopy(
    db_path: str | None = None,
    trade_date: date | str | None = None,
    session: requests.Session | None = None,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    active_settings = settings or load_settings()
    target_date = parse_date(trade_date)
    content = download_bhavcopy(target_date, session=session)
    if not content:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume", "source", "quality_score"])
    parsed = parse_bhavcopy_csv(content, target_date)
    validated = QualityValidator().validate(parsed, "nse_bhavcopy")
    conn = init_db(db_path or get_db_path(active_settings))
    store_prices(validated, conn)
    return validated


def detect_volume_spikes(db_conn: Any, trade_date: date | str, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    active_settings = settings or load_settings()
    target_date = parse_date(trade_date)
    lookback = int(active_settings.get("volume_spike", {}).get("lookback_days", 20))
    threshold = float(active_settings.get("volume_spike", {}).get("zscore_threshold", 2.5))
    prices = pd.read_sql_query(
        "SELECT symbol, date, volume, quality_score FROM prices WHERE date <= ? ORDER BY symbol, date",
        db_conn,
        params=[target_date.isoformat()],
        parse_dates=["date"],
    )
    if prices.empty:
        return []
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")

    def compute(group: pd.DataFrame) -> pd.DataFrame:
        ordered = group.sort_values("date").copy()
        ordered["rolling_mean"] = ordered["volume"].shift(1).rolling(window=lookback, min_periods=lookback).mean()
        ordered["rolling_std"] = ordered["volume"].shift(1).rolling(window=lookback, min_periods=lookback).std(ddof=0)
        ordered["z_score"] = np.where(
            ordered["rolling_std"] > 0,
            (ordered["volume"] - ordered["rolling_mean"]) / ordered["rolling_std"],
            np.nan,
        )
        return ordered

    computed = prices.groupby("symbol", group_keys=False).apply(compute).reset_index(drop=True)
    same_day = computed[computed["date"].dt.date == target_date]
    events: list[dict[str, Any]] = []
    for row in same_day.itertuples(index=False):
        z_score = float(row.z_score) if pd.notna(row.z_score) else None
        if z_score is None or z_score <= threshold:
            continue
        events.append(
            make_event(
                symbol=row.symbol,
                event_type="VOLUME_SPIKE",
                timestamp=f"{target_date.isoformat()}T16:00:00",
                raw_signal_strength=z_score,
                source="nse_bhavcopy",
                quality_score=float(row.quality_score or 1.0),
                metadata={
                    "volume": int(row.volume),
                    "rolling_mean": float(row.rolling_mean),
                    "rolling_std": float(row.rolling_std),
                    "z_score": z_score,
                },
            )
        )
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and store NSE bhavcopy data.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--db-path", default=str(get_db_path()))
    args = parser.parse_args()
    frame = process_bhavcopy(db_path=args.db_path, trade_date=args.date)
    print(frame.to_json(orient="records"))


if __name__ == "__main__":
    main()
