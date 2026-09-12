from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.ai_os.task_executor import TaskExecutor


@pytest.mark.asyncio
async def test_intraday_monitor_is_quiet_outside_session(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(TaskExecutor, "_execute_open_strategy", execute)

    result = await TaskExecutor().monitor_intraday_paper_opportunities(
        datetime.fromisoformat("2026-09-11T09:29:00+08:00")
    )

    assert result == {
        "status": "outside_continuous_session",
        "paper_trades": [],
    }
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_intraday_monitor_reuses_persisted_execution_path(monkeypatch):
    execute = AsyncMock(return_value={"status": "executed", "paper_trades": []})
    monkeypatch.setattr(TaskExecutor, "_execute_open_strategy", execute)

    result = await TaskExecutor().monitor_intraday_paper_opportunities(
        datetime.fromisoformat("2026-09-11T09:31:00+08:00")
    )

    assert result["status"] == "executed"
    task = execute.await_args.args[0]
    assert task.name == "intraday_paper_monitor"
