from unittest.mock import AsyncMock

import pytest

from src.ai_os.scheduler import ScheduledTask, SchedulePhase
from src.ai_os.task_executor import TaskExecutor, TaskStatus


@pytest.mark.asyncio
async def test_explicit_rerun_keeps_original_and_deduplicates_request(monkeypatch):
    executor = TaskExecutor(persist=False)
    task = ScheduledTask(
        name="execute_open_strategy", phase=SchedulePhase.WEEKLY, description="test"
    )
    route = AsyncMock(return_value={"paper_trades": [], "reason": "outside_market_session"})
    monkeypatch.setattr(executor, "_route_task", route)
    original = await executor.execute_task(task)
    ordinary = await executor.execute_task(task)
    rerun = await executor.rerun_open_strategy(task, "approved-001")
    repeated = await executor.rerun_open_strategy(task, "approved-001")
    assert original.status == rerun.status == TaskStatus.SUCCESS
    assert ordinary.output["skip_reason"] == "idempotent_success"
    assert repeated.output["skip_reason"] == "rerun_already_recorded"
    assert route.await_count == 2
    assert original.output["execution_key"] != rerun.output["execution_key"]
    assert rerun.output["paper_trades"] == []


@pytest.mark.asyncio
async def test_rerun_does_not_allow_other_tasks():
    executor = TaskExecutor(persist=False)
    task = ScheduledTask(name="run_scanner", phase=SchedulePhase.WEEKLY, description="test")
    with pytest.raises(ValueError):
        await executor.rerun_open_strategy(task, "approved-001")
