from __future__ import annotations

import multiprocessing

import pytest

from src.infrastructure.market_data.tushare_request_budget import (
    BudgetExhaustedError,
    TushareRequestBudget,
)


def _reserve_from_process(db_path: str, result_queue: object) -> None:
    budget = TushareRequestBudget(db_path, max_per_minute=5, max_per_day=20)
    reserved, _ = budget._try_reserve("worker")
    result_queue.put(reserved)


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_exceed_shared_minute_limit(tmp_path):
    budget = TushareRequestBudget(
        tmp_path / "shared.db", max_per_minute=5, max_per_day=20
    )

    async def reserve():
        try:
            await budget.reserve("daily", max_wait_seconds=0.1)
            return True
        except BudgetExhaustedError:
            return False

    results = await __import__("asyncio").gather(*(reserve() for _ in range(8)))
    assert sum(results) == 5
    assert budget.usage()["current_minute"] == 5


def test_reservations_are_atomic_across_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_reserve_from_process,
            args=(str(tmp_path / "process-shared.db"), result_queue),
        )
        for _ in range(8)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0

    results = [result_queue.get(timeout=2) for _ in processes]
    budget = TushareRequestBudget(
        tmp_path / "process-shared.db", max_per_minute=5, max_per_day=20
    )
    assert sum(results) == 5
    assert budget.usage()["current_minute"] == 5
