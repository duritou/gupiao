import threading
from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.ai_os.scheduler import ScheduledTask, SchedulePhase
from src.ai_os.task_executor import TaskExecutor, TaskStatus, market_checkpoint_freshness
from src.infrastructure.storage.market_database import market_db


@pytest.mark.parametrize(
    ("data_date", "is_live", "expected"),
    [
        ("", False, "unavailable"),
        ("not-a-date", True, "invalid"),
        ("2026-09-08", True, "previous_close_only"),
        ("2026-09-09", False, "dated_snapshot_only"),
        ("2026-09-09", True, "today_live"),
        ("2026-09-10", True, "invalid"),
    ],
)
def test_market_checkpoint_freshness_is_explicit(data_date, is_live, expected):
    assert market_checkpoint_freshness(
        data_date,
        is_live,
        today=date(2026, 9, 9),
    ) == expected


@pytest.mark.asyncio
async def test_persisted_task_execution_runs_sqlite_write_off_event_loop(monkeypatch):
    executor = TaskExecutor(persist=False)
    executor._persist = True
    main_thread = threading.get_ident()
    execution_threads = []

    def save_execution(_payload):
        execution_threads.append(threading.get_ident())

    monkeypatch.setattr(market_db, "save_task_execution", save_execution)
    monkeypatch.setattr(
        executor,
        "_route_task",
        AsyncMock(return_value={"status": "ok"}),
    )

    result = await executor.execute_task(ScheduledTask(
        phase=SchedulePhase.WEEKLY,
        name="test_threaded_persistence",
        description="unit test",
    ))

    assert result.status is TaskStatus.SUCCESS
    assert execution_threads
    assert all(thread_id != main_thread for thread_id in execution_threads)


@pytest.mark.asyncio
async def test_failure_incident_persistence_runs_off_event_loop(monkeypatch):
    executor = TaskExecutor(persist=False)
    executor._persist = True
    main_thread = threading.get_ident()
    execution_threads = []
    incident_threads = []

    monkeypatch.setattr(
        market_db,
        "save_task_execution",
        lambda _payload: execution_threads.append(threading.get_ident()),
    )
    monkeypatch.setattr(
        market_db,
        "save_task_failure_incident",
        lambda _payload: incident_threads.append(threading.get_ident()),
    )
    monkeypatch.setattr(
        executor,
        "_route_task",
        AsyncMock(side_effect=RuntimeError("controlled failure")),
    )

    result = await executor.execute_task(ScheduledTask(
        phase=SchedulePhase.WEEKLY,
        name="test_threaded_failure_persistence",
        description="unit test",
    ))

    assert result.status is TaskStatus.FAILED
    assert execution_threads
    assert incident_threads
    assert all(thread_id != main_thread for thread_id in execution_threads)
    assert all(thread_id != main_thread for thread_id in incident_threads)
