from __future__ import annotations

from typing import Any

from signal_engine.alerts.telegram import TelegramAlerter
from signal_engine.normalization.dedup import EventNormalizer
from signal_engine.queue.redis_queue import RedisQueue
from signal_engine.risk.filter import RiskFilter
from signal_engine.rules.evaluator import RuleEvaluator
from signal_engine.scoring.engine import SignalScorer
from signal_engine.utils import load_settings


class EventWorker:
    def __init__(
        self,
        db_conn: Any,
        settings: dict[str, Any] | None = None,
        queue: RedisQueue | None = None,
        scorer: SignalScorer | None = None,
        risk_filter: RiskFilter | None = None,
        rule_evaluator: RuleEvaluator | None = None,
        alerter: TelegramAlerter | None = None,
    ):
        self.db_conn = db_conn
        self.settings = settings or load_settings()
        self.queue = queue or RedisQueue(self.settings)
        self.scorer = scorer or SignalScorer(settings=self.settings, db_conn=self.db_conn)
        self.risk_filter = risk_filter or RiskFilter(settings=self.settings)
        self.rule_evaluator = rule_evaluator or RuleEvaluator()
        self.alerter = alerter or TelegramAlerter(settings=self.settings, db_conn=self.db_conn, risk_filter=self.risk_filter)
        self.normalizer = EventNormalizer(self.db_conn)

    def process_event(self, event_dict: dict[str, Any]) -> dict[str, Any] | None:
        if not event_dict:
            return None
        event_date = event_dict["timestamp"].split("T", 1)[0]
        grouped_events = self.normalizer.fetch_symbol_day_events(event_dict["symbol"], event_date)
        if not grouped_events:
            return None
        signal = self.scorer.score(grouped_events)
        signal["confidence"] = self.rule_evaluator.evaluate(signal, [item["event_type"] for item in grouped_events])
        self.scorer.save_signal(signal)
        if signal["confidence"] >= float(self.settings.get("alert_threshold", 5.0)) and self.risk_filter.passes(signal, self.db_conn):
            self.alerter.send(signal)
        return signal

    def process_once(self, timeout: int = 5) -> dict[str, Any] | None:
        event = self.queue.pop(timeout=timeout)
        if event is None:
            return None
        try:
            return self.process_event(event)
        except Exception as exc:
            self.queue.push_dead_letter(event, str(exc))
            return None

    def drain(self, max_items: int | None = None) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        count = 0
        while self.queue.queue_depth() > 0:
            if max_items is not None and count >= max_items:
                break
            result = self.process_once(timeout=1)
            if result is not None:
                processed.append(result)
            count += 1
        return processed


def main() -> None:
    print(EventWorker)


if __name__ == "__main__":
    main()
