from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from signal_engine.utils import now_ist


class BacktestEvaluator:
    def __init__(self, db_conn: Any):
        self.db_conn = db_conn

    def _nth_close(self, symbol: str, signal_date: str, offset: int) -> float | None:
        prices = pd.read_sql_query(
            "SELECT date, close FROM prices WHERE symbol = ? AND date >= ? ORDER BY date",
            self.db_conn,
            params=[symbol, signal_date],
        )
        if prices.empty or len(prices.index) <= offset:
            return None
        return float(prices.iloc[offset]["close"])

    def evaluate_pending(self, db_conn: Any | None = None) -> int:
        connection = db_conn or self.db_conn
        pending = pd.read_sql_query(
            """
            SELECT s.signal_id, s.symbol, s.generated_at
            FROM signals s
            LEFT JOIN backtest_results b ON s.signal_id = b.signal_id
            WHERE s.status = 'ALERTED' AND b.signal_id IS NULL
            """,
            connection,
        )
        inserted = 0
        for row in pending.itertuples(index=False):
            signal_date = str(row.generated_at).split("T", 1)[0]
            base_price = self._nth_close(row.symbol, signal_date, 0)
            if base_price is None or base_price <= 0:
                continue
            close_3d = self._nth_close(row.symbol, signal_date, 3)
            close_5d = self._nth_close(row.symbol, signal_date, 5)
            close_10d = self._nth_close(row.symbol, signal_date, 10)
            if close_3d is None or close_5d is None or close_10d is None:
                continue
            return_3d = ((close_3d / base_price) - 1) * 100
            return_5d = ((close_5d / base_price) - 1) * 100
            return_10d = ((close_10d / base_price) - 1) * 100
            connection.execute(
                """
                INSERT INTO backtest_results(signal_id, symbol, signal_date, return_3d, return_5d, return_10d, hit_3d, hit_5d, hit_10d, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.signal_id,
                    row.symbol,
                    signal_date,
                    return_3d,
                    return_5d,
                    return_10d,
                    int(return_3d > 2.0),
                    int(return_5d > 3.0),
                    int(return_10d > 5.0),
                    now_ist().replace(microsecond=0).isoformat(),
                ),
            )
            inserted += 1
        connection.commit()
        return inserted

    def summary(self) -> dict[str, Any]:
        summary = pd.read_sql_query(
            "SELECT COUNT(*) AS total, AVG(hit_3d) AS hit_3d, AVG(hit_5d) AS hit_5d, AVG(hit_10d) AS hit_10d FROM backtest_results",
            self.db_conn,
        )
        if summary.empty:
            return {"hit_rate_3d": 0.0, "hit_rate_5d": 0.0, "hit_rate_10d": 0.0, "total_signals": 0}
        row = summary.iloc[0]
        return {
            "hit_rate_3d": float((row["hit_3d"] or 0.0) * 100),
            "hit_rate_5d": float((row["hit_5d"] or 0.0) * 100),
            "hit_rate_10d": float((row["hit_10d"] or 0.0) * 100),
            "total_signals": int(row["total"] or 0),
        }


def main() -> None:
    print(BacktestEvaluator)


if __name__ == "__main__":
    main()
