from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.market_data.provider_resilience import (
    ProviderCircuitOpenError,
    compute_retry_delay,
    parse_retry_after,
    record_provider_failure,
    reserve_provider_request,
    reset_provider_resilience_state,
)


@pytest.fixture(autouse=True)
def _reset_provider_state():
    reset_provider_resilience_state()
    yield
    reset_provider_resilience_state()


def test_retry_after_accepts_seconds_and_http_date():
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    retry_at = now + timedelta(seconds=45)

    assert parse_retry_after("30", now=now) == 30.0
    assert parse_retry_after(retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT"), now=now) == 45.0
    assert parse_retry_after("not-a-date", now=now) is None


def test_retry_delay_uses_exponential_jitter_and_honours_retry_after(monkeypatch):
    monkeypatch.setattr(
        "src.infrastructure.market_data.provider_resilience.random.uniform",
        lambda low, high: high,
    )

    assert compute_retry_delay(2, base_seconds=0.5, jitter_seconds=0.25) == 1.25
    assert compute_retry_delay(
        2,
        base_seconds=0.5,
        jitter_seconds=0.25,
        retry_after_seconds=4.0,
    ) == 4.0


def test_provider_circuit_is_shared_by_host():
    record_provider_failure(
        "push2.eastmoney.com",
        "HTTP 429",
        failure_threshold=2,
        cooldown_seconds=60,
        immediate=True,
    )

    with pytest.raises(ProviderCircuitOpenError, match="cooldown active"):
        reserve_provider_request(
            "push2.eastmoney.com",
            min_interval_seconds=1.0,
            jitter_seconds=0.0,
        )
