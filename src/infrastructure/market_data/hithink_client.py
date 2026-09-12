"""Transport and resilience core for the HiThink Financial API."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from src.infrastructure.market_data.provider_metrics import reliability_engine
from src.infrastructure.market_data.provider_resilience import (
    ProviderCircuitOpenError,
    compute_retry_delay,
    ensure_provider_available,
    parse_retry_after,
    record_provider_failure,
    record_provider_success,
    reserve_provider_request,
)


class HiThinkError(RuntimeError):
    """A classified HiThink failure with no credential-bearing details."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        status_code: int | None = None,
        provider_code: int | str | None = None,
        request_id: str = "",
    ) -> None:
        self.category = category
        self.status_code = status_code
        self.provider_code = provider_code
        self.request_id = request_id
        safe = str(message).replace("X-api-key", "[REDACTED]")[:240]
        super().__init__(safe)


class HiThinkClient:
    """Shared async request lane, retry policy, metrics and circuit state."""

    provider_id = "hithink"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        retry_attempts: int | None = None,
        min_interval_seconds: float | None = None,
        failure_threshold: int | None = None,
        cooldown_seconds: float | None = None,
        client: Any = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("HITHINK_FINANCE_API_KEY", "")
        if api_key is None and not self.api_key:
            self.api_key = str(self._setting("HITHINK_FINANCE_API_KEY", "") or "")
        self.base_url = (base_url or str(self._setting("HITHINK_BASE_URL", "https://fuyao.aicubes.cn"))).rstrip("/")
        self.timeout_seconds = max(0.1, float(timeout_seconds or self._setting("HITHINK_TIMEOUT_SECONDS", 8.0)))
        self.retry_attempts = max(1, int(retry_attempts or self._setting("HITHINK_RETRY_ATTEMPTS", 2)))
        self.min_interval_seconds = max(0.0, float(min_interval_seconds or self._setting("HITHINK_MIN_INTERVAL_SECONDS", 0.25)))
        self.failure_threshold = max(1, int(failure_threshold or self._setting("HITHINK_FAILURE_THRESHOLD", 3)))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds or self._setting("HITHINK_COOLDOWN_SECONDS", 60.0)))
        self._client = client
        self._stats: dict[str, Any] = {
            "calls": 0, "successes": 0, "failures": 0,
            "total_latency_ms": 0.0, "by_capability": {},
            "recent_request_ids": [], "recent_errors": [],
        }

    @staticmethod
    def _setting(name: str, default: Any) -> Any:
        try:
            from config.settings import settings

            return getattr(settings, name, default)
        except Exception:
            return os.getenv(name, default)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def runtime_stats(self) -> dict[str, Any]:
        stats = dict(self._stats)
        stats["by_capability"] = {
            key: {
                **value,
                "avg_latency_ms": round(value["total_latency_ms"] / value["calls"], 2)
                if value["calls"] else 0.0,
            }
            for key, value in self._stats["by_capability"].items()
        }
        stats["recent_request_ids"] = list(self._stats["recent_request_ids"])
        stats["recent_errors"] = list(self._stats["recent_errors"])
        stats["avg_latency_ms"] = round(
            stats["total_latency_ms"] / stats["calls"], 2
        ) if stats["calls"] else 0.0
        stats.pop("total_latency_ms", None)
        for bucket in stats["by_capability"].values():
            bucket.pop("total_latency_ms", None)
        return stats

    def _record(
        self, capability: str, success: bool, latency_ms: float,
        error: HiThinkError | None = None,
    ) -> None:
        self._stats["calls"] += 1
        self._stats["total_latency_ms"] += latency_ms
        bucket = self._stats["by_capability"].setdefault(
            capability, {"calls": 0, "successes": 0, "failures": 0, "total_latency_ms": 0.0}
        )
        bucket["calls"] += 1
        bucket["total_latency_ms"] += latency_ms
        if success:
            self._stats["successes"] += 1
            bucket["successes"] += 1
        else:
            self._stats["failures"] += 1
            bucket["failures"] += 1
            if error:
                self._stats["recent_errors"] = [
                    *self._stats["recent_errors"],
                    {"category": error.category, "status_code": error.status_code, "provider_code": error.provider_code},
                ][-20:]
        reliability_engine.record_call(
            self.provider_id, capability, success, latency_ms,
            error_message=f"{error.category}:{error.provider_code}" if error else "",
        )

    async def _send(self, capability: str, path: str, params: dict[str, Any]) -> tuple[Any, str, float]:
        if not self.configured:
            error = HiThinkError("hithink_api_key_missing", category="not_configured")
            self._record(capability, False, 0.0, error)
            raise error
        try:
            ensure_provider_available(self.provider_id)
        except ProviderCircuitOpenError as exc:
            error = HiThinkError(str(exc), category="server")
            self._record(capability, False, 0.0, error)
            raise error from exc

        headers = {"X-api-key": self.api_key, "Accept": "application/json"}
        started = time.perf_counter()
        last_error: HiThinkError | None = None
        for attempt in range(1, self.retry_attempts + 1):
            retry_after: float | None = None
            try:
                wait = reserve_provider_request(
                    self.provider_id, min_interval_seconds=self.min_interval_seconds,
                    jitter_seconds=0.0,
                )
                if wait > 0:
                    await asyncio.sleep(wait)
                if self._client is not None:
                    response = await self._client.get(
                        f"{self.base_url}{path}", params=params, headers=headers,
                        timeout=self.timeout_seconds,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        response = await client.get(
                            f"{self.base_url}{path}", params=params, headers=headers
                        )
            except (httpx.TimeoutException, asyncio.TimeoutError):
                last_error = HiThinkError("request_timeout", category="timeout")
            except httpx.HTTPError:
                last_error = HiThinkError("request_network_error", category="network")
            else:
                request_id = str(response.headers.get("X-Request-ID", "") or "")[:120]
                status = response.status_code
                retry_after = parse_retry_after(
                    response.headers.get("Retry-After"), maximum_seconds=900
                )
                if status == 429:
                    last_error = HiThinkError("http_429", category="rate_limited", status_code=status, request_id=request_id)
                elif status == 401:
                    last_error = HiThinkError("http_401", category="authentication", status_code=status, request_id=request_id)
                elif status == 403:
                    last_error = HiThinkError("http_403", category="permission", status_code=status, request_id=request_id)
                elif status >= 500:
                    last_error = HiThinkError(f"http_{status}", category="server", status_code=status, request_id=request_id)
                elif status < 200 or status >= 300:
                    last_error = HiThinkError(f"http_{status}", category="validation", status_code=status, request_id=request_id)
                else:
                    try:
                        body = response.json()
                    except (ValueError, TypeError):
                        last_error = HiThinkError("invalid_json", category="parse_error", status_code=status, request_id=request_id)
                    else:
                        if not isinstance(body, dict):
                            last_error = HiThinkError("response_not_object", category="contract_error", status_code=status, request_id=request_id)
                        else:
                            request_id = str(body.get("request_id") or request_id)[:120]
                            code = body.get("code", -1)
                            if code != 0:
                                code_text = str(code)
                                category = (
                                    "rate_limited" if code in (4001, 429) else
                                    "validation" if code_text in {"1001", "1002", "1003", "1004"} else
                                    "permission" if code_text in {"401", "403", "4003"} else
                                    "server" if code_text.startswith("5") else "contract_error"
                                )
                                last_error = HiThinkError(
                                    str(body.get("message") or "business_error"), category=category,
                                    status_code=status, provider_code=code, request_id=request_id,
                                )
                            elif body.get("data") is None:
                                last_error = HiThinkError("data_null", category="empty", status_code=status, request_id=request_id)
                            else:
                                elapsed = (time.perf_counter() - started) * 1000
                                record_provider_success(self.provider_id)
                                self._record(capability, True, elapsed)
                                self._stats["recent_request_ids"] = [
                                    *self._stats["recent_request_ids"], request_id
                                ][-20:]
                                return body["data"], request_id, elapsed
            if last_error is None:
                last_error = HiThinkError("unknown_error", category="network")
            retryable = last_error.category in {"rate_limited", "server", "timeout", "network"}
            if not retryable or attempt >= self.retry_attempts:
                break
            if last_error.category == "rate_limited":
                record_provider_failure(
                    self.provider_id, str(last_error), failure_threshold=self.failure_threshold,
                    cooldown_seconds=self.cooldown_seconds, retry_after_seconds=retry_after,
                )
            delay = compute_retry_delay(
                attempt, base_seconds=0.4, jitter_seconds=0.1,
                maximum_seconds=8.0, retry_after_seconds=retry_after,
            )
            if delay > 0:
                await asyncio.sleep(delay)
        elapsed = (time.perf_counter() - started) * 1000
        record_provider_failure(
            self.provider_id, str(last_error), failure_threshold=self.failure_threshold,
            cooldown_seconds=self.cooldown_seconds,
            immediate=last_error.category in {"authentication", "permission"},
        )
        self._record(capability, False, elapsed, last_error)
        raise last_error
