from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.ai_os import task_executor as task_executor_module
from src.ai_os.pipeline_runner import pipeline_runner
from src.ai_os.scheduler import SchedulePhase, ScheduledTask
from src.ai_os.task_executor import (
    TaskExecutor,
    _TASK_TIMEOUT_SECONDS,
    local_market_cache_can_run_scanner,
)
from src.ai_os.trading_calendar import CompletedTradingDayStatus
from src.infrastructure.storage.market_database import (
    MarketDatabase,
    SyncResult,
    market_db,
)


def test_local_market_cache_requires_broad_history():
    assert local_market_cache_can_run_scanner(
        {"stocks": 6817, "daily_bars": 1_661_247}, "2026-08-14"
    )
    assert not local_market_cache_can_run_scanner(
        {"stocks": 10, "daily_bars": 100}, "2026-08-14"
    )
    assert not local_market_cache_can_run_scanner(
        {"stocks": 6817, "daily_bars": 10}, ""
    )


def test_daily_bar_sync_rejects_a_concurrent_baostock_session(tmp_path):
    database = MarketDatabase(tmp_path / "market.db")
    assert database._daily_sync_lock.acquire(blocking=False)
    try:
        result = database.sync_daily_bars(codes=[])
    finally:
        database._daily_sync_lock.release()

    assert result.stocks_updated == 0
    assert result.errors == ["baostock sync already in progress"]


@pytest.mark.asyncio
async def test_market_open_executes_persisted_plan_without_rescanning(monkeypatch):
    execute = AsyncMock(return_value={"status": "executed_persisted_plan"})
    scan = AsyncMock()
    monkeypatch.setattr(pipeline_runner, "execute_persisted_strategy", execute)
    monkeypatch.setattr(pipeline_runner, "run_daily_pipeline", scan)
    task = ScheduledTask(
        phase=SchedulePhase.MARKET_OPEN,
        name="execute_open_strategy",
        description="execute",
    )

    result = await TaskExecutor(persist=False)._route_task(task)

    assert result["status"] == "executed_persisted_plan"
    execute.assert_awaited_once_with()
    scan.assert_not_awaited()
    assert _TASK_TIMEOUT_SECONDS["execute_open_strategy"] == 180


@pytest.mark.asyncio
async def test_market_open_notifies_immediately_when_paper_trade_occurs(monkeypatch):
    execute = AsyncMock(return_value={
        "paper_trades": [{
            "action": "BUY", "stock_code": "600000.SH", "stock_name": "浦发银行",
            "shares": 200, "price": 10.1, "execution_tier": "probe",
        }],
        "paper_cash": 97975.0,
        "paper_execution": {"execution_at": "2026-09-10T09:35:01+08:00"},
    })
    executor = TaskExecutor(persist=False)
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline_runner, "execute_persisted_strategy", execute)
    monkeypatch.setattr(executor, "_notify_wechat", notify)

    result = await executor._execute_open_strategy(None)

    assert result["trade_notification_sent"] is True
    notify.assert_awaited_once()
    assert "BUY 浦发银行 200股" in notify.await_args.args[1]


@pytest.mark.asyncio
async def test_task_executor_blocks_duplicate_success_for_same_strategy_day(monkeypatch):
    executor = TaskExecutor(persist=False)
    route = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(executor, "_route_task", route)
    task = ScheduledTask(
        phase=SchedulePhase.WEEKLY,
        name="idempotency_probe",
        description="idempotency",
    )

    first = await executor.execute_task(task)
    second = await executor.execute_task(task)

    assert first.status.value == "success"
    assert second.status.value == "skipped"
    assert second.output["skip_reason"] == "idempotent_success"
    assert second.output["strategy_version"] == first.output["strategy_version"]
    route.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_market_data_unblocks_scanner_with_valid_local_cache(monkeypatch):
    monkeypatch.setattr(
        market_db,
        "get_stats",
        lambda: {"stocks": 6817, "daily_bars": 1_661_247,
                 "latest_data_date": "2026-08-14"},
    )
    monkeypatch.setattr(
        task_executor_module,
        "get_latest_completed_trading_day",
        lambda day: _completed_day(),
    )
    monkeypatch.setattr(
        market_db,
        "sync_daily_bars",
        lambda **kwargs: SyncResult(errors=["baostock login failed"]),
    )
    monkeypatch.setattr(
        TaskExecutor,
        "_sync_current_metadata",
        AsyncMock(return_value={"status": "partial", "market_cap_count": 0}),
    )

    result = await TaskExecutor(persist=False)._sync_market_data(None)

    assert result["status"] == "cache_fallback"
    assert result["usable_for_scanner"] is True
    assert result["degraded"] is True
    assert result["latest_data_date"] == "2026-08-14"
    assert "baostock login failed" in result["sync_errors"][0]
    assert result["metadata_sync"]["status"] == "partial"


async def _completed_day():
    return CompletedTradingDayStatus(
        day=date(2026, 8, 17),
        source="weekday_fallback",
        degraded=True,
        error="baostock unavailable",
    )
