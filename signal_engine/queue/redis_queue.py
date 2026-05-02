from __future__ import annotations

import argparse
from typing import Any

try:
    import redis  # type: ignore
except ImportError:
    redis = None

from signal_engine.utils import json_dumps, json_loads, load_settings

QUEUE_NAME = "signal_engine:events"
DEAD_LETTER_QUEUE = "signal_engine:dead_letter"


class RedisQueue:
    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or load_settings()
        redis_settings = self.settings.get("redis", {})
        self._memory_main: list[str] = []
        self._memory_dead: list[str] = []
        self.available = False
        self.client = None
        if redis is not None:
            self.client = redis.Redis(
                host=redis_settings.get("host", "localhost"),
                port=int(redis_settings.get("port", 6379)),
                db=int(redis_settings.get("db", 0)),
                decode_responses=False,
            )
            try:
                self.client.ping()
                self.available = True
            except Exception:
                self.available = False

    def push(self, event_dict: dict[str, Any]) -> None:
        payload = json_dumps(event_dict)
        if self.available and self.client is not None:
            self.client.lpush(QUEUE_NAME, payload)
        else:
            self._memory_main.insert(0, payload)

    def pop(self, timeout: int = 5) -> dict[str, Any] | None:
        if self.available and self.client is not None:
            item = self.client.brpop(QUEUE_NAME, timeout=timeout)
            if not item:
                return None
            return json_loads(item[1])
        if not self._memory_main:
            return None
        return json_loads(self._memory_main.pop())

    def push_dead_letter(self, event_dict: dict[str, Any], error: str) -> None:
        payload = json_dumps({"event": event_dict, "error": error})
        if self.available and self.client is not None:
            self.client.lpush(DEAD_LETTER_QUEUE, payload)
        else:
            self._memory_dead.insert(0, payload)

    def queue_depth(self) -> int:
        if self.available and self.client is not None:
            return int(self.client.llen(QUEUE_NAME))
        return len(self._memory_main)

    def dead_letter_count(self) -> int:
        if self.available and self.client is not None:
            return int(self.client.llen(DEAD_LETTER_QUEUE))
        return len(self._memory_dead)

    def retry_dead_letters(self, max: int = 10) -> int:
        retried = 0
        if self.available and self.client is not None:
            while retried < max:
                item = self.client.rpop(DEAD_LETTER_QUEUE)
                if not item:
                    break
                payload = json_loads(item)
                self.push(payload["event"])
                retried += 1
            return retried
        while retried < max and self._memory_dead:
            payload = json_loads(self._memory_dead.pop())
            self.push(payload["event"])
            retried += 1
        return retried


def main() -> None:
    queue = RedisQueue()
    queue.push({"ping": "pong"})
    print(queue.pop(timeout=1))


if __name__ == "__main__":
    main()
