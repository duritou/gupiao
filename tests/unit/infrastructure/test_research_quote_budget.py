import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.infrastructure.market_data.source_manager as source_manager_module
from src.infrastructure.market_data.source_manager import DataProvenance, SourceManager


@pytest.mark.asyncio
async def test_timeout_keeps_budget_for_retry_and_fallback():
    manager = SimpleNamespace(
        _try_tushare_quote=AsyncMock(side_effect=TimeoutError),
        get_realtime_quote=AsyncMock(return_value=(
            {'price': 10}, DataProvenance(provider='tencent'))),
    )
    quote, provenance = await SourceManager._bounded_research_quote(manager, '300792.SZ')
    assert quote['price'] == 10
    assert manager._try_tushare_quote.await_count == 2
    assert manager.get_realtime_quote.await_count == 1
    assert 'tushare_primary:TimeoutError' in provenance.fallback_reason
    assert 'tushare_retry:TimeoutError' in provenance.fallback_reason


@pytest.mark.asyncio
async def test_successful_retry_stops_fallback():
    manager = SimpleNamespace(
        _try_tushare_quote=AsyncMock(side_effect=[
            (None, DataProvenance(provider='tushare', error_message='empty')),
            ({'price': 10}, DataProvenance(provider='tushare'))]),
        get_realtime_quote=AsyncMock(),
    )
    quote, provenance = await SourceManager._bounded_research_quote(manager, '300792.SZ')
    assert quote['price'] == 10
    assert provenance.fallback_reason == 'tushare_primary:empty'
    manager.get_realtime_quote.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhaustion_keeps_all_attempt_errors():
    failed = (None, DataProvenance(provider='tushare', error_message='unavailable'))
    manager = SimpleNamespace(_try_tushare_quote=AsyncMock(return_value=failed),
                              get_realtime_quote=AsyncMock(return_value=failed))
    quote, provenance = await SourceManager._bounded_research_quote(manager, '300792.SZ')
    assert quote is None
    assert all(label in provenance.error_message
               for label in ('tushare_primary:', 'tushare_retry:', 'fallback:'))
    assert 'tushare_fallback:skipped_already_attempted' in provenance.error_message


@pytest.mark.asyncio
async def test_real_timeout_does_not_overlap_a_new_tushare_request(monkeypatch):
    monkeypatch.setattr(
        source_manager_module,
        'RESEARCH_QUOTE_ATTEMPT_TIMEOUT_SECONDS',
        0.05,
    )
    active = 0
    peak = 0
    events = []

    async def slow_primary(code):
        nonlocal active, peak
        events.append('primary')
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.15)
        active -= 1
        return None, DataProvenance(provider='tushare', error_message='slow_timeout')

    async def fallback(code, **kwargs):
        events.append('fallback')
        return {'price': 10}, DataProvenance(provider='fallback')

    manager = SimpleNamespace(
        _try_tushare_quote=slow_primary,
        get_realtime_quote=fallback,
    )
    quote, provenance = await SourceManager._bounded_research_quote(manager, '300792.SZ')
    await asyncio.sleep(0.2)

    assert quote['price'] == 10
    assert events == ['primary', 'fallback']
    assert peak == 1
    assert 'tushare_retry:skipped_inflight' in provenance.fallback_reason


@pytest.mark.asyncio
async def test_threaded_timeout_does_not_reenter_tushare_via_fallback(monkeypatch):
    monkeypatch.setattr(
        source_manager_module,
        'RESEARCH_QUOTE_ATTEMPT_TIMEOUT_SECONDS',
        0.05,
    )
    manager = SourceManager()
    manager.cache.clear()
    calls = 0
    active = 0
    peak = 0

    def blocking_provider():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        import time
        time.sleep(0.15)
        active -= 1
        return None, DataProvenance(provider='tushare', error_message='slow')

    async def tushare(code):
        nonlocal calls
        calls += 1
        return await asyncio.to_thread(blocking_provider)

    monkeypatch.setattr(manager, '_try_tushare_quote', tushare)
    monkeypatch.setattr(manager, '_get_ranked_providers', lambda code, capability: [])

    quote, provenance = await SourceManager._bounded_research_quote(
        manager, '300792.SZ'
    )
    await asyncio.sleep(0.2)

    assert quote is None
    assert calls == 1
    assert peak == 1
    assert 'tushare_retry:skipped_inflight' in provenance.error_message
    assert not manager._research_quote_tasks


@pytest.mark.asyncio
async def test_timed_out_fallback_does_not_continue_provider_chain(monkeypatch):
    monkeypatch.setattr(
        source_manager_module,
        'RESEARCH_QUOTE_ATTEMPT_TIMEOUT_SECONDS',
        0.05,
    )
    manager = SourceManager()
    events = []
    failed = (None, DataProvenance(provider='tushare', error_message='failed'))

    async def slow_fallback(provider, code):
        events.append('start')
        await asyncio.sleep(0.15)
        events.append('after_wait')
        return None, DataProvenance(provider=provider, error_message='slow')

    monkeypatch.setattr(manager, '_try_tushare_quote', AsyncMock(return_value=failed))
    monkeypatch.setattr(
        manager,
        '_get_ranked_providers',
        lambda code, capability: ['slow_provider'],
    )
    monkeypatch.setattr(manager, '_dispatch_quote', slow_fallback)

    quote, provenance = await SourceManager._bounded_research_quote(
        manager, '300792.SZ'
    )
    await asyncio.sleep(0.2)

    assert quote is None
    assert events == ['start']
    assert 'fallback:TimeoutError' in provenance.error_message
    assert not manager._research_quote_tasks


@pytest.mark.asyncio
async def test_excluded_provider_is_not_called_by_realtime_fallback(monkeypatch):
    manager = SourceManager()
    manager.cache.clear()
    manager.cache.set(
        'spot:quote:300792.SZ',
        {'price': 10, 'source': 'tushare', 'is_realtime': False},
    )
    tushare = AsyncMock(return_value=(
        None, DataProvenance(provider='tushare', error_message='must_not_call')
    ))
    monkeypatch.setattr(manager, '_try_tushare_quote', tushare)
    monkeypatch.setattr(manager, '_get_ranked_providers', lambda code, capability: [])

    quote, provenance = await manager.get_realtime_quote(
        '300792.SZ', excluded_providers={'tushare'}
    )

    assert quote is None
    assert provenance.provider == 'none'
    tushare.assert_not_awaited()
