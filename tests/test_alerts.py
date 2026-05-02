from __future__ import annotations

from tests.conftest import fresh_runtime_dir
from signal_engine.alerts.telegram import TelegramAlerter
from signal_engine.db.schema import init_db


class StubRiskFilter:
    def passes(self, signal_dict, db_conn):
        return True


class MockResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class MockSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post(self, url, data=None, timeout=10):
        self.calls.append({"url": url, "data": data, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_telegram_message_format_and_db_log(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    conn = init_db(fresh_runtime_dir("alerts1") / "alerts.db")
    conn.execute(
        "INSERT INTO signals(signal_id, symbol, confidence, drivers, generated_at, expires_at, status) VALUES ('sig1', 'SBIN', 6.0, '[]', '2024-01-15T16:00:00', '2099-01-01T16:00:00', 'ACTIVE')"
    )
    conn.commit()
    session = MockSession([MockResponse(200, {"ok": True})])
    alerter = TelegramAlerter(db_conn=conn, risk_filter=StubRiskFilter(), session=session)
    signal = {
        "signal_id": "sig1",
        "symbol": "SBIN",
        "confidence": 6.0,
        "drivers": ["VOLUME_SPIKE", "BULK_DEAL"],
        "generated_at": "2024-01-15T16:00:00",
        "expires_at": "2099-01-01T16:00:00",
    }
    assert alerter.send(signal) is True
    assert session.calls[0]["data"]["text"] == (
        "?? SIGNAL ALERT\n"
        "Stock: SBIN\n"
        "Signal: BUY\n"
        "Confidence: 6.0\n"
        "Drivers: VOLUME_SPIKE, BULK_DEAL\n"
        "Expires: 2099-01-01T16:00:00\n"
        "#NSE #StockSignal"
    )
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM signals WHERE signal_id = 'sig1'").fetchone()[0] == "ALERTED"


def test_telegram_retry_logic(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr("time.sleep", lambda _: None)
    conn = init_db(fresh_runtime_dir("alerts2") / "alerts_retry.db")
    conn.execute(
        "INSERT INTO signals(signal_id, symbol, confidence, drivers, generated_at, expires_at, status) VALUES ('sig2', 'SBIN', 6.0, '[]', '2024-01-15T16:00:00', '2099-01-01T16:00:00', 'ACTIVE')"
    )
    conn.commit()
    session = MockSession([
        MockResponse(500, {"ok": False}),
        MockResponse(500, {"ok": False}),
        MockResponse(200, {"ok": True}),
    ])
    alerter = TelegramAlerter(db_conn=conn, risk_filter=StubRiskFilter(), session=session)
    signal = {
        "signal_id": "sig2",
        "symbol": "SBIN",
        "confidence": 6.0,
        "drivers": ["SECTOR_ROTATION"],
        "generated_at": "2024-01-15T16:00:00",
        "expires_at": "2099-01-01T16:00:00",
    }
    assert alerter.send(signal) is True
    assert len(session.calls) == 3
