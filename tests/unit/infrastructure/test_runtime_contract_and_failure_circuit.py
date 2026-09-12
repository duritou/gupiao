from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.ai_os.pipeline_runner import _add_held_risk_decisions
from src.ai_os.scheduler import SchedulePhase, ScheduledTask
from src.ai_os.task_executor import TaskExecutor
from src.ai_os.trading_policy import position_exit_reason
from src.infrastructure.storage.market_database import MarketDatabase


@pytest.mark.asyncio
async def test_critical_task_failure_alerts_once_then_opens_circuit(monkeypatch):
    executor = TaskExecutor(persist=False)
    notify = AsyncMock()
    route = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    monkeypatch.setattr(executor, "_notify_wechat", notify)
    monkeypatch.setattr(executor, "_route_task", route)
    task = ScheduledTask(
        phase=SchedulePhase.WEEKLY,
        name="critical_probe",
        description="test",
        is_critical=True,
    )

    first = await executor.execute_task(task)
    second = await executor.execute_task(task)
    third = await executor.execute_task(task)
    fourth = await executor.execute_task(task)

    assert first.status.value == "failed"
    assert second.status.value == "failed"
    assert third.circuit_state == "circuit_open"
    assert fourth.status.value == "skipped"
    assert fourth.output["skip_reason"] == "circuit_open"
    assert third.consecutive_failures == 3
    assert notify.await_count == 2
    assert route.await_count == 3


@pytest.mark.asyncio
async def test_failure_circuit_recovery_probe_notifies_once(monkeypatch):
    executor = TaskExecutor(persist=False)
    notify = AsyncMock()
    route = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    monkeypatch.setattr(executor, "_notify_wechat", notify)
    monkeypatch.setattr(executor, "_route_task", route)
    task = ScheduledTask(
        phase=SchedulePhase.WEEKLY,
        name="recovery_probe",
        description="test",
        is_critical=True,
    )

    for _ in range(3):
        await executor.execute_task(task)
    executor._failure_incidents[task.name]["next_probe_at"] = (
        datetime.now() - timedelta(seconds=1)
    ).isoformat()
    route.side_effect = None
    route.return_value = {"status": "recovered"}

    recovered = await executor.execute_task(task)

    assert recovered.status.value == "success"
    assert executor.is_circuit_open(task.name) is False
    assert notify.await_count == 3
    assert "恢复" in notify.await_args_list[-1].args[0]


def test_existing_database_requires_explicit_runtime_contract_adoption(tmp_path):
    database = MarketDatabase(tmp_path / "runtime-contract.db")
    with database._get_conn() as connection:
        connection.execute(
            "INSERT INTO decision_journal(stock_code, stock_name, decision_date, "
            "created_at, evidence) VALUES (?, ?, ?, ?, ?)",
            ("000001.SZ", "test", "2026-08-14", "2026-08-14T10:00:00", "{}"),
        )
    identity = {
        "algorithm_version": "test-version",
        "code_hash": "test-code",
        "build_id": "test-build",
    }

    with pytest.raises(RuntimeError, match="explicit adoption required"):
        database.validate_runtime_contract(identity)

    adopted = database.adopt_runtime_contract(identity)
    assert adopted["status"] == "active"
    assert database.validate_runtime_contract(identity)["status"] == "active"


def test_held_risk_review_uses_verified_entry_deep_rating():
    position = {
        "stock_code": "000001.SZ",
        "stock_name": "test",
        "entry_decision_id": 7,
        "entry_strategy_version": "2.2.0-evidence-routing",
        "entry_deep_rating": "Buy",
        "entry_identity_status": "verified",
    }
    decisions = _add_held_risk_decisions(
        [],
        [position],
        trade_date="2026-08-14",
        signal_at="2026-08-14T15:00:00+08:00",
        data_cutoff_at="2026-08-14T15:00:00+08:00",
    )

    assert position_exit_reason(
        {"avg_cost": 10.0, **position},
        {**decisions[0], "ai_score": 80, "direction": "neutral", "deep_rating": "Hold"},
        current_price=10.0,
        holding_days=10,
    ) == ""


def test_unverified_entry_does_not_receive_deep_buy_bypass():
    reason = position_exit_reason(
        {
            "avg_cost": 10.0,
            "entry_decision_id": None,
            "entry_strategy_version": "",
            "entry_deep_rating": "Buy",
            "entry_identity_status": "legacy_unverified",
        },
        {
            "position_risk_review": True,
            "ai_score": 80,
            "direction": "neutral",
            "deep_rating": "Hold",
        },
        current_price=10.0,
        holding_days=10,
    )

    assert reason == "neutral_max_holding_days=8"
