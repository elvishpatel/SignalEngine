from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
DEFAULT_RULES_PATH = CONFIG_DIR / "rules.yaml"
IST = ZoneInfo("Asia/Kolkata")
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}
EVENT_FIELDS = [
    "event_id",
    "symbol",
    "event_type",
    "timestamp",
    "raw_signal_strength",
    "source",
    "quality_score",
    "metadata",
]


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "None", "~"}:
        return None
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        if any(char in text for char in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _split_key_value(text: str) -> tuple[str, bool, str]:
    if ":" not in text:
        return text.strip(), True, ""
    key, remainder = text.split(":", 1)
    if remainder.strip() == "":
        return key.strip(), False, ""
    return key.strip(), True, remainder.strip()


def _simple_yaml_load(content: str) -> dict[str, Any]:
    raw_lines: list[tuple[int, str]] = []
    for raw in content.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        raw_lines.append((indent, raw.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(raw_lines):
            return {}, index
        current_indent, current_text = raw_lines[index]
        if current_text.startswith("- ") and current_indent == indent:
            return parse_list(index, indent)
        return parse_mapping(index, indent, None)

    def parse_mapping(index: int, indent: int, initial: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
        mapping = initial or {}
        i = index
        while i < len(raw_lines):
            current_indent, text = raw_lines[i]
            if current_indent < indent:
                break
            if current_indent > indent or text.startswith("- "):
                break
            key, has_value, value = _split_key_value(text)
            if has_value:
                mapping[key] = _parse_scalar(value)
                i += 1
            else:
                child, next_index = parse_block(i + 1, indent + 2)
                mapping[key] = child
                i = next_index
        return mapping, i

    def parse_list(index: int, indent: int) -> tuple[list[Any], int]:
        items: list[Any] = []
        i = index
        while i < len(raw_lines):
            current_indent, text = raw_lines[i]
            if current_indent < indent or current_indent != indent or not text.startswith("- "):
                break
            item_text = text[2:].strip()
            if item_text == "":
                child, next_index = parse_block(i + 1, indent + 2)
                items.append(child)
                i = next_index
                continue
            if ":" in item_text:
                key, has_value, value = _split_key_value(item_text)
                initial: dict[str, Any] = {}
                if has_value:
                    initial[key] = _parse_scalar(value)
                    i += 1
                else:
                    child, next_index = parse_block(i + 1, indent + 2)
                    initial[key] = child
                    i = next_index
                parsed_item, next_index = parse_mapping(i, indent + 2, initial)
                items.append(parsed_item)
                i = next_index
                continue
            items.append(_parse_scalar(item_text))
            i += 1
        return items, i

    parsed, _ = parse_block(0, raw_lines[0][0] if raw_lines else 0)
    return parsed if isinstance(parsed, dict) else {"items": parsed}


def ensure_env_loaded(env_path: str | Path | None = None) -> None:
    resolved = Path(env_path) if env_path else PROJECT_ROOT / ".env"
    load_dotenv(resolved, override=False)


def load_yaml(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _simple_yaml_load(text)


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    return load_yaml(path or DEFAULT_SETTINGS_PATH)


def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    return load_yaml(path or DEFAULT_RULES_PATH)


def get_db_path(settings: dict[str, Any] | None = None) -> Path:
    config = settings or load_settings()
    raw_path = config.get("database", {}).get("path", "signal_engine.db")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else get_db_path()
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper().replace(" ", "")


def parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value is None or value == "":
        return now_ist().date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise ValueError(f"Unsupported date value: {value}") from exc


def ensure_timestamp(value: Any, default_time: str = "16:00:00") -> str:
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return f"{value.isoformat()}T{default_time}"
    text = str(value).strip()
    if "T" in text:
        return text
    return f"{parse_date(text).isoformat()}T{default_time}"


def add_trading_days(start_value: date | datetime | str, days: int) -> datetime:
    if isinstance(start_value, datetime):
        current = start_value
    else:
        current = datetime.combine(parse_date(start_value), datetime.min.time(), tzinfo=IST)
    remaining = max(int(days), 0)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def json_loads(value: str | bytes | None) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        if text == "":
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def make_event(
    symbol: str,
    event_type: str,
    timestamp: str | date | datetime,
    raw_signal_strength: float,
    source: str,
    quality_score: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_symbol = normalize_symbol(symbol)
    iso_timestamp = ensure_timestamp(timestamp)
    event_date = iso_timestamp.split("T", 1)[0]
    event = {
        "event_id": sha256_hex(f"{clean_symbol}{event_type}{event_date}"),
        "symbol": clean_symbol,
        "event_type": event_type,
        "timestamp": iso_timestamp,
        "raw_signal_strength": float(raw_signal_strength),
        "source": source,
        "quality_score": float(quality_score),
        "metadata": metadata or {},
    }
    return {field: event[field] for field in EVENT_FIELDS}


def is_trading_weekday(check_date: date | datetime | str | None = None) -> bool:
    return parse_date(check_date or now_ist().date()).weekday() < 5


def getenv(name: str, default: str | None = None) -> str | None:
    ensure_env_loaded()
    return os.getenv(name, default)
