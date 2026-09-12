from datetime import datetime, timedelta

import pytest

from src.api.routes import task_monitor_routes


@pytest.mark.asyncio
async def test_failures_surface_scanner_root_cause_without_dependency_noise(monkeypatch):
    now = datetime.now().isoformat()
    old = (datetime.now() - timedelta(hours=2)).isoformat()
    executions = [
        {
            "task_name": "generate_morning_brief",
            "status": "skipped",
            "error": "依赖未完成: run_scanner",
            "completed_at": now,
        },
        {
            "task_name": "run_scanner",
            "status": "failed",
            "error": "AttributeError: missing setting",
            "completed_at": now,
        },
        {
            "task_name": "run_scanner",
            "status": "failed",
            "error": "AttributeError: missing setting",
            "completed_at": old,
        },
    ]
    monkeypatch.setattr(
        task_monitor_routes.task_executor,
        "get_recent_executions",
        lambda limit=100: executions,
    )
    monkeypatch.setattr(
        task_monitor_routes.task_executor,
        "get_status",
        lambda: {"is_running": True},
    )
    monkeypatch.setitem(task_monitor_routes._scheduler_runtime, "running", True)

    result = await task_monitor_routes.get_actionable_failures(hours=1)

    assert result["count"] == 1
    assert result["failures"][0]["task_name"] == "run_scanner"


@pytest.mark.asyncio
async def test_failures_normalize_aware_and_naive_timestamps(monkeypatch):
    now = datetime.now().astimezone().isoformat()
    executions = [
        {
            "task_name": "run_scanner",
            "status": "failed",
            "error": "provider unavailable",
            "completed_at": now,
        },
        {
            "task_name": "run_scanner",
            "status": "failed",
            "error": "legacy failure",
            "completed_at": datetime.now().isoformat(),
        },
    ]
    monkeypatch.setattr(
        task_monitor_routes.task_executor,
        "get_recent_executions",
        lambda limit=100: executions,
    )
    monkeypatch.setattr(
        task_monitor_routes.task_executor,
        "get_status",
        lambda: {"is_running": True},
    )
    monkeypatch.setitem(task_monitor_routes._scheduler_runtime, "running", True)

    result = await task_monitor_routes.get_actionable_failures(hours=1)

    assert result["count"] == 2
    assert {item["error"] for item in result["failures"]} == {
        "provider unavailable",
        "legacy failure",
    }
