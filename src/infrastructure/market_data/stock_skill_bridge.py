"""Small, auditable bridge for the local ``a-stock-data`` skill.

The skill is a Markdown reference rather than an importable package.  This
module copies only its transport/parser boundary so the Dashboard can use the
same public Tencent and THS feeds without importing a sibling workspace or
creating a second portfolio ledger.

This is deliberately a fallback provider.  The Dashboard remains the source
of truth for decisions, paper fills, reviews, and learning observations.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.infrastructure.market_data.provider_resilience import (
    ProviderCircuitOpenError,
    compute_retry_delay,
    parse_retry_after,
    record_provider_failure,
    record_provider_success,
    reserve_provider_request,
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TRUSTED_CURL_HOSTS = {"qt.gtimg.cn", "zx.10jqka.com.cn"}
_HOST_INTERVALS = {"qt.gtimg.cn": 0.2, "zx.10jqka.com.cn": 0.5}
_PUBLIC_FAILURE_THRESHOLD = 3
_PUBLIC_COOLDOWN_SECONDS = 60.0


class StockSkillFetchError(RuntimeError):
    """Raised when the stock-skill fallback cannot provide trusted data."""


def _as_float(value: object, default: float = 0.0) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"-", "--", "None", "null"}:
        return default
    try:
        return float(text.replace("%", ""))
    except (TypeError, ValueError):
        return default


def _decode_text(raw: bytes) -> str:
    candidates = []
    for encoding in ("utf-8", "gb18030", "gbk"):
        text = raw.decode(encoding, errors="replace")
        cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
        replacement = text.count("\ufffd")
        mojibake = sum(char in "ÃÂÐÑÒÓæåçéêëíîïöøùúüýþÿŷ" for char in text)
        candidates.append((replacement * 100 + mojibake - cjk * 0.01, text))
    return min(candidates, key=lambda item: item[0])[1]


def normalize_stock_code(value: object) -> str:
    """Return the Dashboard's ``000001.SZ`` style code."""
    text = str(value or "").strip().upper()
    digits = "".join(char for char in text if char.isdigit())[:6]
    if len(digits) != 6:
        return ""
    if digits.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{digits}.SH"
    if digits.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{digits}.SZ"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return ""


def _quote_symbol(code: str) -> str:
    normalized = normalize_stock_code(code)
    plain, exchange = normalized.split(".")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}[exchange]
    return f"{prefix}{plain}"


def parse_tencent_quotes(raw: bytes | str, *, fetched_at: str | None = None) -> dict[str, dict]:
    """Parse the complete Tencent field map used by the stock skill.

    The fields intentionally include amplitude, float market cap, limit prices
    and static PE; those are useful for distinguishing a conditional entry from
    chasing an already-extended move.
    """
    text = _decode_text(raw) if isinstance(raw, bytes) else str(raw)
    fetched = fetched_at or datetime.now(timezone.utc).isoformat()
    result: dict[str, dict] = {}
    for line in text.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key, payload = line.split("=", 1)
        values = payload.split('"', 2)[1].split("~")
        if len(values) < 50:
            continue
        key_code = normalize_stock_code(key)
        value_code = normalize_stock_code(values[2] if len(values) > 2 else "")
        code = key_code or value_code
        if not code:
            continue
        exchange_timestamp = values[30].strip() if len(values) > 30 else ""
        data_date = ""
        if len(exchange_timestamp) >= 8 and exchange_timestamp[:8].isdigit():
            data_date = (
                f"{exchange_timestamp[:4]}-{exchange_timestamp[4:6]}-"
                f"{exchange_timestamp[6:8]}"
            )
        quote = {
            "name": values[1],
            "price": _as_float(values[3]),
            "prev_close": _as_float(values[4]),
            "last_close": _as_float(values[4]),
            "open": _as_float(values[5]),
            "change_amt": _as_float(values[31]),
            "change_pct": _as_float(values[32]),
            "high": _as_float(values[33]),
            "low": _as_float(values[34]),
            "amount_wan": _as_float(values[37]),
            "turnover_pct": _as_float(values[38]),
            "pe_ttm": _as_float(values[39]),
            "amplitude_pct": _as_float(values[43]),
            "market_cap_yi": _as_float(values[44]),
            "mcap_yi": _as_float(values[44]),
            "float_mcap_yi": _as_float(values[45]),
            "pb": _as_float(values[46]),
            "limit_up": _as_float(values[47]),
            "limit_down": _as_float(values[48]),
            "volume_ratio": _as_float(values[49]),
            "vol_ratio": _as_float(values[49]),
            "pe_static": _as_float(values[52]) if len(values) > 52 else 0.0,
            "outer_volume_lots": _as_float(values[7]),
            "inner_volume_lots": _as_float(values[8]),
            "source": "stock_skill_tencent_live_quote",
            "data_date": data_date,
            "exchange_timestamp": exchange_timestamp,
            "fetched_at": fetched,
        }
        outer = quote["outer_volume_lots"]
        inner = quote["inner_volume_lots"]
        quote["active_volume_ratio"] = (
            round((outer - inner) / (outer + inner), 6)
            if outer + inner > 0 else None
        )
        result[code] = quote
    if not result:
        raise StockSkillFetchError("Tencent returned no usable quotes")
    return result


def _curl_get(url: str, timeout_seconds: float) -> bytes:
    host = (urlparse(url).hostname or "").lower()
    if host not in _TRUSTED_CURL_HOSTS:
        raise StockSkillFetchError(f"curl fallback refused untrusted host: {host}")
    executable = shutil.which("curl.exe") or shutil.which("curl")
    if not executable:
        raise StockSkillFetchError("curl executable not found")
    timeout = max(1, int(timeout_seconds))
    command = [
        executable, "--fail", "--silent", "--show-error", "--location",
        "--compressed", "--http1.1", "--connect-timeout", str(timeout),
        "--max-time", str(timeout), "--header", f"User-Agent: {UA}", url,
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    completed = subprocess.run(
        command, capture_output=True, check=False, timeout=timeout + 3,
        creationflags=creationflags,
    )
    if completed.returncode != 0 and not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace")[-240:]
        raise StockSkillFetchError(f"curl failed ({completed.returncode}): {detail}")
    return completed.stdout


def _fetch_tencent_quotes_sync(codes: list[str], timeout_seconds: float) -> dict[str, dict]:
    symbols = [_quote_symbol(code) for code in codes if normalize_stock_code(code)]
    if not symbols:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    raw = _fetch_with_transport_retries(
        url,
        timeout_seconds,
        label="Tencent",
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    return parse_tencent_quotes(raw)


async def fetch_tencent_quotes(
    codes: list[str], *, timeout_seconds: float = 10.0
) -> dict[str, dict]:
    """Fetch bounded live quotes without blocking the async event loop."""
    return await asyncio.to_thread(
        _fetch_tencent_quotes_sync, list(codes), float(timeout_seconds)
    )


def parse_ths_hot_reason(raw: bytes | str) -> list[dict]:
    text = _decode_text(raw) if isinstance(raw, bytes) else str(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StockSkillFetchError("THS recommendation response is not JSON") from exc
    if not isinstance(data, dict) or data.get("errocode", 0) != 0:
        raise StockSkillFetchError(
            f"THS recommendation error: {(data or {}).get('errormsg', '')}"
        )
    rows = []
    for item in data.get("data") or []:
        code = normalize_stock_code(item.get("code"))
        if not code:
            continue
        rows.append({
            "rank": len(rows) + 1,
            "code": code,
            "name": item.get("name") or "",
            "reason": item.get("reason") or "",
            "change_pct": _as_float(item.get("zhangfu")),
            "price": _as_float(item.get("close")),
            "turnover_pct": _as_float(item.get("huanshou")),
            "amount": _as_float(item.get("chengjiaoe")),
            "main_net": _as_float(item.get("ddejingliang")),
        })
    return rows


def _fetch_ths_hot_reason_sync(day: str, timeout_seconds: float) -> list[dict]:
    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/date/{day}/"
        "orderby/date/orderway/desc/charset/GBK/"
    )
    raw = _fetch_with_transport_retries(
        url,
        timeout_seconds,
        label="THS",
        headers={"User-Agent": UA, "Accept": "*/*"},
    )
    return parse_ths_hot_reason(raw)


def _fetch_with_transport_retries(
    url: str,
    timeout_seconds: float,
    *,
    label: str,
    headers: dict[str, str],
) -> bytes:
    """Use paced transports without replaying explicit provider rate controls."""
    errors: list[str] = []
    host = (urlparse(url).hostname or "unknown").lower()

    def pace() -> None:
        try:
            wait = reserve_provider_request(
                host,
                min_interval_seconds=_HOST_INTERVALS.get(host, 0.25),
                jitter_seconds=0.15,
            )
        except ProviderCircuitOpenError as exc:
            raise StockSkillFetchError(str(exc)) from exc
        if wait > 0:
            time.sleep(wait)

    for attempt in range(1, 3):
        pace()
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
                record_provider_success(host)
                return raw
        except HTTPError as primary_error:
            retry_after = parse_retry_after(
                primary_error.headers.get("Retry-After") if primary_error.headers else None,
                maximum_seconds=900.0,
            )
            if primary_error.code in {403, 429}:
                record_provider_failure(
                    host,
                    f"HTTP {primary_error.code}",
                    failure_threshold=_PUBLIC_FAILURE_THRESHOLD,
                    cooldown_seconds=_PUBLIC_COOLDOWN_SECONDS,
                    immediate=True,
                    retry_after_seconds=retry_after,
                )
                raise StockSkillFetchError(
                    f"stock-skill {label} rate control detected "
                    f"(HTTP {primary_error.code}); provider cooldown active"
                ) from primary_error
            primary_exception: Exception = primary_error
        except Exception as primary_error:
            primary_exception = primary_error
        try:
            # The alternate Windows transport is also a real provider request,
            # so it must reserve its own slot instead of firing immediately.
            pace()
            try:
                raw = _curl_get(url, timeout_seconds)
                record_provider_success(host)
                return raw
            except Exception as fallback_error:
                errors.append(
                    f"attempt {attempt}: urllib={primary_exception}; curl={fallback_error}"
                )
                record_provider_failure(
                    host,
                    errors[-1],
                    failure_threshold=_PUBLIC_FAILURE_THRESHOLD,
                    cooldown_seconds=_PUBLIC_COOLDOWN_SECONDS,
                )
        except StockSkillFetchError:
            raise
        if attempt < 2:
            time.sleep(
                compute_retry_delay(
                    attempt,
                    base_seconds=0.5,
                    jitter_seconds=0.25,
                    maximum_seconds=4.0,
                )
            )
    raise StockSkillFetchError(
        f"stock-skill {label} transports failed after 2 attempts: {errors[-1]}"
    )


async def fetch_ths_hot_reason(
    day: str, *, timeout_seconds: float = 10.0
) -> list[dict]:
    return await asyncio.to_thread(
        _fetch_ths_hot_reason_sync, day, float(timeout_seconds)
    )
