from __future__ import annotations

import argparse
import io
import logging
from datetime import date
from typing import Any

import pandas as pd
import requests

from signal_engine.db.schema import init_db
from signal_engine.utils import HTTP_HEADERS, coerce_float, get_db_path, load_settings, make_event, parse_date

LOGGER = logging.getLogger(__name__)
PROMOTER_URL = "https://archives.nseindia.com/corporate/datafiles/shareholding_pattern_{quarter}.csv"
QUARTER_MONTHS = ("Mar", "Jun", "Sep", "Dec")


def quarter_from_date(value: date | str | None = None) -> str:
    current = parse_date(value)
    month = current.month
    if month <= 3:
        return f"Mar{current.year}"
    if month <= 6:
        return f"Jun{current.year}"
    if month <= 9:
        return f"Sep{current.year}"
    return f"Dec{current.year}"


def previous_quarter(quarter: str) -> str:
    month = quarter[:3]
    year = int(quarter[3:])
    index = QUARTER_MONTHS.index(month)
    if index == 0:
        return f"Dec{year - 1}"
    return f"{QUARTER_MONTHS[index - 1]}{year}"


def quarter_end_date(quarter: str) -> date:
    month = quarter[:3]
    year = int(quarter[3:])
    mapping = {
        "Mar": date(year, 3, 31),
        "Jun": date(year, 6, 30),
        "Sep": date(year, 9, 30),
        "Dec": date(year, 12, 31),
    }
    return mapping[month]


def download_shareholding_pattern(quarter: str, session: requests.Session | None = None) -> str | None:
    active_session = session or requests.Session()
    response = active_session.get(PROMOTER_URL.format(quarter=quarter), headers=HTTP_HEADERS, timeout=30)
    if response.status_code == 404:
        LOGGER.info("Shareholding pattern unavailable for %s", quarter)
        return None
    response.raise_for_status()
    return response.text


def _find_symbol_column(columns: list[str]) -> str | None:
    for column in columns:
        if column.lower() == "symbol":
            return column
    for column in columns:
        if "symbol" in column.lower():
            return column
    return None


def _find_promoter_column(columns: list[str]) -> str | None:
    prioritized = [
        column
        for column in columns
        if "promoter" in column.lower()
        and any(token in column.lower() for token in ("holding", "share", "total", "%", "per"))
    ]
    if prioritized:
        return prioritized[0]
    for column in columns:
        if "promoter" in column.lower():
            return column
    return None


def parse_shareholding_csv(content: str, quarter: str) -> pd.DataFrame:
    if not content or not content.strip():
        return pd.DataFrame(columns=["symbol", "promoter_pct", "quarter"])
    frame = pd.read_csv(io.StringIO(content))
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "promoter_pct", "quarter"])
    frame.columns = [str(column).strip() for column in frame.columns]
    symbol_column = _find_symbol_column(list(frame.columns))
    promoter_column = _find_promoter_column(list(frame.columns))
    if symbol_column is None or promoter_column is None:
        return pd.DataFrame(columns=["symbol", "promoter_pct", "quarter"])
    parsed = pd.DataFrame(
        {
            "symbol": frame[symbol_column].astype(str).str.strip().str.upper(),
            "promoter_pct": frame[promoter_column].map(coerce_float),
            "quarter": quarter,
        }
    )
    parsed = parsed[parsed["symbol"] != ""].drop_duplicates(subset=["symbol"], keep="first")
    return parsed.reset_index(drop=True)


def produce_promoter_events(
    db_path: str | None = None,
    quarter: str | None = None,
    session: requests.Session | None = None,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_settings = settings or load_settings()
    init_db(db_path or get_db_path(active_settings))
    current_quarter = quarter or quarter_from_date()
    prior_quarter = previous_quarter(current_quarter)
    current_content = download_shareholding_pattern(current_quarter, session=session)
    previous_content = download_shareholding_pattern(prior_quarter, session=session)
    if not current_content or not previous_content:
        return []
    current_df = parse_shareholding_csv(current_content, current_quarter)
    previous_df = parse_shareholding_csv(previous_content, prior_quarter)
    if current_df.empty or previous_df.empty:
        return []
    merged = current_df.merge(previous_df, on="symbol", suffixes=("_current", "_previous"))
    merged["change_pct"] = merged["promoter_pct_current"] - merged["promoter_pct_previous"]
    threshold = float(active_settings.get("promoter_change", {}).get("min_change_pct", 1.0))
    filtered = merged[merged["change_pct"].abs() > threshold]
    event_date = quarter_end_date(current_quarter)
    events: list[dict[str, Any]] = []
    for row in filtered.itertuples(index=False):
        change_pct = float(row.change_pct)
        events.append(
            make_event(
                symbol=row.symbol,
                event_type="PROMOTER_CHANGE",
                timestamp=f"{event_date.isoformat()}T16:00:00",
                raw_signal_strength=abs(change_pct),
                source="nse_shareholding",
                quality_score=1.0,
                metadata={
                    "quarter": current_quarter,
                    "current_promoter_pct": float(row.promoter_pct_current),
                    "previous_promoter_pct": float(row.promoter_pct_previous),
                    "change_pct": change_pct,
                },
            )
        )
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and compute promoter holding change events.")
    parser.add_argument("--quarter", default=None)
    parser.add_argument("--db-path", default=str(get_db_path()))
    args = parser.parse_args()
    events = produce_promoter_events(db_path=args.db_path, quarter=args.quarter)
    print(pd.DataFrame(events).to_json(orient="records"))


if __name__ == "__main__":
    main()
