"""TickFlow HTTP adapter for authenticated A-share quotes and K-lines.

TickFlow is deliberately optional: without ``TICKFLOW_API_KEY`` this module
does not make network calls.  The adapter normalizes the documented compact
responses into the same dictionaries used by ``SourceManager`` and keeps the
API key out of URLs and error messages.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv

    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

from src.infrastructure.market_data.provider_resilience import (
    ProviderCircuitOpenError,
    compute_retry_delay,
    parse_retry_after,
    record_provider_failure,
    record_provider_success,
    reserve_provider_request,
)

DEFAULT_BASE_URL = "https://api.tickflow.org"
_CHINA_TZ = timezone(timedelta(hours=8))
_MAX_RETRIES = 2
_HOST_INTERVAL_SECONDS = 0.25
_HOST_JITTER_SECONDS = 0.10


class TickFlowError(RuntimeError):
    """Raised when TickFlow cannot return a valid response."""


def _network_failure_reason(exc: BaseException) -> tuple[str, bool]:
    """Return a stable reason and whether Windows denied the socket call."""
    candidates = (exc, getattr(exc, "reason", None))
    for candidate in candidates:
        code = getattr(candidate, "winerror", None) or getattr(candidate, "errno", None)
        text = str(candidate or "")
        if code == 10013 or "WinError 10013" in text:
            return "windows_socket_denied (WinError 10013)", True
        if code == 10057 or "WinError 10057" in text:
            return "windows_socket_not_connected (WinError 10057)", True
    return (str(exc)[:160] or exc.__class__.__name__), False


def get_api_key() -> str:
    return str(os.getenv("TICKFLOW_API_KEY") or "").strip()


def is_configured() -> bool:
    """Return whether the optional authenticated provider can be called."""
    return bool(get_api_key())


def _configured_timeout(default: float) -> float:
    value = str(os.getenv("TICKFLOW_TIMEOUT_SECONDS") or default).strip()
    try:
        return max(1.0, float(value))
    except ValueError:
        return float(default)


def _base_url() -> str:
    value = str(os.getenv("TICKFLOW_BASE_URL") or DEFAULT_BASE_URL).strip()
    return value.rstrip("/") + "/"


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_percent(value: Any) -> float:
    """Convert TickFlow's decimal ratio fields to the platform's percent unit."""
    return _as_float(value) * 100.0


def _timestamp_seconds(value: Any) -> float:
    numeric = _as_float(value)
    if numeric > 10_000_000_000:
        return numeric / 1000.0
    return numeric


def _timestamp_iso(value: Any) -> str:
    seconds = _timestamp_seconds(value)
    if seconds <= 0:
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _timestamp_date(value: Any) -> str:
    seconds = _timestamp_seconds(value)
    if seconds <= 0:
        return ""
    return datetime.fromtimestamp(seconds, tz=_CHINA_TZ).date().isoformat()


def _json_data(payload: object) -> Any:
    if not isinstance(payload, dict):
        raise TickFlowError("TickFlow response is not an object")
    if payload.get("error") or payload.get("errors"):
        raise TickFlowError("TickFlow returned an API error")
    data = payload.get("data")
    if data is None:
        raise TickFlowError("TickFlow response has no data")
    return data


def _request_json(path: str, params: dict[str, object], timeout_seconds: float) -> Any:
    api_key = get_api_key()
    if not api_key:
        raise TickFlowError("TICKFLOW_API_KEY is not configured")

    url = urljoin(_base_url(), path.lstrip("/"))
    query = urlencode({key: value for key, value in params.items() if value is not None})
    request_url = f"{url}?{query}" if query else url
    host = (urlparse(url).hostname or "api.tickflow.org").lower()
    headers = {
        "Accept": "application/json",
        "User-Agent": "AdaptiveInvestment/6.0 TickFlowAdapter",
        "x-api-key": api_key,
    }
    errors: list[str] = []

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            wait = reserve_provider_request(
                host,
                min_interval_seconds=_HOST_INTERVAL_SECONDS,
                jitter_seconds=_HOST_JITTER_SECONDS,
            )
            if wait > 0:
                time.sleep(wait)
            request = Request(request_url, headers=headers, method="GET")
            with urlopen(request, timeout=float(timeout_seconds)) as response:
                raw = response.read()
            record_provider_success(host)
            try:
                return _json_data(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TickFlowError("TickFlow response is not valid JSON") from exc
        except ProviderCircuitOpenError as exc:
            raise TickFlowError(str(exc)) from exc
        except HTTPError as exc:
            retry_after = parse_retry_after(
                exc.headers.get("Retry-After") if exc.headers else None,
                maximum_seconds=900.0,
            )
            reason = f"HTTP {exc.code}"
            errors.append(reason)
            record_provider_failure(
                host,
                reason,
                failure_threshold=3,
                cooldown_seconds=60.0 if exc.code == 429 else 300.0,
                immediate=exc.code in {401, 403},
                retry_after_seconds=retry_after,
            )
            if exc.code in {400, 401, 403, 404} or attempt == _MAX_RETRIES:
                raise TickFlowError(reason) from exc
            time.sleep(compute_retry_delay(
                attempt,
                base_seconds=0.5,
                jitter_seconds=0.2,
                maximum_seconds=8.0,
                retry_after_seconds=retry_after,
            ))
        except (URLError, TimeoutError, OSError, TickFlowError) as exc:
            reason, windows_socket_denied = _network_failure_reason(exc)
            errors.append(reason)
            if isinstance(exc, TickFlowError) and "response" in reason.lower():
                raise
            record_provider_failure(
                host, reason, failure_threshold=3,
                cooldown_seconds=180.0 if windows_socket_denied else 60.0,
                immediate=windows_socket_denied,
            )
            if attempt == _MAX_RETRIES:
                raise TickFlowError("; ".join(errors)[-300:]) from exc
            time.sleep(compute_retry_delay(
                attempt, base_seconds=0.5, jitter_seconds=0.2, maximum_seconds=8.0,
            ))

    raise TickFlowError("TickFlow request failed")


def _quote_row(data: Any, requested_code: str) -> dict[str, Any]:
    if not isinstance(data, list) or not data:
        raise TickFlowError("TickFlow quote data is empty")
    row = next((item for item in data if isinstance(item, dict)), None)
    if row is None:
        raise TickFlowError("TickFlow quote row is invalid")
    ext = row.get("ext") if isinstance(row.get("ext"), dict) else {}
    symbol = str(row.get("symbol") or requested_code).strip().upper()
    price = _as_float(row.get("last_price"))
    if price <= 0:
        raise TickFlowError(f"TickFlow returned zero price for {requested_code}")
    timestamp = row.get("timestamp")
    exchange_timestamp = _timestamp_iso(timestamp)
    return {
        "stock_code": symbol,
        "stock_name": str(ext.get("name") or row.get("name") or symbol),
        "price": price,
        "change_pct": _as_percent(ext.get("change_pct")),
        "change_amount": _as_float(ext.get("change_amount")),
        "volume": _as_float(row.get("volume")),
        "amount": _as_float(row.get("amount")),
        "amount_yi": _as_float(row.get("amount")) / 1e8,
        "high": _as_float(row.get("high"), price),
        "low": _as_float(row.get("low"), price),
        "open": _as_float(row.get("open"), price),
        "pre_close": _as_float(row.get("prev_close"), price),
        "turnover": _as_percent(ext.get("turnover_rate")),
        "amplitude": _as_percent(ext.get("amplitude")),
        "data_date": _timestamp_date(timestamp),
        "exchange_timestamp": exchange_timestamp,
        "source": "tickflow_live_quote",
    }


def fetch_quote(code: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Fetch and normalize one real-time quote."""
    data = _request_json(
        "/v1/quotes",
        {"symbols": str(code).strip().upper()},
        _configured_timeout(timeout_seconds or 10.0),
    )
    return _quote_row(data, code)


def _kline_rows(data: Any, code: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise TickFlowError("TickFlow K-line data is invalid")
    timestamps = data.get("timestamp") or []
    opens = data.get("open") or []
    highs = data.get("high") or []
    lows = data.get("low") or []
    closes = data.get("close") or []
    volumes = data.get("volume") or []
    amounts = data.get("amount") or []
    length = min(len(timestamps), len(opens), len(highs), len(lows), len(closes))
    if length <= 0:
        raise TickFlowError(f"TickFlow returned no K-lines for {code}")
    return [{
        "date": _timestamp_date(timestamps[index]),
        "open": _as_float(opens[index]),
        "high": _as_float(highs[index]),
        "low": _as_float(lows[index]),
        "close": _as_float(closes[index]),
        "volume": _as_float(volumes[index]) if index < len(volumes) else 0.0,
        "amount": _as_float(amounts[index]) if index < len(amounts) else 0.0,
        "timestamp": _timestamp_iso(timestamps[index]),
        "source": "tickflow_kline",
    } for index in range(length)]


def fetch_klines(
    code: str,
    count: int = 250,
    *,
    timeout_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch normalized daily K-lines in chronological order."""
    data = _request_json(
        "/v1/klines",
        {
            "symbol": str(code).strip().upper(),
            "period": "1d",
            "count": max(1, min(int(count), 10000)),
            "adjust": "none",
        },
        _configured_timeout(timeout_seconds or 15.0),
    )
    return _kline_rows(data, code)
