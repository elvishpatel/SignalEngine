from __future__ import annotations

import argparse
import io
import logging
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import requests

from signal_engine.db.schema import init_db
from signal_engine.utils import HTTP_HEADERS, get_db_path, load_settings, make_event, parse_date

LOGGER = logging.getLogger(__name__)
NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
SECTOR_URLS = {
    "BANK": "https://archives.nseindia.com/content/indices/ind_niftybanklist.csv",
    "IT": "https://archives.nseindia.com/content/indices/ind_niftyitlist.csv",
    "PHARMA": "https://archives.nseindia.com/content/indices/ind_niftypharmalist.csv",
    "AUTO": "https://archives.nseindia.com/content/indices/ind_niftyautolist.csv",
    "FMCG": "https://archives.nseindia.com/content/indices/ind_niftyfmcglist.csv",
    "METAL": "https://archives.nseindia.com/content/indices/ind_niftymetallist.csv",
    "ENERGY": "https://archives.nseindia.com/content/indices/ind_niftyenergylist.csv",
}


def _download_csv(url: str, session: requests.Session | None = None) -> str | None:
    active_session = session or requests.Session()
    response = active_session.get(url, headers=HTTP_HEADERS, timeout=30)
    if response.status_code == 404:
        LOGGER.info("Sector file unavailable: %s", url)
        return None
    response.raise_for_status()
    return response.text


def _parse_index_symbols(content: str, sector: str, index_name: str) -> list[tuple[str, str, str]]:
    if not content or not content.strip():
        return []
    frame = pd.read_csv(io.StringIO(content))
    if frame.empty:
        return []
    frame.columns = [str(column).strip() for column in frame.columns]
    symbol_column = next((column for column in frame.columns if column.lower() == "symbol"), None)
    if symbol_column is None:
        return []
    records: list[tuple[str, str, str]] = []
    for symbol in frame[symbol_column].dropna().astype(str).str.strip().str.upper():
        if symbol:
            records.append((symbol, sector, index_name))
    return records


def populate_sector_membership(db_conn: Any, memberships: list[tuple[str, str, str]]) -> int:
    if not memberships:
        return 0
    cursor = db_conn.cursor()
    cursor.executemany(
        "INSERT OR REPLACE INTO sector_membership(symbol, sector, index_name) VALUES (?, ?, ?)",
        memberships,
    )
    db_conn.commit()
    return len(memberships)


def load_sector_memberships(db_conn: Any, session: requests.Session | None = None) -> dict[str, list[str]]:
    mappings: list[tuple[str, str, str]] = []
    nifty500_content = _download_csv(NIFTY500_URL, session=session)
    mappings.extend(_parse_index_symbols(nifty500_content or "", "NIFTY500", "NIFTY 500"))
    for sector, url in SECTOR_URLS.items():
        content = _download_csv(url, session=session)
        mappings.extend(_parse_index_symbols(content or "", sector, f"NIFTY {sector.title()}"))
    populate_sector_membership(db_conn, mappings)
    sector_map: dict[str, list[str]] = defaultdict(list)
    for symbol, sector, _ in mappings:
        sector_map[sector].append(symbol)
    return dict(sector_map)


def compute_sector_rotation_events(
    db_conn: Any,
    trade_date: date | str | None = None,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_settings = settings or load_settings()
    target_date = parse_date(trade_date)
    lookback = int(active_settings.get("sector_rotation", {}).get("lookback_days", 5))
    threshold = float(active_settings.get("sector_rotation", {}).get("relative_strength_std_threshold", 1.5))
    sector_members = pd.read_sql_query("SELECT symbol, sector, index_name FROM sector_membership", db_conn)
    if sector_members.empty:
        return []
    distinct_dates = pd.read_sql_query(
        "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date",
        db_conn,
        params=[target_date.isoformat()],
        parse_dates=["date"],
    )
    if len(distinct_dates) < lookback + 1:
        return []
    window_dates = distinct_dates["date"].dt.strftime("%Y-%m-%d").tolist()[-(lookback + 1):]
    placeholders = ",".join(["?"] * len(window_dates))
    prices = pd.read_sql_query(
        f"SELECT symbol, date, close FROM prices WHERE date IN ({placeholders})",
        db_conn,
        params=window_dates,
        parse_dates=["date"],
    )
    if prices.empty:
        return []
    pivot = prices.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    start_date = pivot.index[0]
    end_date = pivot.index[-1]
    sector_returns: dict[str, float] = {}
    nifty_members = sector_members.loc[sector_members["sector"] == "NIFTY500", "symbol"].tolist()
    if not nifty_members:
        nifty_members = list(pivot.columns)

    def average_return(symbols: list[str]) -> float:
        valid_symbols = [symbol for symbol in symbols if symbol in pivot.columns]
        if not valid_symbols:
            return float("nan")
        subset = pivot[valid_symbols]
        first = subset.loc[start_date]
        last = subset.loc[end_date]
        returns = (last / first) - 1
        returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
        if returns.empty:
            return float("nan")
        return float(returns.mean())

    nifty_return = average_return(nifty_members)
    if np.isnan(nifty_return):
        return []
    for sector in sorted(sector_members["sector"].unique()):
        if sector == "NIFTY500":
            continue
        symbols = sector_members.loc[sector_members["sector"] == sector, "symbol"].tolist()
        sector_return = average_return(symbols)
        if np.isnan(sector_return):
            continue
        sector_returns[sector] = sector_return - nifty_return
    if not sector_returns:
        return []
    relative_strengths = np.array(list(sector_returns.values()), dtype=float)
    rs_mean = float(relative_strengths.mean())
    rs_std = float(relative_strengths.std(ddof=0))
    events: list[dict[str, Any]] = []
    for sector, relative_strength in sector_returns.items():
        z_score = (relative_strength - rs_mean) / rs_std if rs_std > 0 else relative_strength * 100
        if z_score <= threshold:
            continue
        members = sector_members.loc[sector_members["sector"] == sector, "symbol"].tolist()
        for symbol in members:
            events.append(
                make_event(
                    symbol=symbol,
                    event_type="SECTOR_ROTATION",
                    timestamp=f"{target_date.isoformat()}T16:00:00",
                    raw_signal_strength=float(z_score),
                    source="nse_sector",
                    quality_score=1.0,
                    metadata={
                        "sector": sector,
                        "sector_return": float(relative_strength + nifty_return),
                        "nifty500_return": float(nifty_return),
                        "relative_strength": float(relative_strength),
                    },
                )
            )
    return events


def produce_sector_data(
    db_path: str | None = None,
    trade_date: date | str | None = None,
    session: requests.Session | None = None,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_settings = settings or load_settings()
    conn = init_db(db_path or get_db_path(active_settings))
    load_sector_memberships(conn, session=session)
    return compute_sector_rotation_events(conn, trade_date=trade_date, settings=active_settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load sector membership and compute sector rotation events.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--db-path", default=str(get_db_path()))
    args = parser.parse_args()
    events = produce_sector_data(db_path=args.db_path, trade_date=args.date)
    print(pd.DataFrame(events).to_json(orient="records"))


if __name__ == "__main__":
    main()
