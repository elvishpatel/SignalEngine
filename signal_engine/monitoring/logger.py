from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "module": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        standard = set(logging.makeLogRecord({}).__dict__.keys())
        extras = {key: value for key, value in record.__dict__.items() if key not in standard and not key.startswith("_")}
        payload.update(extras)
        return json.dumps(payload, default=str)


class StructuredLogger:
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger


class PipelineMonitor:
    def __init__(self, db_conn: Any, queue: Any | None = None, logger: logging.Logger | None = None):
        self.db_conn = db_conn
        self.queue = queue
        self.logger = logger or StructuredLogger.get_logger(__name__)

    def queue_depth(self) -> int:
        depth = int(self.queue.queue_depth()) if self.queue is not None else 0
        self.logger.info("queue_depth", extra={"queue_depth": depth})
        return depth

    def dead_letter_count(self) -> int:
        count = int(self.queue.dead_letter_count()) if self.queue is not None else 0
        level = logging.WARNING if count > 10 else logging.INFO
        self.logger.log(level, "dead_letter_count", extra={"dead_letter_count": count})
        return count

    def failed_events_last_hour(self) -> int:
        cursor = self.db_conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM events WHERE quality_score < 0.5 AND created_at >= datetime('now', '-1 hour')"
        )
        count = int(cursor.fetchone()[0])
        self.logger.info("failed_events_last_hour", extra={"failed_events_last_hour": count})
        return count

    def log_pipeline_run(self, phase: str, status: str, count: int, duration_ms: int) -> None:
        self.logger.info(
            "pipeline_phase",
            extra={"phase": phase, "status": status, "count": count, "duration_ms": duration_ms},
        )

    def monitor_forever(self, interval_seconds: int = 60) -> None:
        while True:
            self.queue_depth()
            self.dead_letter_count()
            self.failed_events_last_hour()
            time.sleep(interval_seconds)


def main() -> None:
    logger = StructuredLogger.get_logger(__name__)
    logger.info("logger_ready")


if __name__ == "__main__":
    main()
