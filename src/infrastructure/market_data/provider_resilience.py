"""Process-wide resilience primitives for public market-data providers.

The controller deliberately throttles request starts instead of trying to
evade provider controls.  State is shared by host so API routes, scheduled
jobs, and fallback transports cannot independently create retry storms.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class ProviderCircuitOpenError(RuntimeError):
    """Raised when a provider is cooling down after repeated failures."""


@dataclass
class _ProviderState:
    next_request_at: float = 0.0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    cooldown_reason: str = ""


_STATE_LOCK = threading.RLock()
_PROVIDER_STATES: dict[str, _ProviderState] = {}


def _provider_key(provider: str) -> str:
    return str(provider or "unknown").strip().lower()


def reset_provider_resilience_state() -> None:
    """Clear process-local state; primarily useful for deterministic tests."""
    with _STATE_LOCK:
        _PROVIDER_STATES.clear()


def ensure_provider_available(provider: str) -> None:
    key = _provider_key(provider)
    now = time.monotonic()
    with _STATE_LOCK:
        state = _PROVIDER_STATES.setdefault(key, _ProviderState())
        remaining = state.cooldown_until - now
        if remaining > 0:
            raise ProviderCircuitOpenError(
                f"{key} cooldown active for {remaining:.0f}s: "
                f"{state.cooldown_reason or 'recent provider failure'}"
            )
        if state.cooldown_until:
            state.cooldown_until = 0.0
            state.consecutive_failures = 0
            state.cooldown_reason = ""


def reserve_provider_request(
    provider: str,
    *,
    min_interval_seconds: float,
    jitter_seconds: float,
) -> float:
    """Reserve a process-wide request start and return required wait seconds."""
    key = _provider_key(provider)
    now = time.monotonic()
    with _STATE_LOCK:
        ensure_provider_available(key)
        state = _PROVIDER_STATES.setdefault(key, _ProviderState())
        wait = max(0.0, state.next_request_at - now)
        interval = max(0.0, float(min_interval_seconds))
        jitter = random.uniform(0.0, max(0.0, float(jitter_seconds)))
        state.next_request_at = now + wait + interval + jitter
        return wait


def record_provider_failure(
    provider: str,
    reason: str,
    *,
    failure_threshold: int,
    cooldown_seconds: float,
    immediate: bool = False,
    retry_after_seconds: float | None = None,
) -> None:
    key = _provider_key(provider)
    now = time.monotonic()
    with _STATE_LOCK:
        state = _PROVIDER_STATES.setdefault(key, _ProviderState())
        state.consecutive_failures += 1
        if immediate or state.consecutive_failures >= max(1, int(failure_threshold)):
            cooldown = max(0.0, float(cooldown_seconds))
            if retry_after_seconds is not None:
                cooldown = max(cooldown, max(0.0, float(retry_after_seconds)))
            state.cooldown_until = max(state.cooldown_until, now + cooldown)
            state.cooldown_reason = str(reason)[:240]


def record_provider_success(provider: str) -> None:
    key = _provider_key(provider)
    now = time.monotonic()
    with _STATE_LOCK:
        state = _PROVIDER_STATES.setdefault(key, _ProviderState())
        # Do not let an older in-flight success erase a newer 429 cooldown.
        if state.cooldown_until > now:
            return
        state.consecutive_failures = 0
        state.cooldown_reason = ""


def parse_retry_after(
    value: str | None,
    *,
    now: datetime | None = None,
    maximum_seconds: float = 3600.0,
) -> float | None:
    """Parse RFC 9110 Retry-After seconds or HTTP-date with a safety cap."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.isdigit():
            seconds = float(int(text))
        else:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            seconds = max(0.0, (retry_at - current).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
    return min(max(0.0, seconds), max(0.0, float(maximum_seconds)))


def compute_retry_delay(
    attempt: int,
    *,
    base_seconds: float,
    jitter_seconds: float,
    maximum_seconds: float = 30.0,
    retry_after_seconds: float | None = None,
) -> float:
    """Return capped exponential backoff plus jitter, respecting Retry-After."""
    exponent = max(0, int(attempt) - 1)
    backoff = max(0.0, float(base_seconds)) * (2**exponent)
    backoff += random.uniform(0.0, max(0.0, float(jitter_seconds)))
    delay = min(max(0.0, float(maximum_seconds)), backoff)
    if retry_after_seconds is not None:
        delay = max(delay, max(0.0, float(retry_after_seconds)))
    return delay
