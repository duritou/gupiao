"""The daily scheduled job must keep its exit-code contract.

`QuantAI_DailyVerify` runs scripts/auto_daily_verify.bat every morning, which
runs this script and alarms on a non-zero exit.  The informational probes may
grow, but the return codes may not drift: 0 when a live quote was obtained
(with or without iFind), 1 when none was, 2 when iFind was required and absent.

The kline probe was folded in from the older root-level script this replaced.
It reports and does not vote, precisely so that adding it could not change when
the job alarms.
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


def _quote(price: float):
    return SimpleNamespace(price=price)


@pytest.fixture()
def trading_day(monkeypatch):
    async def status():
        return SimpleNamespace(is_trading_day=True, source="test-fixture")

    monkeypatch.setattr(verify_module, "get_trading_day_status", status)


def _install(monkeypatch, *, ifind_quote, fallback, kline):
    monkeypatch.setattr(verify_module.ifind, "get_quote", lambda code: ifind_quote)
    monkeypatch.setattr(verify_module.ifind, "get_kline", lambda code, count=3: kline)

    async def get_realtime_quote(code):
        return fallback

    monkeypatch.setattr(
        verify_module.source_manager, "get_realtime_quote", get_realtime_quote
    )


def test_a_fallback_quote_passes_even_when_ifind_is_down(monkeypatch, trading_day):
    _install(
        monkeypatch,
        ifind_quote=None,
        fallback=({"price": 10.0}, SimpleNamespace(provider="tickflow", is_live=True, error_message="")),
        kline=None,
    )

    assert asyncio.run(verify_module.verify("600000.SH", require_ifind=False)) == 0


def test_no_quote_at_all_fails(monkeypatch, trading_day):
    _install(
        monkeypatch,
        ifind_quote=None,
        fallback=(None, SimpleNamespace(provider="", is_live=False, error_message="down")),
        kline=None,
    )

    assert asyncio.run(verify_module.verify("600000.SH", require_ifind=False)) == 1


def test_requiring_ifind_fails_when_it_is_absent(monkeypatch, trading_day):
    _install(
        monkeypatch,
        ifind_quote=None,
        fallback=({"price": 10.0}, SimpleNamespace(provider="tickflow", is_live=True, error_message="")),
        kline=None,
    )

    assert asyncio.run(verify_module.verify("600000.SH", require_ifind=True)) == 2


def test_the_kline_probe_does_not_change_the_exit_code(monkeypatch, trading_day, capsys):
    # iFind is currently unavailable in production, so this probe prints
    # "no data" every morning.  That must stay informational.
    _install(
        monkeypatch,
        ifind_quote=None,
        fallback=({"price": 10.0}, SimpleNamespace(provider="tickflow", is_live=True, error_message="")),
        kline=None,
    )

    code = asyncio.run(verify_module.verify("600000.SH", require_ifind=False))

    assert code == 0
    assert "ifind-kline: no data" in capsys.readouterr().out


def test_the_kline_probe_reports_the_latest_bar(monkeypatch, trading_day, capsys):
    _install(
        monkeypatch,
        ifind_quote=_quote(10.0),
        fallback=({"price": 10.0}, SimpleNamespace(provider="ifind", is_live=True, error_message="")),
        kline=[{"date": "2026-09-18", "close": 9.5}, {"date": "2026-09-19", "close": 9.8}],
    )

    code = asyncio.run(verify_module.verify("600000.SH", require_ifind=False))

    assert code == 0
    out = capsys.readouterr().out
    assert "ifind-kline: OK 2 bars" in out
    assert "2026-09-19" in out


def test_a_non_trading_day_skips_before_probing(monkeypatch, capsys):
    async def status():
        return SimpleNamespace(is_trading_day=False, source="test-fixture")

    monkeypatch.setattr(verify_module, "get_trading_day_status", status)
    monkeypatch.setattr(
        verify_module.ifind, "get_quote",
        lambda code: pytest.fail("must not probe on a non-trading day"),
    )

    assert asyncio.run(verify_module.verify("600000.SH", require_ifind=True)) == 0
    assert "non-trading day" in capsys.readouterr().out
