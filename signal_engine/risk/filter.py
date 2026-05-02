from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from signal_engine.utils import load_settings, parse_date


class RiskFilter:
    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or load_settings()
        self.config = self.settings.get("risk_filter", {})

    def _symbol_history(self, db_conn: Any, symbol: str, event_date: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT date, close, volume FROM prices WHERE symbol = ? AND date <= ? ORDER BY date DESC LIMIT 20",
            db_conn,
            params=[symbol, parse_date(event_date).isoformat()],
            parse_dates=["date"],
        ).sort_values("date")

    def _market_return(self, db_conn: Any, event_date: str) -> float:
        membership = pd.read_sql_query("SELECT symbol FROM sector_membership WHERE sector = 'NIFTY500'", db_conn)
        symbols = membership["symbol"].tolist()
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            query = f"SELECT symbol, date, close FROM prices WHERE symbol IN ({placeholders}) AND date <= ?"
            params = [*symbols, parse_date(event_date).isoformat()]
        else:
            query = "SELECT symbol, date, close FROM prices WHERE date <= ?"
            params = [parse_date(event_date).isoformat()]
        prices = pd.read_sql_query(query, db_conn, params=params, parse_dates=["date"])
        if prices.empty:
            return 0.0
        dates = sorted(prices["date"].dt.strftime("%Y-%m-%d").unique())
        if len(dates) < 20:
            return 0.0
        window_dates = dates[-20:]
        window = prices[prices["date"].dt.strftime("%Y-%m-%d").isin(window_dates)]
        pivot = window.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
        if len(pivot.index) < 2:
            return 0.0
        first_mean = float(pivot.iloc[0].dropna().mean())
        last_mean = float(pivot.iloc[-1].dropna().mean())
        if first_mean <= 0:
            return 0.0
        return ((last_mean / first_mean) - 1) * 100

    def passes(self, signal_dict: dict[str, Any], db_conn: Any) -> bool:
        if float(signal_dict.get("confidence", 0.0)) < float(self.config.get("min_confidence", 3.0)):
            return False
        expires_at = signal_dict.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) < datetime.now(tz=datetime.fromisoformat(expires_at).tzinfo):
            return False
        event_date = signal_dict.get("generated_at", "").split("T", 1)[0]
        history = self._symbol_history(db_conn, signal_dict["symbol"], event_date)
        if history.empty:
            return False
        avg_volume = float(history["volume"].astype(float).mean())
        if avg_volume < float(self.config.get("min_avg_volume", 100000)):
            return False
        close_mean = float(history["close"].astype(float).mean())
        close_std = float(history["close"].astype(float).std(ddof=0)) if len(history) > 1 else 0.0
        if close_mean <= 0:
            return False
        volatility = close_std / close_mean
        if volatility > float(self.config.get("max_volatility", 0.05)):
            return False
        market_return = self._market_return(db_conn, event_date)
        if market_return < float(self.config.get("min_market_return_20d", -5.0)):
            return False
        return True


def main() -> None:
    print(RiskFilter)


if __name__ == "__main__":
    main()
