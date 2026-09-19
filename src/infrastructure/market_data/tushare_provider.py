"""Tushare Pro adapter used by Adaptive's A-share truth layer.

The adapter keeps Tushare-specific field units and dates at the boundary.  It
does not label end-of-day data as realtime and it raises on an unusable
response so callers can record a precise fallback reason.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.infrastructure.market_data.tushare_request_budget import (
    BudgetExhaustedError,
    TushareRequestBudget,
)


def _date(value: Any) -> str:
    if value is None:
        return ""
    try:
        if math.isnan(float(value)):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _ts_code(code: str) -> str:
    """Normalize a six-digit local code to Tushare's exchange-qualified code."""
    text = str(code or "").strip().upper()
    if "." in text:
        return text
    if text.startswith(("6", "68", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "2", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8")):
        return f"{text}.BJ"
    return text


def _clean_record(row: dict[str, Any]) -> dict[str, Any]:
    """Convert pandas/numpy scalar values to JSON-safe Python values."""
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            cleaned[key] = None
            continue
        try:
            if math.isnan(float(value)):
                cleaned[key] = None
                continue
        except (TypeError, ValueError):
            pass
        scalar = value.item() if hasattr(value, "item") else value
        cleaned[key] = str(scalar) if isinstance(scalar, date | datetime) else scalar
    return cleaned


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "-") or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
        return default if math.isnan(parsed) else parsed
    except (TypeError, ValueError):
        return default


def _value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row.get(key, default)
    except AttributeError:
        value = default
    return default if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


_MONEYFLOW_FIELDS = (
    "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
    "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount"
)


def _moneyflow_history_row(raw: dict[str, Any], fallback_code: str = "") -> dict[str, Any] | None:
    """Normalize one Tushare moneyflow row for single or batched requests."""
    trade_date = _date(raw.get("trade_date"))
    code = _ts_code(raw.get("ts_code") or fallback_code)
    if not code or not trade_date:
        return None

    def net(buy: str, sell: str) -> float:
        return ((_number(raw.get(buy)) or 0.0) - (_number(raw.get(sell)) or 0.0)) * 10000.0

    main_net = net("buy_lg_amount", "sell_lg_amount") + net(
        "buy_elg_amount", "sell_elg_amount"
    )
    return {
        "ts_code": code,
        "trade_date": trade_date,
        "main_net": round(main_net, 2),
        "net_amount": round(
            main_net + net("buy_md_amount", "sell_md_amount")
            + net("buy_sm_amount", "sell_sm_amount"), 2
        ),
        "status": "positive" if main_net > 0 else "negative" if main_net < 0 else "neutral",
        "source": "tushare",
        "endpoint": "moneyflow",
        "raw": _clean_record(raw),
    }


@dataclass(frozen=True)
class TusharePayload:
    data: Any
    endpoint: str
    data_date: str = ""
    coverage_ratio: float | None = None
    row_count: int = 0


class TushareProvider:
    """Small async wrapper with one bounded request lane per process."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv("TUSHARE_TOKEN", "")
        if not self.token:
            try:
                from config.settings import settings
                self.token = str(settings.TUSHARE_TOKEN or "")
            except Exception:
                self.token = ""
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self.min_interval_seconds = 0.30  # 200 calls/minute tier
        budget_path = os.getenv("TUSHARE_BUDGET_DB_PATH", "")
        budget_per_minute = 190
        budget_per_day = 95000
        retry_attempts = 3
        request_timeout_seconds = 30.0
        try:
            from config.settings import settings
            budget_path = budget_path or str(settings.TUSHARE_BUDGET_DB_PATH)
            budget_per_minute = int(settings.TUSHARE_BUDGET_PER_MINUTE)
            budget_per_day = int(settings.TUSHARE_BUDGET_PER_DAY)
            retry_attempts = int(settings.TUSHARE_REQUEST_RETRY_ATTEMPTS)
            request_timeout_seconds = float(settings.TUSHARE_REQUEST_TIMEOUT_SECONDS)
        except Exception:
            pass
        self.request_budget = TushareRequestBudget(
            budget_path or Path(__file__).resolve().parents[3] / "data" / "tushare_request_budget.db",
            max_per_minute=budget_per_minute,
            max_per_day=budget_per_day,
        )
        self.retry_attempts = max(1, retry_attempts)
        self.request_timeout_seconds = max(1.0, request_timeout_seconds)
        self.total_timeout_seconds = (
            self.request_timeout_seconds * self.retry_attempts + 65.0
        )
        self._inflight_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._metrics = {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_queue_wait_seconds": 0.0,
            "total_latency_seconds": 0.0,
            "by_endpoint": {},
            "recent_attempts": [],
        }

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def _call(self, endpoint: str, **kwargs: Any) -> TusharePayload:
        if not self.configured:
            raise RuntimeError("tushare_token_missing")
        loop = asyncio.get_running_loop()

        def invoke() -> Any:
            import tushare as ts
            pro = ts.pro_api(self.token, timeout=self.request_timeout_seconds)
            method = getattr(pro, endpoint)
            return method(**kwargs)

        deadline = loop.time() + max(
            self.request_timeout_seconds, self.total_timeout_seconds
        )
        request_key = json.dumps(
            [endpoint, kwargs], ensure_ascii=False, sort_keys=True, default=str
        )
        request_hash = hashlib.sha256(request_key.encode("utf-8")).hexdigest()[:16]
        for attempt in range(1, self.retry_attempts + 1):
            requested_at = loop.time()
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise BudgetExhaustedError(
                    f"tushare_request_total_timeout:{endpoint}"
                )
            try:
                await self.request_budget.reserve(
                    endpoint, max_wait_seconds=min(65.0, remaining)
                )
            except Exception as exc:
                self._record_attempt({
                    "endpoint": endpoint, "request_hash": request_hash,
                    "attempt_index": attempt, "sent": False,
                    "queue_seconds": round(loop.time() - requested_at, 4),
                    "network_seconds": 0.0,
                    "total_seconds": round(loop.time() - requested_at, 4),
                    "status": type(exc).__name__,
                    "error_type": type(exc).__name__,
                })
                raise
            async with self._lock:
                wait = self.min_interval_seconds - (loop.time() - self._last_call)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_call = loop.time()
                queue_wait = max(0.0, loop.time() - requested_at)

            started = loop.time()
            endpoint_metrics = self._metrics["by_endpoint"].setdefault(
                endpoint,
                {"calls": 0, "successes": 0, "failures": 0},
            )
            self._metrics["calls"] += 1
            endpoint_metrics["calls"] += 1
            self._metrics["total_queue_wait_seconds"] += queue_wait
            try:
                frame = await self._invoke_deduplicated(
                    request_key,
                    invoke,
                    timeout_seconds=min(
                        self.request_timeout_seconds, max(0.1, deadline - loop.time())
                    ),
                )
                if frame is None or getattr(frame, "empty", False):
                    raise ValueError(f"tushare_empty:{endpoint}")
                self._metrics["successes"] += 1
                endpoint_metrics["successes"] += 1
                self._record_attempt({
                    "endpoint": endpoint, "request_hash": request_hash,
                    "attempt_index": attempt, "sent": True,
                    "queue_seconds": round(queue_wait, 4),
                    "network_seconds": round(loop.time() - started, 4),
                    "total_seconds": round(loop.time() - requested_at, 4),
                    "status": "available", "error_type": "",
                })
                return TusharePayload(data=frame, endpoint=endpoint, row_count=len(frame))
            except Exception as exc:
                self._metrics["failures"] += 1
                endpoint_metrics["failures"] += 1
                self._record_attempt({
                    "endpoint": endpoint, "request_hash": request_hash,
                    "attempt_index": attempt, "sent": True,
                    "queue_seconds": round(queue_wait, 4),
                    "network_seconds": round(loop.time() - started, 4),
                    "total_seconds": round(loop.time() - requested_at, 4),
                    "status": type(exc).__name__,
                    "error_type": type(exc).__name__,
                })
                if attempt >= self.retry_attempts or not self._retryable(exc):
                    raise
                await asyncio.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))
            finally:
                self._metrics["total_latency_seconds"] += max(
                    0.0, loop.time() - started
                )
        raise BudgetExhaustedError(f"tushare_request_exhausted:{endpoint}")

    def _record_attempt(self, item: dict[str, Any]) -> None:
        """Keep bounded, secret-free facts about actual provider attempts."""
        recent = self._metrics.setdefault("recent_attempts", [])
        recent.append(dict(item))
        del recent[:-200]

    async def _invoke_deduplicated(
        self,
        request_key: str,
        invoke: Any,
        *,
        timeout_seconds: float,
    ) -> Any:
        """Never start a second SDK call while the first thread is in flight."""
        async with self._inflight_lock:
            task = self._inflight.get(request_key)
            if task is None or task.done():
                task = asyncio.create_task(asyncio.to_thread(invoke))
                task.add_done_callback(
                    lambda completed: (
                        None
                        if completed.cancelled()
                        else completed.exception()
                    )
                )
                self._inflight[request_key] = task
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), timeout=max(0.1, timeout_seconds)
            )
        finally:
            if task.done():
                async with self._inflight_lock:
                    if self._inflight.get(request_key) is task:
                        self._inflight.pop(request_key, None)

    @staticmethod
    def _retryable(error: Exception) -> bool:
        text = str(error).lower()
        if isinstance(error, BudgetExhaustedError):
            return False
        if "empty" in text or any(
            marker in text for marker in ("权限", "积分", "permission", "invalid", "参数")
        ):
            return False
        return True

    def runtime_stats(self) -> dict[str, Any]:
        """Return redacted process-local request and queue diagnostics."""
        calls = int(self._metrics["calls"] or 0)
        return {
            "calls": calls,
            "successes": int(self._metrics["successes"] or 0),
            "failures": int(self._metrics["failures"] or 0),
            "average_queue_wait_seconds": round(
                float(self._metrics["total_queue_wait_seconds"] or 0) / calls,
                4,
            ) if calls else 0.0,
            "average_latency_seconds": round(
                float(self._metrics["total_latency_seconds"] or 0) / calls,
                4,
            ) if calls else 0.0,
            "by_endpoint": {
                endpoint: dict(values)
                for endpoint, values in self._metrics["by_endpoint"].items()
            },
            "recent_attempts": [dict(item) for item in self._metrics["recent_attempts"]],
            "min_interval_seconds": float(self.min_interval_seconds),
            "request_timeout_seconds": float(self.request_timeout_seconds),
            "budget": self.request_budget.usage(),
        }

    async def latest_trade_date(self, end_date: str = "") -> str:
        end = end_date or date.today().strftime("%Y%m%d")
        start = (date.fromisoformat(_date(end)) - timedelta(days=21)).strftime("%Y%m%d")
        payload = await self._call(
            "trade_cal", exchange="", start_date=start, end_date=end,
            is_open=1, fields="exchange,cal_date,is_open",
        )
        dates = [_date(row.get("cal_date")) for row in payload.data.to_dict("records")]
        dates = [item for item in dates if item]
        if not dates:
            raise ValueError("tushare_no_open_trade_date")
        return max(dates)

    async def recent_trade_dates(self, count: int = 3, end_date: str = "") -> list[str]:
        end = end_date or date.today().strftime("%Y%m%d")
        start = (date.fromisoformat(_date(end)) - timedelta(days=30)).strftime("%Y%m%d")
        payload = await self._call(
            "trade_cal", exchange="", start_date=start, end_date=end,
            is_open=1, fields="exchange,cal_date,is_open",
        )
        dates = sorted({
            _date(row.get("cal_date"))
            for row in payload.data.to_dict("records")
            if row.get("cal_date")
        })
        return dates[-max(1, int(count)):]

    async def fetch_daily_quote(self, code: str) -> TusharePayload:
        ts_code = _ts_code(code)
        daily = await self._call(
            "daily", ts_code=ts_code, limit=2,
            fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
        )
        basic = await self._call(
            "daily_basic", ts_code=ts_code, limit=2,
            fields="ts_code,trade_date,turnover_rate,pe,pe_ttm,pb,ps,ps_ttm,total_mv,circ_mv,volume_ratio",
        )
        daily_rows = daily.data.to_dict("records")
        basic_rows = {str(row.get("trade_date")): row for row in basic.data.to_dict("records")}
        row = daily_rows[0]
        basic_row = basic_rows.get(str(row.get("trade_date")), {})
        data_date = _date(row.get("trade_date"))
        amount = (_number(row.get("amount")) or 0.0) * 1000.0  # Tushare: 千元
        quote = {
            "stock_code": ts_code,
            "price": _number(row.get("close"), 0.0),
            "change_pct": _number(row.get("pct_chg"), 0.0),
            "change_amount": (_number(row.get("close"), 0.0) or 0.0)
            - (_number(row.get("pre_close"), 0.0) or 0.0),
            "open": _number(row.get("open"), 0.0),
            "high": _number(row.get("high"), 0.0),
            "low": _number(row.get("low"), 0.0),
            "pre_close": _number(row.get("pre_close"), 0.0),
            "volume": _number(row.get("vol"), 0.0),
            "amount": amount,
            "amount_yi": round(amount / 100000000.0, 4),
            "turnover": _number(basic_row.get("turnover_rate"), 0.0),
            "pe": _number(basic_row.get("pe_ttm"), 0.0),
            "pb": _number(basic_row.get("pb"), 0.0),
            "ps": _number(basic_row.get("ps_ttm"), 0.0),
            "total_market_cap": (_number(basic_row.get("total_mv"), 0.0) or 0.0) * 10000.0,
            "market_cap_yi": (_number(basic_row.get("total_mv"), 0.0) or 0.0) / 10000.0,
            "circ_market_cap_yi": (_number(basic_row.get("circ_mv"), 0.0) or 0.0) / 10000.0,
            "volume_ratio": _number(basic_row.get("volume_ratio"), 0.0),
            "source": "tushare",
            "endpoint": "daily+daily_basic",
            "data_date": data_date,
            "fetched_at": _iso_now(),
            "is_realtime": False,
        }
        return TusharePayload(quote, "daily+daily_basic", data_date, row_count=1)

    async def fetch_realtime_quote(self, code: str) -> TusharePayload:
        """Fetch the latest A-share one-minute bar from Tushare ``rt_min``.

        The caller still validates session and quote age before execution.  A
        dated daily close must never be relabelled as a realtime quote.
        """
        ts_code = _ts_code(code)
        payload = await self._call("rt_min", ts_code=ts_code, freq="1MIN")
        rows = payload.data.to_dict("records")
        if not rows:
            raise ValueError("tushare_empty:rt_min")
        row = max(rows, key=lambda item: str(item.get("time") or ""))
        exchange_at = str(row.get("time") or "").strip()
        if not exchange_at:
            raise ValueError("tushare_rt_min_timestamp_missing")
        price = _number(row.get("close"), 0.0) or 0.0
        if price <= 0:
            raise ValueError("tushare_rt_min_price_invalid")
        quote = {
            "stock_code": _ts_code(row.get("ts_code") or ts_code),
            "price": price,
            "open": _number(row.get("open"), price),
            "high": _number(row.get("high"), price),
            "low": _number(row.get("low"), price),
            "volume": _number(row.get("vol"), 0.0),
            "amount": _number(row.get("amount"), 0.0),
            "source": "tushare_rt_min",
            "endpoint": "rt_min",
            "data_date": _date(exchange_at),
            "exchange_at": exchange_at,
            "fetched_at": _iso_now(),
            "is_realtime": True,
        }
        return TusharePayload(
            quote, "rt_min", quote["data_date"], row_count=len(rows)
        )

    async def fetch_kline(self, code: str, count: int) -> TusharePayload:
        ts_code = _ts_code(code)
        payload = await self._call(
            "daily", ts_code=ts_code, limit=max(1, min(int(count), 1000)),
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
        )
        rows = []
        for row in reversed(payload.data.to_dict("records")):
            rows.append({
                "date": _date(row.get("trade_date")),
                "open": _number(row.get("open"), 0.0),
                "high": _number(row.get("high"), 0.0),
                "low": _number(row.get("low"), 0.0),
                "close": _number(row.get("close"), 0.0),
                "volume": _number(row.get("vol"), 0.0),
                "amount": (_number(row.get("amount")) or 0.0) * 1000.0,
                "source": "tushare",
                "data_date": _date(row.get("trade_date")),
            })
        return TusharePayload(rows, "daily", rows[-1]["date"] if rows else "", row_count=len(rows))

    async def fetch_daily_history(
        self, code: str, *, start_date: str = "", end_date: str = "", count: int = 250
    ) -> TusharePayload:
        """Fetch a bounded, chronological unadjusted daily history."""
        kwargs: dict[str, Any] = {
            "ts_code": _ts_code(code),
            "limit": max(1, min(int(count), 1000)),
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
        }
        if start_date:
            kwargs["start_date"] = str(start_date).replace("-", "")
        if end_date:
            kwargs["end_date"] = str(end_date).replace("-", "")
        payload = await self._call("daily", **kwargs)
        rows = []
        for raw in payload.data.to_dict("records"):
            trade_date = _date(raw.get("trade_date"))
            if not trade_date:
                continue
            rows.append({
                "ts_code": _ts_code(str(raw.get("ts_code") or code)),
                "trade_date": trade_date,
                "open": _number(raw.get("open")),
                "high": _number(raw.get("high")),
                "low": _number(raw.get("low")),
                "close": _number(raw.get("close")),
                "pre_close": _number(raw.get("pre_close")),
                "change_pct": _number(raw.get("pct_chg")),
                "volume": _number(raw.get("vol")),
                "amount": (_number(raw.get("amount")) or 0.0) * 1000.0,
                "source": "tushare",
            })
        rows.sort(key=lambda item: item["trade_date"])
        return TusharePayload(
            rows, "daily", rows[-1]["trade_date"] if rows else "", row_count=len(rows)
        )

    async def fetch_index_history(
        self, code: str, *, start_date: str = "", end_date: str = "", count: int = 1000
    ) -> TusharePayload:
        """Fetch a bounded, chronological reference-index history.

        Mirrors :meth:`fetch_daily_history` but hits ``index_daily``, whose
        bars live in their own table because indices are not part of the
        tradeable universe and must never enter a scanner pool.
        """
        kwargs: dict[str, Any] = {
            "ts_code": str(code or "").strip().upper(),
            "limit": max(1, min(int(count), 1000)),
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
        }
        if start_date:
            kwargs["start_date"] = str(start_date).replace("-", "")
        if end_date:
            kwargs["end_date"] = str(end_date).replace("-", "")
        payload = await self._call("index_daily", **kwargs)
        rows = []
        for raw in payload.data.to_dict("records"):
            trade_date = _date(raw.get("trade_date"))
            if not trade_date:
                continue
            rows.append({
                "ts_code": str(raw.get("ts_code") or code).strip().upper(),
                "trade_date": trade_date,
                "open": _number(raw.get("open")),
                "high": _number(raw.get("high")),
                "low": _number(raw.get("low")),
                "close": _number(raw.get("close")),
                "pre_close": _number(raw.get("pre_close")),
                "change_pct": _number(raw.get("pct_chg")),
                "volume": _number(raw.get("vol")),
                "amount": (_number(raw.get("amount")) or 0.0) * 1000.0,
                "source": "tushare",
            })
        rows.sort(key=lambda item: item["trade_date"])
        return TusharePayload(
            rows, "index_daily", rows[-1]["trade_date"] if rows else "", row_count=len(rows)
        )

    async def fetch_adjustment_factors(
        self, code: str, *, start_date: str = "", end_date: str = "", count: int = 1000
    ) -> TusharePayload:
        """Fetch adjustment factors separately from raw OHLC bars."""
        kwargs: dict[str, Any] = {
            "ts_code": _ts_code(code),
            "limit": max(1, min(int(count), 1000)),
            "fields": "ts_code,trade_date,adj_factor",
        }
        if start_date:
            kwargs["start_date"] = str(start_date).replace("-", "")
        if end_date:
            kwargs["end_date"] = str(end_date).replace("-", "")
        payload = await self._call("adj_factor", **kwargs)
        rows = [
            {
                "ts_code": _ts_code(str(raw.get("ts_code") or code)),
                "trade_date": _date(raw.get("trade_date")),
                "adj_factor": _number(raw.get("adj_factor")),
                "source": "tushare",
            }
            for raw in payload.data.to_dict("records")
            if _date(raw.get("trade_date")) and _number(raw.get("adj_factor")) is not None
        ]
        rows.sort(key=lambda item: item["trade_date"])
        return TusharePayload(
            rows, "adj_factor", rows[-1]["trade_date"] if rows else "", row_count=len(rows)
        )

    async def fetch_daily_snapshot(self, trade_date: str) -> TusharePayload:
        date_arg = trade_date.replace("-", "")
        daily = await self._call(
            "daily", trade_date=date_arg,
            fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
        )
        basic = await self._call(
            "daily_basic", trade_date=date_arg,
            fields="ts_code,trade_date,turnover_rate,pe_ttm,pb,total_mv,circ_mv",
        )
        basic_map = {str(r.get("ts_code")): r for r in basic.data.to_dict("records")}
        rows = []
        for row in daily.data.to_dict("records"):
            if _date(row.get("trade_date")) != _date(trade_date):
                continue
            code = str(row.get("ts_code") or "").upper()
            if not code.endswith((".SH", ".SZ", ".BJ")):
                continue
            b = basic_map.get(code, {})
            rows.append({
                "ts_code": code, "trade_date": _date(row.get("trade_date")),
                "open": _number(row.get("open"), 0.0), "high": _number(row.get("high"), 0.0),
                "low": _number(row.get("low"), 0.0), "close": _number(row.get("close"), 0.0),
                "pre_close": _number(row.get("pre_close"), 0.0),
                "change_pct": _number(row.get("pct_chg"), 0.0),
                "volume": _number(row.get("vol"), 0.0),
                "amount": (_number(row.get("amount")) or 0.0) * 1000.0,
                "turnover": _number(b.get("turnover_rate"), 0.0),
                "market_cap_yi": (_number(b.get("total_mv")) or 0.0) / 10000.0,
                "float_mcap_yi": (_number(b.get("circ_mv")) or 0.0) / 10000.0,
                "source": "tushare",
            })
        try:
            universe = await self._call(
                "stock_basic", exchange="", list_status="L", fields="ts_code"
            )
            expected = len([
                row for row in universe.data.to_dict("records")
                if str(row.get("ts_code", "")).endswith((".SH", ".SZ", ".BJ"))
            ])
        except Exception:
            expected = 0
        coverage = len(rows) / expected if expected else None
        return TusharePayload(
            rows, "daily+daily_basic", _date(trade_date), coverage, len(rows)
        )

    async def fetch_stock_metadata(self) -> TusharePayload:
        payload = await self._call(
            "stock_basic", exchange="", list_status="L",
            fields="ts_code,name,industry,list_date",
        )
        rows = [
            {
                "ts_code": str(row.get("ts_code") or "").upper(),
                "name": str(row.get("name") or ""),
                "industry": str(row.get("industry") or ""),
                "list_date": _date(row.get("list_date")),
                "source": "tushare",
            }
            for row in payload.data.to_dict("records")
            if str(row.get("ts_code") or "").upper().endswith((".SH", ".SZ", ".BJ"))
        ]
        return TusharePayload(rows, "stock_basic", row_count=len(rows))

    async def fetch_indices(self) -> TusharePayload:
        target = await self.latest_trade_date()
        mapping = {
            "000001.SH": "上证指数", "399001.SZ": "深证成指",
            "399006.SZ": "创业板指", "000688.SH": "科创50",
        }
        result = []
        for code, name in mapping.items():
            payload = await self._call(
                "index_daily", ts_code=code, trade_date=target.replace("-", ""),
                fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
            )
            row = payload.data.to_dict("records")[0]
            result.append({
                "name": name, "code": code, "value": _number(row.get("close"), 0.0),
                "change_pct": _number(row.get("pct_chg"), 0.0),
                "data_date": _date(row.get("trade_date")), "source": "tushare",
            })
        return TusharePayload(result, "index_daily", target, row_count=len(result))

    async def fetch_index_closes(self, code: str, count: int) -> TusharePayload:
        """Fetch a chronological close series for a benchmark index."""
        payload = await self._call(
            "index_daily",
            ts_code=str(code or "").strip().upper(),
            limit=max(1, min(int(count), 1000)),
            fields="ts_code,trade_date,close",
        )
        rows = sorted(
            payload.data.to_dict("records"),
            key=lambda row: _date(row.get("trade_date")),
        )
        closes = {
            _date(row.get("trade_date")): _number(row.get("close"))
            for row in rows
            if _date(row.get("trade_date")) and _number(row.get("close"))
        }
        if not closes:
            raise ValueError("tushare_empty:index_daily_close")
        return TusharePayload(
            closes,
            "index_daily",
            max(closes),
            row_count=len(closes),
        )

    async def fetch_breadth(self) -> TusharePayload:
        target = await self.latest_trade_date()
        daily = await self.fetch_daily_snapshot(target)
        rows = [row for row in daily.data if (_number(row.get("close")) or 0) > 0]
        up = sum(1 for row in rows if (_number(row.get("change_pct")) or 0) > 0)
        down = sum(1 for row in rows if (_number(row.get("change_pct")) or 0) < 0)
        flat = len(rows) - up - down
        try:
            limits = await self._call("stk_limit", trade_date=target.replace("-", ""),
                                      fields="trade_date,ts_code,up_limit,down_limit")
            limit_map = {str(row.get("ts_code")): row for row in limits.data.to_dict("records")}

            def _at_limit(row: dict, field: str, upper: bool) -> bool:
                limit_row = limit_map.get(str(row.get("ts_code")))
                close = _number(row.get("close"))
                limit = _number(limit_row.get(field)) if limit_row else None
                if close is None or limit is None or limit <= 0:
                    return False
                return close >= limit - 0.011 if upper else close <= limit + 0.011

            limit_up = sum(_at_limit(row, "up_limit", True) for row in rows)
            limit_down = sum(_at_limit(row, "down_limit", False) for row in rows)
            limit_source = "tushare.stk_limit"
        except Exception:
            limit_up = None
            limit_down = None
            limit_source = "unavailable"
        coverage = daily.coverage_ratio
        expected = int(round(len(rows) / coverage)) if coverage else 0
        data = {
            "data_date": target, "covered_stocks": len(rows), "expected_stocks": expected,
            "coverage_ratio": round(coverage, 4) if coverage is not None else None,
            "up": up, "down": down, "flat": flat, "total": len(rows),
            "limit_up": limit_up, "limit_down": limit_down,
            "limit_counts_complete": limit_up is not None and limit_down is not None,
            "limit_source": limit_source,
            "total_volume": round(
                sum(_number(row.get("amount"), 0.0) or 0.0 for row in rows) / 1e12,
                4,
            ),
            "source": "tushare", "endpoint": "daily+daily_basic+stk_limit",
        }
        return TusharePayload(data, "daily+daily_basic+stk_limit", target, coverage, len(rows))

    async def fetch_fundamental(self, code: str) -> TusharePayload:
        ts_code = _ts_code(code)
        payload = await self._call("fina_indicator", ts_code=ts_code, limit=1)
        row = payload.data.to_dict("records")[0]
        income = await self._call("income", ts_code=ts_code, limit=1)
        income_row = income.data.to_dict("records")[0]
        data = {
            "available": True, "source": "tushare", "endpoint": "fina_indicator+income",
            "ann_date": _date(row.get("ann_date")), "end_date": _date(row.get("end_date")),
            "eps": _number(row.get("eps")), "roe": _number(row.get("roe")),
            "roa": _number(row.get("roa")), "revenue_yoy": _number(row.get("tr_yoy")),
            "profit_yoy": _number(row.get("netprofit_yoy")),
            "net_profit": _number(income_row.get("n_income_attr_p") or income_row.get("n_income")),
            "revenue": _number(income_row.get("total_revenue") or income_row.get("revenue")),
            "data_date": _date(row.get("ann_date") or row.get("end_date")),
            "fetched_at": _iso_now(),
        }
        return TusharePayload(data, "fina_indicator+income", data["data_date"], row_count=1)

    async def fetch_financial_history(
        self, code: str, periods: int = 8,
        endpoints: tuple[str, ...] | list[str] | None = None,
    ) -> TusharePayload:
        """Fetch independent multi-period statement and indicator histories."""
        ts_code = _ts_code(code)
        limit = max(1, min(int(periods), 12))
        endpoint_names = tuple(endpoints or (
            "income", "balancesheet", "cashflow", "fina_indicator"
        ))
        endpoint_names = tuple(
            name for name in endpoint_names
            if name in {"income", "balancesheet", "cashflow", "fina_indicator"}
        )
        # Tushare statement endpoints may return several revisions or annual
        # cumulative rows for one report period. Fetch a bounded buffer and
        # deduplicate by end_date so "8 rows" cannot be mistaken for 8 periods.
        fetch_limit = max(24, limit * 4)

        async def fetch_one(endpoint: str) -> tuple[str, list[dict[str, Any]], str]:
            raw_rows: list[dict[str, Any]] = []
            error = ""
            try:
                previous_page = None
                for page in range(8):
                    payload = await self._call(
                        endpoint, ts_code=ts_code, limit=fetch_limit,
                        offset=page * fetch_limit,
                    )
                    batch = [_clean_record(row) for row in payload.data.to_dict("records")]
                    if batch == previous_page:
                        error = f"{endpoint}:pagination_no_progress"
                        break
                    previous_page = batch
                    # Do not mix single-quarter/parent-company reports into
                    # consolidated year-to-date statements.
                    raw_rows.extend(row for row in batch if str(row.get("report_type") or "1")
                                    in {"1", "4", "5"})
                    periods_seen = {_date(row.get("end_date")) for row in raw_rows}
                    periods_seen.discard("")
                    if len(periods_seen) >= limit or len(batch) < fetch_limit:
                        break
                else:
                    error = f"{endpoint}:pagination_budget_exhausted"
            except Exception as exc:
                error = f"{endpoint}:{type(exc).__name__}:{str(exc)[:120]}"
            if raw_rows:
                raw_rows.sort(
                    key=lambda row: (
                        _date(row.get("end_date") or row.get("ann_date")),
                        _date(row.get("ann_date")),
                    ),
                    reverse=True,
                )
                rows = []
                seen_periods: set[str] = set()
                for row in raw_rows:
                    period = _date(row.get("end_date") or row.get("report_date") or row.get("ann_date"))
                    if not period or period in seen_periods:
                        continue
                    seen_periods.add(period)
                    rows.append(row)
                    if len(rows) >= limit:
                        break
                return endpoint, rows, error
            return endpoint, [], error

        results = await asyncio.gather(
            *(fetch_one(endpoint) for endpoint in endpoint_names)
        )
        statements = {endpoint: rows for endpoint, rows, _ in results}
        errors = [error for _, _, error in results if error]
        dates = [
            _date(row.get("ann_date") or row.get("end_date"))
            for rows in statements.values()
            for row in rows
            if _date(row.get("ann_date") or row.get("end_date"))
        ]
        data = {
            "available": any(statements.values()),
            "source": "tushare",
            "endpoint": "income+balancesheet+cashflow+fina_indicator",
            "statements": statements,
            "period_counts": {endpoint: len(rows) for endpoint, rows in statements.items()},
            "errors": errors,
            "data_date": max(dates, default=""),
            "fetched_at": _iso_now(),
        }
        return TusharePayload(data, data["endpoint"], data["data_date"], row_count=sum(map(len, statements.values())))

    async def fetch_financial_statements(self, code: str) -> TusharePayload:
        """Fetch the latest income, balance-sheet and cash-flow rows."""
        ts_code = _ts_code(code)
        results = {}
        for endpoint in ("income", "balancesheet", "cashflow"):
            payload = await self._call(endpoint, ts_code=ts_code, limit=1)
            results[endpoint] = _clean_record(payload.data.to_dict("records")[0])
        dates = [
            _date(row.get("ann_date") or row.get("end_date"))
            for row in results.values()
        ]
        data_date = max(dates) if dates else ""
        return TusharePayload(
            {
                "available": True,
                "source": "tushare",
                "endpoint": "income+balancesheet+cashflow",
                "data_date": data_date,
                "fetched_at": _iso_now(),
                **results,
            },
            "income+balancesheet+cashflow",
            data_date,
            row_count=3,
        )

    async def fetch_moneyflow(self, code: str, days: int = 5) -> TusharePayload:
        ts_code = _ts_code(code)
        payload = await self._call(
            "moneyflow", ts_code=ts_code, limit=max(1, min(int(days), 120)),
            fields="ts_code,trade_date,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,buy_md_amount,sell_md_amount,buy_sm_amount,sell_sm_amount",
        )
        rows = payload.data.to_dict("records")
        latest = rows[0]
        def total(row: dict, buy: str, sell: str) -> float:
            return ((_number(row.get(buy)) or 0.0) - (_number(row.get(sell)) or 0.0)) * 10000.0
        main_values = [
            total(row, "buy_lg_amount", "sell_lg_amount")
            + total(row, "buy_elg_amount", "sell_elg_amount")
            for row in rows
        ]
        net_values = [
            main
            + total(row, "buy_md_amount", "sell_md_amount")
            + total(row, "buy_sm_amount", "sell_sm_amount")
            for row, main in zip(rows, main_values, strict=False)
        ]
        main_net = sum(main_values)
        data_date = _date(latest.get("trade_date"))
        data = {
            "status": "positive" if main_net > 0 else "negative",
            "main_net": round(main_net, 2),
            "latest_main_net": round(main_values[0], 2),
            "net_amount": round(sum(net_values), 2),
            "row_count": len(rows),
            "trade_date": data_date,
            "data_date": data_date,
            "source": "tushare",
            "endpoint": "moneyflow",
            "attempted": True,
            "fallback_attempted": True,
            "fallback_status": "confirmed",
            "fetched_at": _iso_now(),
        }
        return TusharePayload(data, "moneyflow", data["data_date"], row_count=len(rows))

    async def fetch_moneyflow_history(self, code: str, days: int = 20) -> TusharePayload:
        """Fetch dated money-flow rows while preserving Tushare's raw units."""
        ts_code = _ts_code(code)
        payload = await self._call(
            "moneyflow", ts_code=ts_code, limit=max(1, min(int(days), 120)),
            fields=(
                "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
                "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount"
            ),
        )
        rows: list[dict[str, Any]] = []
        for raw in payload.data.to_dict("records"):
            target = _date(raw.get("trade_date"))
            if not target:
                continue
            def net(buy: str, sell: str) -> float:
                return ((_number(raw.get(buy)) or 0.0) - (_number(raw.get(sell)) or 0.0)) * 10000.0
            main_net = net("buy_lg_amount", "sell_lg_amount") + net(
                "buy_elg_amount", "sell_elg_amount"
            )
            rows.append({
                "ts_code": ts_code,
                "trade_date": target,
                "main_net": round(main_net, 2),
                "net_amount": round(
                    main_net + net("buy_md_amount", "sell_md_amount")
                    + net("buy_sm_amount", "sell_sm_amount"), 2
                ),
                "status": "positive" if main_net > 0 else "negative" if main_net < 0 else "neutral",
                "source": "tushare",
                "endpoint": "moneyflow",
                "raw": _clean_record(raw),
            })
        rows.sort(key=lambda item: item["trade_date"], reverse=True)
        return TusharePayload(
            rows, "moneyflow", rows[0]["trade_date"] if rows else "", row_count=len(rows)
        )

    async def fetch_moneyflow_batch(
        self, codes: list[str], trade_date: str
    ) -> TusharePayload:
        """Fetch one dated moneyflow batch for several A-share codes.

        The caller chunks codes to keep the request payload bounded.  Tushare's
        moneyflow endpoint accepts a comma-separated ``ts_code`` selection;
        the returned rows are still validated against the requested date.
        """
        normalized = []
        for code in codes:
            value = _ts_code(code)
            if value and value not in normalized:
                normalized.append(value)
        expected = _date(trade_date)
        if not normalized or not expected:
            raise ValueError("moneyflow_batch_requires_codes_and_trade_date")
        payload = await self._call(
            "moneyflow",
            ts_code=",".join(normalized),
            trade_date=expected.replace("-", ""),
            fields=_MONEYFLOW_FIELDS,
        )
        allowed = set(normalized)
        rows = []
        for raw in payload.data.to_dict("records"):
            row = _moneyflow_history_row(raw, normalized[0] if len(normalized) == 1 else "")
            if row and row["trade_date"] == expected and row["ts_code"] in allowed:
                rows.append(row)
        return TusharePayload(rows, "moneyflow", expected, row_count=len(rows))

    async def fetch_top_list(
        self, code: str, trade_date: str = ""
    ) -> TusharePayload:
        """Fetch the dated Tushare billboard summary for one stock."""
        target = (trade_date or await self.latest_trade_date()).replace("-", "")
        payload = await self._call(
            "top_list",
            ts_code=_ts_code(code),
            trade_date=target,
        )
        rows = [
            _clean_record(row)
            for row in payload.data.to_dict("records")
            if _date(row.get("trade_date")) == _date(target)
        ]
        if not rows:
            raise ValueError("tushare_empty:top_list")
        return TusharePayload(rows, "top_list", _date(target), row_count=len(rows))

    async def fetch_stock_evidence(self, code: str) -> dict[str, Any]:
        quote = await self.fetch_daily_quote(code)
        fundamental = await self.fetch_fundamental(code)
        flow = await self.fetch_moneyflow(code)
        return {
            "quote": quote.data,
            "fundamental": fundamental.data,
            "fund_flow": flow.data,
            "provenance": {
                "provider": "tushare",
                "endpoints": [quote.endpoint, fundamental.endpoint, flow.endpoint],
                "data_date": max(
                    quote.data_date, fundamental.data_date, flow.data_date
                ),
                "fetched_at": _iso_now(),
            },
        }


tushare_provider = TushareProvider()
