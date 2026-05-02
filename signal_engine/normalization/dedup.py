from __future__ import annotations

from collections import defaultdict
from typing import Any

from signal_engine.utils import EVENT_FIELDS, json_dumps, json_loads, parse_date


class EventNormalizer:
    def __init__(self, db_conn: Any):
        self.db_conn = db_conn

    def _event_exists(self, event_id: str) -> bool:
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT 1 FROM events WHERE event_id = ? LIMIT 1", (event_id,))
        return cursor.fetchone() is not None

    def _merge_duplicates(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for event in events:
            canonical = {field: event[field] for field in EVENT_FIELDS}
            event_id = canonical["event_id"]
            if event_id not in merged:
                merged[event_id] = canonical
                merged[event_id]["metadata"] = dict(canonical.get("metadata") or {})
                merged[event_id]["metadata"]["duplicate_count"] = 1
                continue
            existing = merged[event_id]
            existing["raw_signal_strength"] = max(float(existing["raw_signal_strength"]), float(canonical["raw_signal_strength"]))
            existing["quality_score"] = max(float(existing["quality_score"]), float(canonical["quality_score"]))
            existing["metadata"]["duplicate_count"] = int(existing["metadata"].get("duplicate_count", 1)) + 1
            duplicates = existing["metadata"].setdefault("duplicates", [])
            duplicates.append(canonical.get("metadata") or {})
        return list(merged.values())

    def normalize(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped = [event for event in self._merge_duplicates(events) if not self._event_exists(event["event_id"])]
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for event in deduped:
            event_date = event["timestamp"].split("T", 1)[0]
            groups[(event["symbol"], event_date)].append(event)
        normalized: list[dict[str, Any]] = []
        for (_, event_date), grouped_events in groups.items():
            event_types = sorted({item["event_type"] for item in grouped_events})
            diversity_factor = 1.0 + (0.1 * len(event_types))
            if {"VOLUME_SPIKE", "BULK_DEAL"}.issubset(set(event_types)):
                diversity_factor = max(diversity_factor, 1.2)
            for event in grouped_events:
                metadata = dict(event.get("metadata") or {})
                metadata["active_event_types"] = event_types
                metadata["diversity_factor"] = diversity_factor
                metadata["normalized_date"] = event_date
                metadata["merged_event_count"] = len(grouped_events)
                normalized.append({**event, "metadata": metadata})
        if normalized:
            cursor = self.db_conn.cursor()
            cursor.executemany(
                """
                INSERT OR IGNORE INTO events(event_id, symbol, event_type, timestamp, raw_signal_strength, source, quality_score, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event["event_id"],
                        event["symbol"],
                        event["event_type"],
                        event["timestamp"],
                        float(event["raw_signal_strength"]),
                        event["source"],
                        float(event["quality_score"]),
                        json_dumps(event["metadata"]),
                    )
                    for event in normalized
                ],
            )
            self.db_conn.commit()
        return normalized

    def fetch_symbol_day_events(self, symbol: str, event_date: str) -> list[dict[str, Any]]:
        cursor = self.db_conn.cursor()
        cursor.execute(
            "SELECT event_id, symbol, event_type, timestamp, raw_signal_strength, source, quality_score, metadata FROM events WHERE symbol = ? AND substr(timestamp, 1, 10) = ? ORDER BY timestamp",
            (symbol, parse_date(event_date).isoformat()),
        )
        rows = cursor.fetchall()
        return [
            {
                "event_id": row[0],
                "symbol": row[1],
                "event_type": row[2],
                "timestamp": row[3],
                "raw_signal_strength": float(row[4]),
                "source": row[5],
                "quality_score": float(row[6]),
                "metadata": json_loads(row[7]) if row[7] else {},
            }
            for row in rows
        ]


def main() -> None:
    print(EventNormalizer)


if __name__ == "__main__":
    main()
