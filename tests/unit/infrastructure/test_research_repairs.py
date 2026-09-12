from types import SimpleNamespace

import pandas as pd
import pytest

from src.infrastructure.market_data.research_flow import aggregate_flow
from src.infrastructure.market_data.tushare_provider import TushareProvider
from src.ai_os.execution_policy import evaluate_entry_execution


@pytest.mark.asyncio
async def test_financial_history_pages_past_revisions(monkeypatch):
    provider = TushareProvider()
    periods = ['20260630', '20260331', '20251231', '20250930',
               '20250630', '20250331', '20241231', '20240930']
    rows = [dict(end_date=p, ann_date='20260830', report_type='1')
            for p in periods for _ in range(8)]
    calls = []

    async def fetch(endpoint, **kwargs):
        calls.append((endpoint, kwargs['offset']))
        start = kwargs['offset']
        return SimpleNamespace(data=pd.DataFrame(rows[start:start + kwargs['limit']]))

    monkeypatch.setattr(provider, '_call', fetch)
    result = await provider.fetch_financial_history('300523.SZ', 8)
    assert all(n == 8 for n in result.data['period_counts'].values())
    assert ('cashflow', 32) in calls


def test_flow_window_rejects_stale_duplicate_and_nonfinite():
    rows = [{'trade_date': '2026-09-04', 'main_net': 0},
            {'trade_date': '2026-09-03', 'main_net': -1}]
    assert aggregate_flow(rows, 2, '2026-09-04')['main_net'] == -1
    for bad, expected in [(rows, '2026-09-07'), ([rows[0]] * 2, '2026-09-04'),
                          ([{**rows[0], 'main_net': float('nan')}, rows[1]], '2026-09-04')]:
        with pytest.raises(ValueError):
            aggregate_flow(bad, 2, expected)


@pytest.mark.asyncio
async def test_weekend_research_day_uses_completed_exchange_day(monkeypatch):
    from datetime import date, datetime
    from src.infrastructure.market_data import research_flow
    from src.ai_os import trading_calendar

    class Saturday(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 5, 14, tzinfo=tz)

    async def calendar(cutoff):
        assert cutoff == date(2026, 9, 5)
        return SimpleNamespace(day=date(2026, 9, 4), degraded=False)

    monkeypatch.setattr(research_flow, 'datetime', Saturday)
    monkeypatch.setattr(trading_calendar, 'get_latest_completed_trading_day', calendar)
    result = await research_flow.completed_research_day()
    assert result.day == date(2026, 9, 4)
    assert not result.degraded


@pytest.mark.asyncio
async def test_current_cached_flow_does_not_request_provider(monkeypatch):
    from datetime import date
    from src.infrastructure.market_data import research_flow
    from src.infrastructure.storage import market_database

    async def calendar():
        return SimpleNamespace(day=date(2026, 9, 4), degraded=False)

    monkeypatch.setattr(research_flow, 'completed_research_day', calendar)
    monkeypatch.setattr(market_database, 'market_db', SimpleNamespace(
        get_fund_flow_history=lambda code, days: [
            {'trade_date': '2026-09-04', 'main_net': 100}]))
    result = await research_flow.get_research_flow('002949.SZ', 1)
    assert result['endpoint'] == 'local.fund_flow_history'
    assert result['is_cached'] is True
    assert result['is_realtime'] is False


def test_confirmed_probe_is_paper_only_and_cannot_bypass_veto():
    decision = dict(direction='neutral', pre_gate_direction='buy', flow_status='positive',
                    action_score=68, technical_score=60, deep_analysis_available=True,
                    deep_rating='Overweight', final_review_available=True,
                    final_buy_approved=True, final_review_verdict='approve',
                    execution_evidence_complete=True)
    assert evaluate_entry_execution(decision)['tier'] == 'blocked'
    assert evaluate_entry_execution(decision, paper_mode=True)['tier'] == 'probe'
    assert evaluate_entry_execution(decision, paper_mode=True, allow_probe=False)['tier'] == 'blocked'
    for patch in [dict(flow_status='negative'), dict(deep_rating='Hold'),
                  dict(final_buy_approved=False), dict(final_review_verdict='veto'),
                  dict(execution_evidence_complete=False), dict(action_score=float('nan')),
                  dict(gate_reasons=['fundamental_loss_risk'])]:
        assert evaluate_entry_execution({**decision, **patch}, paper_mode=True)['tier'] == 'blocked'
