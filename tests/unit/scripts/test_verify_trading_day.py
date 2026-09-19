"""The daily scheduled job must keep its exit-code contract.

`QuantAI_DailyVerify` runs scripts/auto_daily_verify.bat every morning, which
runs this script and alarms on a non-zero exit.  The informational probes may
grow, but the return codes may not drift: 0 when a live quote was obtained, 1
when none was.

The script no longer names a provider.  iFind was removed from the chain on
2026-09-19 when its account expired, and the chain itself is ranked by observed
reliability -- asserting a winner here would create a second place for that
ranking to go stale.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.verify_trading_day as verify_module  # noqa: E402


def _provenance(provider: str, error: str = ""):
    return SimpleNamespace(provider=provider, is_live=True, error_message=error)


@pytest.fixture()
def trading_day(monkeypatch):
    async def status():
        return SimpleNamespace(is_trading_day=True, source="test-fixture")

    monkeypatch.setattr(verify_module, "get_trading_day_status", status)


def _install(monkeypatch, *, quote, klines):
    async def get_realtime_quote(code):
        return quote

    async def get_kline(code, count=250, adjustment_mode=None):
        return klines

    monkeypatch.setattr(verify_module.source_manager, "get_realtime_quote", get_realtime_quote)
    monkeypatch.setattr(verify_module.source_manager, "get_kline", get_kline)


def test_a_live_quote_passes(monkeypatch, trading_day):
    _install(
        monkeypatch,
        quote=({"price": 10.0}, _provenance("tickflow")),
        klines=([], _provenance("tushare", "no bars")),
    )

    assert asyncio.run(verify_module.verify("600000.SH")) == 0


def test_no_quote_at_all_fails(monkeypatch, trading_day):
    _install(
        monkeypatch,
        quote=(None, _provenance("", "all providers failed")),
        klines=([], _provenance("", "none")),
    )

    assert asyncio.run(verify_module.verify("600000.SH")) == 1


def test_the_kline_probe_does_not_change_the_exit_code(monkeypatch, trading_day, capsys):
    _install(
        monkeypatch,
        quote=({"price": 10.0}, _provenance("tickflow")),
        klines=([], _provenance("tushare", "no bars")),
    )

    code = asyncio.run(verify_module.verify("600000.SH"))

    assert code == 0
    assert "market-data-kline: no data" in capsys.readouterr().out


def test_the_kline_probe_reports_the_latest_bar(monkeypatch, trading_day, capsys):
    _install(
        monkeypatch,
        quote=({"price": 10.0}, _provenance("tickflow")),
        klines=(
            [{"date": "2026-09-18", "close": 9.5}, {"date": "2026-09-19", "close": 9.8}],
            _provenance("tushare"),
        ),
    )

    code = asyncio.run(verify_module.verify("600000.SH"))

    assert code == 0
    out = capsys.readouterr().out
    assert "2 bars" in out and "2026-09-19" in out
    assert "provider=tushare" in out


def test_the_provider_is_reported_not_asserted(monkeypatch, trading_day, capsys):
    # Whichever provider wins the dynamic ranking, the script reports it.
    _install(
        monkeypatch,
        quote=({"price": 10.0}, _provenance("some-other-provider")),
        klines=([], _provenance("x", "none")),
    )

    asyncio.run(verify_module.verify("600000.SH"))

    assert "provider=some-other-provider" in capsys.readouterr().out


def test_a_non_trading_day_skips_before_probing(monkeypatch, capsys):
    async def status():
        return SimpleNamespace(is_trading_day=False, source="test-fixture")

    monkeypatch.setattr(verify_module, "get_trading_day_status", status)
    monkeypatch.setattr(
        verify_module.source_manager, "get_realtime_quote",
        lambda code: pytest.fail("must not probe on a non-trading day"),
    )

    assert asyncio.run(verify_module.verify("600000.SH")) == 0
    assert "non-trading day" in capsys.readouterr().out
