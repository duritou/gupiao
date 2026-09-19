"""Remote daily market discovery for the adaptive decision pipeline.

The local SQLite warehouse remains an auditable cache, but it must not decide
which stocks are interesting.  This module builds the daily candidate pool
from live public A-share feeds:

* THS strong-stock reasons (topic/reason discovery)
* THS popularity ranking
* Eastmoney popularity ranking (THS fallback only)
* Tencent live quotes
* Eastmoney intraday main-money flow

Every returned candidate carries source provenance and the exact features used
for ranking so later outcome observations can learn symbol/source reliability.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from config.settings import settings
from src.infrastructure.market_data.hithink_discovery import (
    HiThinkDiscoveryResult,
    fetch_hithink_special,
)
from src.infrastructure.market_data.provider_resilience import (
    ProviderCircuitOpenError,
    compute_retry_delay,
    ensure_provider_available,
    parse_retry_after,
    record_provider_failure,
    record_provider_success,
    reserve_provider_request,
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_CURL_EASTMONEY_HOSTS = {
    "push2.eastmoney.com",
    "push2his.eastmoney.com",
}


class EastmoneyCircuitOpenError(RuntimeError):
    """Raised when Eastmoney should not be contacted during a cooldown."""


def _curl_get_bytes(
    url: str, headers: dict[str, str], timeout_seconds: float
) -> bytes:
    """Use system curl only for the two trusted Eastmoney flow hosts."""
    host = (urlparse(url).hostname or "").lower()
    if host not in _CURL_EASTMONEY_HOSTS:
        raise RuntimeError(f"curl fallback refused untrusted host: {host}")
    executable = shutil.which("curl.exe") or shutil.which("curl")
    if not executable:
        raise RuntimeError("curl fallback unavailable: curl executable not found")
    timeout = max(1, int(math.ceil(timeout_seconds)))
    command = [
        executable,
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--compressed",
        "--http1.1",
        "--connect-timeout", str(min(timeout, 10)),
        "--max-time", str(timeout),
    ]
    for name, value in {"User-Agent": UA, "Accept": "*/*", **headers}.items():
        header = f"{name}: {value}"
        if "\r" not in header and "\n" not in header:
            command.extend(["--header", header])
    command.append(url)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout + 3,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"curl fallback failed to start: {exc}") from exc
    try:
        json.loads(_decode_text(completed.stdout))
    except (json.JSONDecodeError, TypeError, ValueError):
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[-240:]
        raise RuntimeError(
            f"curl fallback returned invalid JSON (exit {completed.returncode}): {detail}"
        ) from None
    return completed.stdout


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _decode_text(raw: bytes) -> str:
    """Choose the cleanest UTF-8/GBK decode for mixed mainland endpoints."""
    candidates = []
    for encoding in ("utf-8", "gb18030"):
        text = raw.decode(encoding, errors="replace")
        cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
        replacement = text.count("\ufffd")
        mojibake = sum(char in "ÃÂÐÑÒÓæåçéêëíîïöøùúüýþÿŷ" for char in text)
        candidates.append((replacement * 100 + mojibake - cjk * 0.01, text))
    return min(candidates, key=lambda item: item[0])[1]


def normalize_a_share_code(value: Any) -> str:
    """Normalize common A-share code forms to ``000001.SZ``."""
    text = str(value or "").strip().upper()
    exchange_hint = ""
    for prefix in ("SH.", "SZ.", "SH", "SZ"):
        if text.startswith(prefix):
            exchange_hint = prefix[:2]
            text = text[len(prefix):]
            break
    text = text.split(".")[0] if text[:6].isdigit() else text
    digits = "".join(ch for ch in text if ch.isdigit())[:6]
    if len(digits) != 6:
        return ""
    if digits.startswith(("600", "601", "603", "605", "688", "689")):
        if exchange_hint and exchange_hint != "SH":
            return ""
        return f"{digits}.SH"
    if digits.startswith(("000", "001", "002", "003", "300", "301")):
        if exchange_hint and exchange_hint != "SZ":
            return ""
        return f"{digits}.SZ"
    return ""


def _plain_code(code: str) -> str:
    return normalize_a_share_code(code).split(".")[0]


def _source_rank_score(rank: int | float | None) -> float:
    if rank is None:
        return 50.0
    return _clamp(102.0 - float(rank) * 2.0)


@dataclass
class DiscoverySnapshot:
    requested_date: str
    fetched_at: str
    candidates: list[dict] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    remote_available: bool = False
    degraded: bool = True
    stock_skill_fallback: dict[str, int | bool] = field(default_factory=dict)
    provider_observations: dict[str, Any] = field(default_factory=dict)
    version: str = "remote-daily-market-v2-stock-skill"

    def to_dict(self) -> dict:
        return asdict(self)


class RemoteMarketDiscovery:
    """Build a bounded, source-backed candidate pool from remote daily data."""

    def __init__(
        self,
        timeout_seconds: float = 12.0,
        flow_limit: int = 12,
        stock_skill_enabled: bool = True,
        max_quote_count: int = 300,
    ):
        self.timeout_seconds = timeout_seconds
        self.flow_limit = max(1, flow_limit)
        self.stock_skill_enabled = bool(stock_skill_enabled)
        self.max_quote_count = max(1, int(max_quote_count))
        from config.settings import settings
        self.retry_attempts = max(1, int(settings.REMOTE_MARKET_RETRY_ATTEMPTS))
        self.retry_backoff_seconds = max(
            0.1, float(settings.REMOTE_MARKET_RETRY_BACKOFF_SECONDS)
        )
        self.retry_jitter_seconds = max(
            0.0, float(settings.REMOTE_MARKET_RETRY_JITTER_SECONDS)
        )
        self.retry_max_backoff_seconds = max(
            self.retry_backoff_seconds,
            float(settings.REMOTE_MARKET_RETRY_MAX_BACKOFF_SECONDS),
        )
        self.retry_after_max_seconds = max(
            1.0, float(settings.REMOTE_MARKET_RETRY_AFTER_MAX_SECONDS)
        )
        self.public_min_interval_seconds = max(
            0.0, float(settings.PUBLIC_DATA_MIN_INTERVAL_SECONDS)
        )
        self.public_jitter_seconds = max(
            0.0, float(settings.PUBLIC_DATA_JITTER_SECONDS)
        )
        self.public_failure_threshold = max(
            1, int(settings.PUBLIC_DATA_FAILURE_THRESHOLD)
        )
        self.public_cooldown_seconds = max(
            1.0, float(settings.PUBLIC_DATA_COOLDOWN_SECONDS)
        )
        # Match the local a-stock-data skill's conservative Eastmoney policy:
        # one shared serial lane, a 1.5-2.0 second batch gap, and a cooldown
        # after a clear rate-control response or repeated transport failures.
        self.eastmoney_min_interval_seconds = max(
            1.0, float(settings.EASTMONEY_MIN_INTERVAL_SECONDS)
        )
        self.eastmoney_jitter_seconds = max(
            0.0, float(settings.EASTMONEY_JITTER_SECONDS)
        )
        self.eastmoney_cooldown_seconds = max(
            30.0, float(settings.EASTMONEY_COOLDOWN_SECONDS)
        )
        self.eastmoney_failure_threshold = max(
            1, int(settings.EASTMONEY_FAILURE_THRESHOLD)
        )
        self._eastmoney_lock = asyncio.Lock()

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Retry idempotent transient failures with shared pacing and jitter."""
        retry_statuses = {408, 425, 429, 500, 502, 503, 504}
        last_error: Exception | None = None
        host = (urlparse(url).hostname or "unknown").lower()
        retryable_method = method.upper() in {"GET", "HEAD", "OPTIONS"}
        for attempt in range(1, self.retry_attempts + 1):
            wait = reserve_provider_request(
                host,
                min_interval_seconds=self.public_min_interval_seconds,
                jitter_seconds=self.public_jitter_seconds,
            )
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await client.request(method, url, **kwargs)
                retry_after = parse_retry_after(
                    response.headers.get("Retry-After"),
                    maximum_seconds=self.retry_after_max_seconds,
                )
                if response.status_code in {403, 429}:
                    record_provider_failure(
                        host,
                        f"HTTP {response.status_code}",
                        failure_threshold=self.public_failure_threshold,
                        cooldown_seconds=self.public_cooldown_seconds,
                        immediate=True,
                        retry_after_seconds=retry_after,
                    )
                    # A rate-control response is an instruction to stop, not an
                    # invitation to immediately replay the same public request.
                    return response
                if response.status_code not in retry_statuses:
                    record_provider_success(host)
                    return response
                record_provider_failure(
                    host,
                    f"HTTP {response.status_code}",
                    failure_threshold=self.public_failure_threshold,
                    cooldown_seconds=self.public_cooldown_seconds,
                )
                if attempt >= self.retry_attempts or not retryable_method:
                    return response
                last_error = RuntimeError(f"HTTP {response.status_code}")
            except httpx.RequestError as exc:
                last_error = exc
                # A transport failure can be local (Windows socket policy,
                # proxy, TLS backend).  Do not open the provider circuit here:
                # the stock-skill bridge still needs a chance to try curl.
                retry_after = None
                if attempt >= self.retry_attempts or not retryable_method:
                    raise
            delay = compute_retry_delay(
                attempt,
                base_seconds=self.retry_backoff_seconds,
                jitter_seconds=self.retry_jitter_seconds,
                maximum_seconds=self.retry_max_backoff_seconds,
                retry_after_seconds=retry_after,
            )
            await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    async def discover(self, day: str, limit: int = 30) -> DiscoverySnapshot:
        fetched_at = datetime.now(timezone.utc).isoformat()
        errors: list[str] = []
        stock_skill_fallback: dict[str, int | bool] = {
            "enabled": self.stock_skill_enabled,
            "hot_reason": False,
            "quotes": 0,
        }
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": UA},
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=2,
                keepalive_expiry=15.0,
            ),
        ) as client:
            # Prefer THS for popularity discovery. The local a-stock-data
            # skill deliberately keeps Eastmoney as a fallback because its
            # public HTTP endpoints apply stricter traffic controls.
            source_results = await asyncio.gather(
                self._ths_hot_reason(client, day),
                self._ths_hot_list(client),
                return_exceptions=True,
            )

            merged: dict[str, dict] = {}
            source_counts: dict[str, int] = {}
            provider_observations: dict[str, Any] = {}
            source_names = ("ths_hot_reason", "ths_hot_list")
            for source, result in zip(source_names, source_results, strict=False):
                if isinstance(result, Exception):
                    if source == "ths_hot_reason" and self.stock_skill_enabled:
                        try:
                            from src.infrastructure.market_data.stock_skill_bridge import (
                                fetch_ths_hot_reason,
                            )
                            result = await fetch_ths_hot_reason(
                                day, timeout_seconds=self.timeout_seconds
                            )
                            stock_skill_fallback["hot_reason"] = True
                        except Exception as fallback_error:
                            errors.append(
                                f"{source}: {str(result)[:120]}; "
                                f"stock_skill_fallback: {str(fallback_error)[:120]}"
                            )
                            continue
                    else:
                        errors.append(f"{source}: {str(result)[:180]}")
                        continue
                source_counts[source] = len(result)
                self._merge_source(merged, source, result)

            # HiThink special data is isolated behind a rollout switch.  In
            # shadow/validator mode it is fetched only for audit comparison;
            # primary/fallback modes may contribute rows but never alter the
            # downstream score formula or filtering thresholds.
            hithink_mode = str(getattr(settings, "HITHINK_SPECIAL_MODE", "disabled"))
            if hithink_mode != "disabled":
                try:
                    hithink_result: HiThinkDiscoveryResult = await fetch_hithink_special(
                        day,
                        limit,
                    )
                    observation = dict(hithink_result.observation)
                    observation["mode"] = hithink_mode
                    observation["used"] = False
                    provider_observations["hithink_special"] = observation
                    if hithink_result.sources:
                        can_use = hithink_mode == "primary" or (
                            hithink_mode == "fallback" and not merged
                        )
                        if can_use:
                            for source, rows in hithink_result.sources.items():
                                source_counts[source] = len(rows)
                                self._merge_source(merged, source, rows)
                            observation["used"] = True
                except Exception as exc:
                    # A shadow probe must not turn an otherwise healthy
                    # discovery run into a degraded result.  The exception is
                    # reduced to a type-only observation to avoid leaking URLs.
                    provider_observations["hithink_special"] = {
                        "status": "failed",
                        "mode": hithink_mode,
                        "used": False,
                        "error_type": type(exc).__name__,
                    }

            source_counts["eastmoney_hot_rank"] = 0
            if source_counts.get("ths_hot_list", 0) == 0:
                try:
                    eastmoney_rows = await self._eastmoney_hot_rank(
                        client, max(50, limit)
                    )
                    source_counts["eastmoney_hot_rank"] = len(eastmoney_rows)
                    self._merge_source(
                        merged, "eastmoney_hot_rank", eastmoney_rows
                    )
                except Exception as exc:
                    errors.append(f"eastmoney_hot_rank: {str(exc)[:180]}")

            # Bound downstream calls before quote/flow enrichment.
            preliminary = sorted(
                merged.values(),
                key=lambda item: (
                    -len(item["sources"]),
                    min(item["source_ranks"].values(), default=9999),
                ),
            )[: max(limit * 2, 50)]
            codes = [item["stock_code"] for item in preliminary[:self.max_quote_count]]

            quotes: dict[str, dict] = {}
            if codes:
                try:
                    quotes = await self._tencent_quotes(client, codes)
                except Exception as exc:
                    errors.append(f"tencent_quotes: {str(exc)[:180]}")
                    if self.stock_skill_enabled:
                        try:
                            from src.infrastructure.market_data.stock_skill_bridge import (
                                fetch_tencent_quotes,
                            )
                            quotes = await fetch_tencent_quotes(
                                codes, timeout_seconds=self.timeout_seconds
                            )
                            stock_skill_fallback["quotes"] = len(quotes)
                        except Exception as fallback_error:
                            errors.append(
                                "stock_skill_tencent_quotes: "
                                f"{str(fallback_error)[:180]}"
                            )

            quote_ready = [item for item in preliminary if item["stock_code"] in quotes]
            flow_targets = quote_ready[: min(max(limit, 1), self.flow_limit)]
            flows: dict[str, dict] = {}
            if flow_targets:
                # Eastmoney is intentionally serialized and throttled.  Parallel
                # calls are frequently disconnected and can poison the full run.
                consecutive_failures = 0
                for item in flow_targets:
                    code = item["stock_code"]
                    from src.infrastructure.market_data.research_flow import get_research_flow

                    try:
                        flows[code] = await asyncio.wait_for(
                            get_research_flow(code, days=5), timeout=self.timeout_seconds
                        )
                        source_counts["tushare_flow"] = source_counts.get("tushare_flow", 0) + 1
                        continue
                    except Exception as primary_error:
                        primary_reason = f"tushare_flow:{type(primary_error).__name__}"
                    if consecutive_failures >= 2:
                        flows[code] = {
                            "status": "missing", "main_net": None, "row_count": 0,
                            "attempted": True, "fallback_attempted": True,
                            "fallback_status": "exhausted",
                            "error": f"{primary_reason};eastmoney_circuit_open",
                        }
                        continue
                    try:
                        flows[code] = await self._eastmoney_fund_flow(client, code)
                        flows[code]["fallback_reason"] = primary_reason
                        consecutive_failures = 0
                    except Exception as exc:
                        errors.append(f"fund_flow:{code}: {str(exc)[:120]}")
                        flows[code] = {
                            "status": "missing",
                            "main_net": None,
                            "row_count": 0,
                            "attempted": True,
                            "fallback_attempted": True,
                            "fallback_status": "exhausted",
                            "error": str(exc)[:180],
                        }
                        consecutive_failures += 1
                        if consecutive_failures >= 2:
                            errors.append(
                                "eastmoney_fund_flow: disabled after repeated disconnects; "
                                "using Tencent active-volume proxy"
                            )
                            # Keep trying Tushare, but skip Eastmoney for this run.

        ranked: list[dict] = []
        for item in quote_ready:
            code = item["stock_code"]
            quote = quotes[code]
            name = quote.get("name") or item.get("stock_name") or code
            change_pct = abs(_as_float(quote.get("change_pct")))
            if (
                "ST" in name.upper()
                or name.upper().startswith(("N", "C"))
                or change_pct > 30
                or _as_float(quote.get("price")) <= 0
            ):
                continue
            flow = flows.get(code) or {}
            ranked.append(self._score_candidate(item, quote, flow))

        ranked.sort(key=lambda item: item["discovery_score"], reverse=True)
        for index, item in enumerate(ranked[:limit], start=1):
            item["discovery_rank"] = index

        candidates = ranked[:limit]
        return DiscoverySnapshot(
            requested_date=day,
            fetched_at=fetched_at,
            candidates=candidates,
            source_counts=source_counts,
            errors=errors,
            remote_available=bool(candidates),
            degraded=not candidates or bool(errors),
            stock_skill_fallback=stock_skill_fallback,
            provider_observations=provider_observations,
        )

    async def fetch_live_quotes(self, codes: list[str]) -> dict[str, dict]:
        """Fetch causal quotes, with the stock skill as a bounded fallback."""
        # Normalize and de-duplicate within this fetch.  The same symbol can
        # arrive through the normal, momentum, and conditional lanes; sending
        # it repeatedly wastes provider capacity and creates avoidable rate
        # pressure.  No quote is reused across minute ticks, so freshness and
        # causal timestamp checks remain unchanged.
        normalized_codes = list(dict.fromkeys(
            normalized
            for code in codes
            if (normalized := normalize_a_share_code(code))
        ))
        if not normalized_codes:
            return {}
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": UA},
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=2,
                keepalive_expiry=15.0,
            ),
        ) as client:
            batches = [
                normalized_codes[index:index + 60]
                for index in range(0, len(normalized_codes), 60)
            ]
            # Sequential batches are intentional: five parallel requests to
            # Tencent often trigger disconnects or local socket protection.
            results: list[dict[str, dict] | Exception] = []
            for batch in batches:
                try:
                    results.append(await self._tencent_quotes(client, batch))
                except Exception as exc:
                    results.append(exc)
            quotes = {
                code: quote
                for result in results
                if not isinstance(result, Exception)
                for code, quote in result.items()
            }
            missing = [code for code in normalized_codes if code not in quotes]
            if missing and self.stock_skill_enabled:
                from src.infrastructure.market_data.stock_skill_bridge import (
                    fetch_tencent_quotes,
                )
                # Keep the fallback URL bounded as well.  A full-universe
                # metadata refresh can contain thousands of symbols; sending
                # them in one Tencent request risks URL limits and turns a
                # partial provider failure into a total metadata outage.
                for index in range(0, len(missing), 60):
                    fallback = await fetch_tencent_quotes(
                        missing[index:index + 60],
                        timeout_seconds=self.timeout_seconds,
                    )
                    quotes.update(fallback)
            # The batch Tencent endpoint occasionally returns a partial set
            # (or is locally blocked) even while the single-symbol provider
            # chain is healthy.  Execution must not stop at that partial
            # response: retry the small intraday candidate set through the
            # SourceManager's Tencent/TickFlow/Sina chain.  Tushare is
            # deliberately excluded here because its rt_min endpoint has a
            # strict daily request budget and is not needed for live quotes.
            missing = [code for code in normalized_codes if code not in quotes]
            if missing and len(normalized_codes) <= 30:
                from src.infrastructure.market_data.source_manager import (
                    source_manager,
                )

                semaphore = asyncio.Semaphore(4)

                async def fetch_one(code: str) -> tuple[str, dict | None]:
                    async with semaphore:
                        try:
                            quote, provenance = await source_manager.get_realtime_quote(
                                code,
                                excluded_providers={"tushare"},
                            )
                        except Exception:
                            return code, None
                        if not quote:
                            return code, None
                        normalized = dict(quote)
                        normalized["source"] = str(
                            normalized.get("source")
                            or getattr(provenance, "provider", "")
                            or ""
                        )
                        normalized["fetched_at"] = str(
                            normalized.get("fetched_at")
                            or getattr(provenance, "fetched_at", "")
                            or datetime.now(timezone.utc).isoformat()
                        )
                        normalized["exchange_timestamp"] = str(
                            normalized.get("exchange_timestamp")
                            or normalized.get("exchange_at")
                            or ""
                        )
                        normalized["data_date"] = str(
                            normalized.get("data_date")
                            or getattr(provenance, "data_date", "")
                            or ""
                        )
                        return normalize_a_share_code(code), normalized

                fallback_results = await asyncio.gather(
                    *(fetch_one(code) for code in missing)
                )
                for code, quote in fallback_results:
                    if quote:
                        quotes[code] = quote
            if not quotes and results:
                first_error = next(
                    (result for result in results if isinstance(result, Exception)),
                    None,
                )
                if first_error is not None:
                    raise first_error
            return quotes

    @staticmethod
    def _merge_source(merged: dict[str, dict], source: str, rows: list[dict]) -> None:
        for fallback_rank, row in enumerate(rows, start=1):
            code = normalize_a_share_code(row.get("code"))
            if not code:
                continue
            rank_value = row.get("rank")
            try:
                rank = int(float(rank_value)) if rank_value not in (None, "") else fallback_rank
            except (TypeError, ValueError):
                rank = fallback_rank
            item = merged.setdefault(
                code,
                {
                    "stock_code": code,
                    "stock_name": row.get("name") or "",
                    "sources": [],
                    "source_ranks": {},
                    "reasons": [],
                    "concepts": [],
                    "stock_skill": {},
                },
            )
            if source not in item["sources"]:
                item["sources"].append(source)
            item["source_ranks"][source] = rank
            if row.get("name") and not item.get("stock_name"):
                item["stock_name"] = row["name"]
            reason = str(row.get("reason") or "").strip()
            if reason and reason not in item["reasons"]:
                item["reasons"].append(reason)
            for concept in row.get("concepts") or []:
                text = str(concept).strip()
                if text and text not in item["concepts"]:
                    item["concepts"].append(text)
            if source == "ths_hot_reason":
                skill_fields = {
                    key: row.get(key)
                    for key in (
                        "change_pct", "price", "turnover_pct", "amount", "main_net"
                    )
                    if row.get(key) not in (None, "")
                }
                if skill_fields:
                    item["stock_skill"].update(skill_fields)

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        response.raise_for_status()
        try:
            return json.loads(_decode_text(response.content))
        except json.JSONDecodeError as exc:
            raise ValueError("response is not valid JSON") from exc

    async def _ths_hot_reason(self, client: httpx.AsyncClient, day: str) -> list[dict]:
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/date/{day}/"
            "orderby/date/orderway/desc/charset/GBK/"
        )
        data = self._decode_json(await self._request_with_retry(client, "GET", url))
        if not isinstance(data, dict) or data.get("errocode", 0) != 0:
            raise ValueError(f"THS strong-stock error: {(data or {}).get('errormsg', '')}")
        rows = []
        for rank, item in enumerate(data.get("data") or [], start=1):
            rows.append({
                "rank": rank,
                "code": item.get("code"),
                "name": item.get("name") or "",
                "reason": item.get("reason") or "",
            })
        return rows

    async def _ths_hot_list(self, client: httpx.AsyncClient) -> list[dict]:
        response = await self._request_with_retry(
            client,
            "GET",
            "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
            params={"stock_type": "a", "type": "day", "list_type": "normal"},
        )
        data = self._decode_json(response)
        stock_list = (
            ((data.get("data") or {}).get("stock_list") or [])
            if isinstance(data, dict)
            else []
        )
        rows = []
        for fallback_rank, item in enumerate(stock_list, start=1):
            tag = item.get("tag") or {}
            rows.append({
                "rank": item.get("order") or fallback_rank,
                "code": item.get("code"),
                "name": item.get("name") or "",
                "concepts": tag.get("concept_tag") or [],
            })
        return rows

    async def _eastmoney_hot_rank(
        self, client: httpx.AsyncClient, top: int
    ) -> list[dict]:
        response = await self._eastmoney_request(
            client,
            "POST",
            "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
            json_body={
                "appId": "appId01",
                "globalId": "786e4c21-70dc-435a-93bb-38",
                "marketType": "",
                "pageNo": 1,
                "pageSize": top,
            },
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://guba.eastmoney.com/",
                "Origin": "https://guba.eastmoney.com",
            },
        )
        data = self._decode_json(response)
        rows = []
        for fallback_rank, item in enumerate((data or {}).get("data") or [], start=1):
            rows.append({
                "rank": item.get("rk") or fallback_rank,
                "code": item.get("sc"),
                "name": "",
            })
        return rows

    async def _tencent_quotes(
        self, client: httpx.AsyncClient, codes: list[str]
    ) -> dict[str, dict]:
        symbols = []
        for code in codes:
            normalized = normalize_a_share_code(code)
            if normalized:
                plain, exchange = normalized.split(".")
                symbols.append(f"{'sh' if exchange == 'SH' else 'sz'}{plain}")
        if not symbols:
            return {}
        response = await self._request_with_retry(
            client,
            "GET",
            f"https://qt.gtimg.cn/q={','.join(symbols)}",
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        response.raise_for_status()
        text = _decode_text(response.content)
        result: dict[str, dict] = {}
        for line in text.splitlines():
            if '="' not in line:
                continue
            payload = line.split('="', 1)[1].rsplit('"', 1)[0]
            values = payload.split("~")
            if len(values) < 50:
                continue
            code = normalize_a_share_code(values[2])
            if not code:
                continue
            exchange_timestamp = values[30].strip() if len(values) > 30 else ""
            data_date = (
                f"{exchange_timestamp[:4]}-{exchange_timestamp[4:6]}-"
                f"{exchange_timestamp[6:8]}"
                if len(exchange_timestamp) >= 8 and exchange_timestamp[:8].isdigit()
                else ""
            )
            result[code] = {
                "name": values[1],
                "price": _as_float(values[3]),
                "prev_close": _as_float(values[4]),
                "change_amt": _as_float(values[31]),
                "change_pct": _as_float(values[32]),
                "high": _as_float(values[33]),
                "low": _as_float(values[34]),
                "amount_wan": _as_float(values[37]),
                "turnover_pct": _as_float(values[38]),
                "pe_ttm": _as_float(values[39]),
                "amplitude_pct": _as_float(values[43]),
                "market_cap_yi": _as_float(values[44]),
                "float_mcap_yi": _as_float(values[45]),
                "pb": _as_float(values[46]),
                "limit_up": _as_float(values[47]),
                "limit_down": _as_float(values[48]),
                "volume_ratio": _as_float(values[49]),
                "vol_ratio": _as_float(values[49]),
                "pe_static": _as_float(values[52]) if len(values) > 52 else 0.0,
                "outer_volume_lots": _as_float(values[7]),
                "inner_volume_lots": _as_float(values[8]),
                "source": "tencent_live_quote",
                "data_date": data_date,
                "exchange_timestamp": exchange_timestamp,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            outer = result[code]["outer_volume_lots"]
            inner = result[code]["inner_volume_lots"]
            result[code]["active_volume_ratio"] = (
                round((outer - inner) / (outer + inner), 6)
                if outer + inner > 0 else None
            )
        if not result:
            raise ValueError("Tencent returned no usable A-share quotes")
        return result

    async def _eastmoney_fund_flow(
        self, client: httpx.AsyncClient, code: str
    ) -> dict:
        normalized = normalize_a_share_code(code)
        plain, exchange = normalized.split(".")
        secid = f"{1 if exchange == 'SH' else 0}.{plain}"
        common_headers = {
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        rows: list[str] = []
        granularity = "intraday"
        transport = "python_http"
        response = await self._eastmoney_get(
            client,
            "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
            params={
                "secid": secid,
                "lmt": 0,
                "klt": 1,
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
            },
            headers=common_headers,
        )
        transport = str(
            response.extensions.get("adaptive_transport", "python_http")
        )
        data = self._decode_json(response)
        rows = ((data.get("data") or {}).get("klines") or []) if isinstance(data, dict) else []
        if not rows:
            # Only fall back after a valid empty intraday response. A transport
            # disconnect is propagated so it does not immediately double the
            # blocked host's traffic with a second endpoint request.
            granularity = "daily_5d_fallback"
            response = await self._eastmoney_get(
                client,
                "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                params={
                    "secid": secid,
                    "lmt": 5,
                    "klt": 101,
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                    "ut": "b2884a393a59ad64002292a3e90d46a5",
                },
                headers=common_headers,
            )
            transport = str(
                response.extensions.get("adaptive_transport", "python_http")
            )
            data = self._decode_json(response)
            rows = ((data.get("data") or {}).get("klines") or []) if isinstance(data, dict) else []
        main_values: list[float] = []
        for row in rows:
            parts = str(row).split(",")
            if len(parts) >= 2:
                main_values.append(_as_float(parts[1]))
        if not main_values:
            return {
                "status": "missing",
                "main_net": None,
                "row_count": 0,
                "attempted": True,
                "fallback_attempted": True,
                "fallback_status": "exhausted",
            }
        return {
            "status": "ok",
            "main_net": round(sum(main_values), 2),
            "latest_main_net": round(main_values[-1], 2),
            "row_count": len(main_values),
            "granularity": granularity,
            "source": (
                "eastmoney_intraday_fund_flow"
                if granularity == "intraday"
                else "eastmoney_daily_fund_flow"
            ),
            "transport": transport,
        }

    async def _eastmoney_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict,
        headers: dict,
    ) -> httpx.Response:
        return await self._eastmoney_request(
            client,
            "GET",
            url,
            params=params,
            headers=headers,
        )

    async def _eastmoney_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        json_body: object | None = None,
    ) -> httpx.Response:
        """Use one paced Eastmoney lane and stop promptly on rate control."""
        host = (urlparse(url).hostname or "").lower()
        if host != "eastmoney.com" and not host.endswith(".eastmoney.com"):
            raise ValueError(f"Eastmoney request refused untrusted host: {host}")
        async with self._eastmoney_lock:
            self._ensure_eastmoney_available()
            await self._pace_eastmoney_request()
            request = client.build_request(
                method,
                url,
                params=params,
                headers=headers,
                json=json_body,
            )
            try:
                try:
                    response = await client.send(request)
                    if response.status_code in {403, 429}:
                        reason = f"HTTP {response.status_code} from {host}"
                        retry_after = parse_retry_after(
                            response.headers.get("Retry-After"),
                            maximum_seconds=self.retry_after_max_seconds,
                        )
                        self._record_eastmoney_failure(
                            reason,
                            immediate=True,
                            retry_after_seconds=retry_after,
                        )
                        raise EastmoneyCircuitOpenError(
                            f"Eastmoney rate control detected ({reason}); "
                            f"cooldown {self.eastmoney_cooldown_seconds:.0f}s"
                        )
                    response.raise_for_status()
                    try:
                        json.loads(_decode_text(response.content))
                    except json.JSONDecodeError as exc:
                        reason = f"non-JSON response from {host}"
                        self._record_eastmoney_failure(reason, immediate=True)
                        raise EastmoneyCircuitOpenError(
                            "Eastmoney anti-bot or invalid payload detected; "
                            f"cooldown {self.eastmoney_cooldown_seconds:.0f}s"
                        ) from exc
                    self._record_eastmoney_success()
                    response.extensions["adaptive_transport"] = "python_http"
                    return response
                except EastmoneyCircuitOpenError:
                    raise
                except httpx.HTTPError as python_error:
                    # A second transport is useful only for the two trusted
                    # flow hosts. Pace it as another request; never retry an
                    # explicit 403/429 or an anti-bot HTML response.
                    if method.upper() != "GET" or host not in _CURL_EASTMONEY_HOSTS:
                        self._record_eastmoney_failure(str(python_error))
                        raise
                    await self._pace_eastmoney_request()
                    try:
                        raw = await asyncio.to_thread(
                            _curl_get_bytes,
                            str(request.url),
                            headers,
                            self.timeout_seconds,
                        )
                        json.loads(_decode_text(raw))
                    except Exception as curl_error:
                        message = (
                            f"Eastmoney transports failed: "
                            f"python={type(python_error).__name__}: {python_error}; "
                            f"curl={type(curl_error).__name__}: {curl_error}"
                        )
                        self._record_eastmoney_failure(message, immediate=True)
                        raise EastmoneyCircuitOpenError(
                            f"{message}; cooldown "
                            f"{self.eastmoney_cooldown_seconds:.0f}s"
                        ) from curl_error
                    self._record_eastmoney_success()
                    fallback = httpx.Response(200, content=raw, request=request)
                    fallback.extensions["adaptive_transport"] = "curl"
                    return fallback
            finally:
                pass

    async def _pace_eastmoney_request(self) -> None:
        try:
            wait = reserve_provider_request(
                "eastmoney",
                min_interval_seconds=self.eastmoney_min_interval_seconds,
                jitter_seconds=self.eastmoney_jitter_seconds,
            )
        except ProviderCircuitOpenError as exc:
            raise EastmoneyCircuitOpenError(str(exc).replace("eastmoney", "Eastmoney")) from exc
        if wait > 0:
            await asyncio.sleep(wait)

    def _ensure_eastmoney_available(self) -> None:
        try:
            ensure_provider_available("eastmoney")
        except ProviderCircuitOpenError as exc:
            raise EastmoneyCircuitOpenError(str(exc).replace("eastmoney", "Eastmoney")) from exc

    def _record_eastmoney_failure(
        self,
        reason: str,
        *,
        immediate: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        record_provider_failure(
            "eastmoney",
            reason,
            failure_threshold=self.eastmoney_failure_threshold,
            cooldown_seconds=self.eastmoney_cooldown_seconds,
            immediate=immediate,
            retry_after_seconds=retry_after_seconds,
        )

    def _record_eastmoney_success(self) -> None:
        record_provider_success("eastmoney")

    @staticmethod
    def _score_candidate(item: dict, quote: dict, flow: dict) -> dict:
        ranks = item.get("source_ranks") or {}
        heat_score = max((_source_rank_score(rank) for rank in ranks.values()), default=50.0)
        source_count = len(item.get("sources") or [])
        consensus_score = _clamp(50.0 + max(0, source_count - 1) * 25.0)
        change_pct = _as_float(quote.get("change_pct"))
        momentum_score = _clamp(50.0 + change_pct * 4.0)
        main_net = flow.get("main_net")
        amount_yuan = _as_float(quote.get("amount_wan")) * 10_000
        main_net_ratio = None
        if main_net is not None and amount_yuan > 0:
            main_net_ratio = float(main_net) / amount_yuan
            flow_score = _clamp(50.0 + main_net_ratio * 100.0)
        elif main_net is not None:
            flow_score = _clamp(50.0 + math.copysign(10.0, float(main_net)))
        else:
            active_ratio = quote.get("active_volume_ratio")
            if active_ratio is not None:
                flow = {
                    **flow,
                    "status": "proxy",
                    "flow_signal": float(active_ratio),
                    "active_volume_ratio": float(active_ratio),
                    "source": "tencent_active_volume_proxy",
                    "fallback_attempted": bool(
                        flow.get("fallback_attempted") or flow.get("attempted")
                    ),
                    "fallback_status": flow.get(
                        "fallback_status", "proxy_only"
                    ),
                    "note": "外盘/内盘主动成交差额代理，不等同于主力净流入",
                }
                flow_score = _clamp(50.0 + float(active_ratio) * 50.0)
            else:
                flow_score = 50.0
        discovery_score = round(
            0.45 * heat_score
            + 0.20 * consensus_score
            + 0.20 * momentum_score
            + 0.15 * flow_score,
            2,
        )
        return {
            **item,
            "stock_name": quote.get("name") or item.get("stock_name") or item["stock_code"],
            "discovery_score": discovery_score,
            "score_breakdown": {
                "heat": round(heat_score, 2),
                "source_consensus": round(consensus_score, 2),
                "momentum": round(momentum_score, 2),
                "fund_flow": round(flow_score, 2),
            },
            "quote": quote,
            "stock_skill": item.get("stock_skill") or {},
            "fund_flow": {**flow, "main_net_ratio": main_net_ratio},
            "data_sources": [*(item.get("sources") or []), quote.get("source")]
            + ([flow.get("source")] if flow.get("source") else []),
        }


remote_market_discovery = RemoteMarketDiscovery()
