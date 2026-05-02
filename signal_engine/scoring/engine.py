from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

from signal_engine.utils import add_trading_days, json_dumps, json_loads, load_settings, sha256_hex


class SignalScorer:
    def __init__(self, settings: dict[str, Any] | None = None, db_conn: Any | None = None):
        self.settings = settings or load_settings()
        self.db_conn = db_conn
        self.weights = {key: float(value) for key, value in self.settings.get("signal_weights", {}).items()}

    def score(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            raise ValueError("score requires at least one event")
        symbol = events[0]["symbol"]
        drivers = []
        weighted_sum = 0.0
        quality_scores = []
        max_timestamp = max(event["timestamp"] for event in events)
        event_types = []
        diversity_candidates = []
        for event in events:
            event_type = event["event_type"]
            event_types.append(event_type)
            if event_type not in drivers:
                drivers.append(event_type)
            weight = self.weights.get(event_type, 0.0)
            weighted_sum += weight * float(event["raw_signal_strength"])
            quality_scores.append(float(event.get("quality_score", 1.0)))
            metadata = event.get("metadata") or {}
            if "diversity_factor" in metadata:
                diversity_candidates.append(float(metadata["diversity_factor"]))
        distinct_count = len(set(event_types))
        diversity_factor = max(diversity_candidates) if diversity_candidates else 1.0 + (0.1 * distinct_count)
        quality_mean = sum(quality_scores) / len(quality_scores)
        confidence = weighted_sum * diversity_factor * quality_mean
        generated_at = max_timestamp
        generated_date = generated_at.split("T", 1)[0]
        validity_days = int(self.settings.get("risk_filter", {}).get("signal_validity_days", 2))
        expires_at = add_trading_days(generated_date, validity_days).replace(hour=16, minute=0, second=0, microsecond=0).isoformat()
        signal = {
            "signal_id": sha256_hex(f"{symbol}{generated_date}"),
            "symbol": symbol,
            "confidence": float(confidence),
            "drivers": drivers,
            "generated_at": generated_at,
            "expires_at": expires_at,
            "status": "ACTIVE",
        }
        if self.db_conn is not None:
            self.save_signal(signal)
        return signal

    def save_signal(self, signal: dict[str, Any]) -> None:
        if self.db_conn is None:
            return
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT status FROM signals WHERE signal_id = ?", (signal["signal_id"],))
        existing = cursor.fetchone()
        status = signal.get("status") or (existing[0] if existing else "ACTIVE")
        cursor.execute(
            """
            INSERT INTO signals(signal_id, symbol, confidence, drivers, generated_at, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET
                symbol = excluded.symbol,
                confidence = excluded.confidence,
                drivers = excluded.drivers,
                generated_at = excluded.generated_at,
                expires_at = excluded.expires_at,
                status = excluded.status
            """,
            (
                signal["signal_id"],
                signal["symbol"],
                float(signal["confidence"]),
                json_dumps(signal["drivers"]),
                signal["generated_at"],
                signal["expires_at"],
                status,
            ),
        )
        self.db_conn.commit()


def main() -> None:
    scorer = SignalScorer()
    sample = [
        {
            "event_id": "1",
            "symbol": "SBIN",
            "event_type": "VOLUME_SPIKE",
            "timestamp": datetime.now().replace(microsecond=0).isoformat(),
            "raw_signal_strength": 3.0,
            "source": "demo",
            "quality_score": 1.0,
            "metadata": {},
        }
    ]
    print(scorer.score(sample))


if __name__ == "__main__":
    main()
