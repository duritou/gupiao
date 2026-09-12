from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.ai_os import hithink_canary


@pytest.mark.asyncio
async def test_canary_runner_skips_without_credentials():
    runner = hithink_canary.HiThinkCanaryRunner(SimpleNamespace(configured=False))

    result = await runner.run("09:35")

    assert result["status"] == "not_configured"
    assert result["checkpoint"] == "09:35"


@pytest.mark.asyncio
async def test_canary_runner_serializes_and_redacts_failures(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def fake_probe(code, capabilities, *, provider):
        calls.append((code, capabilities, provider))
        started.set()
        await release.wait()
        return {
            "status": "completed",
            "checked_at": "2026-09-12T09:35:00+08:00",
            "capability_count": 4,
            "supported_count": 3,
            "results": [{"status": "failed"}],
        }

    monkeypatch.setattr(hithink_canary, "run_probe", fake_probe)
    runner = hithink_canary.HiThinkCanaryRunner(SimpleNamespace(configured=True))
    first = asyncio.create_task(runner.run("09:35"))
    await started.wait()
    second = await runner.run("11:30")
    release.set()
    first_result = await first

    assert second["status"] == "skipped"
    assert first_result["status"] == "completed"
    assert first_result["failed_count"] == 1
    assert len(calls) == 1
    assert "payload" not in str(first_result).lower()


@pytest.mark.asyncio
async def test_canary_runner_contains_only_error_type(monkeypatch):
    class ClassifiedError(RuntimeError):
        category = "rate_limited"

    async def failed_probe(*args, **kwargs):
        raise ClassifiedError("secret response body")

    monkeypatch.setattr(hithink_canary, "run_probe", failed_probe)
    runner = hithink_canary.HiThinkCanaryRunner(SimpleNamespace(configured=True))

    result = await runner.run("15:10")

    assert result["status"] == "failed"
    assert result["error_type"] == "rate_limited"
    assert "secret response body" not in str(result)


def test_configured_canary_codes_normalizes_and_bounds():
    result = hithink_canary.configured_canary_codes(
        "600519,000001.SZ,not-a-code,600519.SH"
    )

    assert result == ("600519.SH", "000001.SZ")


@pytest.mark.asyncio
async def test_canary_matrix_is_sequential_and_aggregated(monkeypatch):
    calls = []

    async def fake_probe(code, capabilities, *, provider):
        calls.append((code, capabilities, provider))
        return {
            "status": "completed",
            "capability_count": 4,
            "supported_count": 3,
            "results": [{"status": "failed"}],
        }

    monkeypatch.setattr(hithink_canary, "run_probe", fake_probe)
    provider = SimpleNamespace(configured=True)
    runner = hithink_canary.HiThinkCanaryRunner(provider)

    result = await runner.run_matrix("09:35", ["600519.SH", "000001.SZ"])

    assert result["status"] == "completed"
    assert result["code_count"] == 2
    assert result["capability_count"] == 8
    assert result["supported_count"] == 6
    assert result["failed_count"] == 2
    assert [item[0] for item in calls] == ["600519.SH", "000001.SZ"]
    assert "payload" not in str(result).lower()
