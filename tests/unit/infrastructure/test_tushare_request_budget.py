from __future__ import annotations

import pytest

from src.infrastructure.market_data.tushare_request_budget import (
    BudgetExhaustedError,
    TushareRequestBudget,
)


@pytest.mark.asyncio
async def test_budget_reservation_is_shared_by_endpoints(tmp_path):
    budget = TushareRequestBudget(
        tmp_path / "budget.db", max_per_minute=3, max_per_day=10
    )

    assert await budget.reserve("daily") >= 0
    assert await budget.reserve("income") >= 0
    assert await budget.reserve("moneyflow") >= 0
    usage = budget.usage()

    assert usage["current_minute"] == 3
    assert usage["current_day"] == 3


@pytest.mark.asyncio
async def test_budget_fails_bounded_when_minute_bucket_is_full(tmp_path):
    budget = TushareRequestBudget(
        tmp_path / "budget.db", max_per_minute=1, max_per_day=10
    )
    await budget.reserve("daily")

    with pytest.raises(BudgetExhaustedError):
        await budget.reserve("daily", max_wait_seconds=0.1)
