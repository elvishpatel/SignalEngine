from __future__ import annotations

import argparse
import time
from datetime import date
from typing import Any

import requests

from signal_engine.db.schema import init_db
from signal_engine.monitoring.logger import PipelineMonitor, StructuredLogger
from signal_engine.normalization.dedup import EventNormalizer
from signal_engine.producers.bhavcopy import detect_volume_spikes, process_bhavcopy
from signal_engine.producers.bulk_deals import produce_bulk_deals
from signal_engine.producers.promoter import produce_promoter_events, quarter_from_date
from signal_engine.producers.sector import produce_sector_data
from signal_engine.queue.redis_queue import RedisQueue
from signal_engine.utils import get_db_path, is_trading_weekday, load_settings, parse_date
from signal_engine.validation.backtest import BacktestEvaluator
from signal_engine.workers.event_worker import EventWorker


def run_pipeline(trade_date: date | str | None = None) -> dict[str, Any]:
    settings = load_settings()
    db_path = get_db_path(settings)
    conn = init_db(db_path)
    logger = StructuredLogger.get_logger(__name__)
    queue = RedisQueue(settings=settings)
    monitor = PipelineMonitor(conn, queue=queue, logger=logger)
    target_date = parse_date(trade_date)
    stats: dict[str, Any] = {"date": target_date.isoformat(), "prices": 0, "events": 0, "signals": 0, "backtests": 0}
    session = requests.Session()

    def timed_phase(name: str, func):
        start = time.perf_counter()
        try:
            result = func()
            count = len(result) if hasattr(result, "__len__") else int(bool(result))
            duration_ms = int((time.perf_counter() - start) * 1000)
            monitor.log_pipeline_run(name, "success", count, duration_ms)
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            monitor.log_pipeline_run(name, f"failed:{type(exc).__name__}", 0, duration_ms)
            return [] if name != "bhavcopy" else None

    prices = timed_phase("bhavcopy", lambda: process_bhavcopy(db_path=str(db_path), trade_date=target_date, session=session, settings=settings))
    stats["prices"] = 0 if prices is None else len(prices.index)
    bulk_events = timed_phase("bulk_deals", lambda: produce_bulk_deals(db_path=str(db_path), trade_date=target_date, session=session, settings=settings)) or []
    volume_events = timed_phase("volume_spikes", lambda: detect_volume_spikes(conn, trade_date=target_date, settings=settings)) or []
    sector_events = timed_phase("sector_rotation", lambda: produce_sector_data(db_path=str(db_path), trade_date=target_date, session=session, settings=settings)) or []
    promoter_events = timed_phase(
        "promoter_change",
        lambda: produce_promoter_events(db_path=str(db_path), quarter=quarter_from_date(target_date), session=session, settings=settings),
    ) or []
    raw_events = [*bulk_events, *volume_events, *sector_events, *promoter_events]
    normalized_events = timed_phase("normalization", lambda: EventNormalizer(conn).normalize(raw_events)) or []
    stats["events"] = len(normalized_events)
    for event in normalized_events:
        queue.push(event)
    signals = timed_phase("worker", lambda: EventWorker(db_conn=conn, settings=settings, queue=queue).drain()) or []
    stats["signals"] = len(signals)
    backtester = BacktestEvaluator(conn)
    backtests = timed_phase("backtest", backtester.evaluate_pending)
    stats["backtests"] = int(backtests or 0)
    monitor.queue_depth()
    monitor.dead_letter_count()
    monitor.failed_events_last_hour()
    return stats


def _scheduled_runner() -> None:
    if is_trading_weekday():
        run_pipeline()


def run_scheduler() -> None:
    import schedule

    schedule.every().day.at("16:30").do(_scheduled_runner)
    while True:
        schedule.run_pending()
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the event-driven stock signal engine.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args()
    if args.schedule:
        run_scheduler()
    else:
        print(run_pipeline(trade_date=args.date))


if __name__ == "__main__":
    main()
