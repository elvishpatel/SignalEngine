from __future__ import annotations

import argparse
import time
from typing import Any

import requests

from signal_engine.utils import ensure_env_loaded, getenv, load_settings, now_ist


class TelegramAlerter:
    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        db_conn: Any | None = None,
        risk_filter: Any | None = None,
        session: requests.Session | None = None,
    ):
        self.settings = settings or load_settings()
        self.db_conn = db_conn
        self.risk_filter = risk_filter
        self.session = session or requests.Session()
        ensure_env_loaded()
        self.token = getenv("TELEGRAM_TOKEN")
        self.chat_id = getenv("TELEGRAM_CHAT_ID")
        self.threshold = float(self.settings.get("alert_threshold", 5.0))

    def _build_message(self, signal_dict: dict[str, Any]) -> str:
        drivers = signal_dict.get("drivers", [])
        if not isinstance(drivers, list):
            drivers = list(drivers)
        return (
            f"?? SIGNAL ALERT\n"
            f"Stock: {signal_dict['symbol']}\n"
            f"Signal: BUY\n"
            f"Confidence: {float(signal_dict['confidence']):.1f}\n"
            f"Drivers: {', '.join(drivers)}\n"
            f"Expires: {signal_dict['expires_at']}\n"
            f"#NSE #StockSignal"
        )

    def send(self, signal_dict: dict[str, Any]) -> bool:
        if float(signal_dict.get("confidence", 0.0)) <= self.threshold:
            return False
        if self.risk_filter is not None and self.db_conn is not None and not self.risk_filter.passes(signal_dict, self.db_conn):
            return False
        if not self.token or not self.chat_id:
            return False
        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            cursor.execute("SELECT status FROM signals WHERE signal_id = ?", (signal_dict["signal_id"],))
            row = cursor.fetchone()
            if row and row[0] == "ALERTED":
                return False
        message = self._build_message(signal_dict)
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message}
        delay = 1
        for attempt in range(3):
            try:
                response = self.session.post(url, data=payload, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        if self.db_conn is not None:
                            cursor = self.db_conn.cursor()
                            cursor.execute(
                                "INSERT INTO alerts(signal_id, symbol, message, sent_at, channel) VALUES (?, ?, ?, ?, 'telegram')",
                                (signal_dict["signal_id"], signal_dict["symbol"], message, now_ist().replace(microsecond=0).isoformat()),
                            )
                            cursor.execute("UPDATE signals SET status = 'ALERTED' WHERE signal_id = ?", (signal_dict["signal_id"],))
                            self.db_conn.commit()
                        return True
            except requests.RequestException:
                pass
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
        return False


def main() -> None:
    print(TelegramAlerter)


if __name__ == "__main__":
    main()
