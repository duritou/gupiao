"""The label must compare a stock against the equal-weight market, same window.

The window end is fixed by the market calendar, so a stock suspended across the
horizon is rejected rather than scored against a benchmark that covered
different dates.  These tests pin that guard and the sample shape.
"""

import pytest

from src.explain import outcome_backfiller
from src.explain.benchmark import BASIS_FILTERED, BenchmarkBasis
from src.explain.outcome_backfiller import _build_market_observation

CALENDAR = ["2026-08-01", "2026-08-04", "2026-08-05"]


def _basis(count: int = 4000) -> BenchmarkBasis:
    return BenchmarkBasis(
        status=BASIS_FILTERED, metadata_date="2026-08-01", constituent_count=count
    )


@pytest.fixture()
def benchmark(monkeypatch):
    """Stub the equal-weight lookup so no database is touched."""

    def install(value):
        monkeypatch.setattr(
            outcome_backfiller.market_db,
            "equal_weight_benchmark",
            lambda start, end: (value, _basis()),
        )

    return install


def test_market_observation_requires_a_benchmark_result(benchmark):
    benchmark(None)

    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5}, CALENDAR, "2026-08-01", 1
    )

    assert sample is None


def test_market_observation_rejects_a_stock_whose_window_differs(benchmark):
    # The stock's own next bar is 08-05; the market's is 08-04.  Suspended
    # across the horizon, so it is not comparable.
    benchmark(0.01)

    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-05": 10.5}, CALENDAR, "2026-08-01", 1
    )

    assert sample is None


def test_market_observation_rejects_a_horizon_that_has_not_closed(benchmark):
    benchmark(0.01)

    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5}, CALENDAR, "2026-08-01", 5
    )

    assert sample is None


def test_market_observation_contains_stock_benchmark_and_excess_return(benchmark):
    benchmark(0.01)

    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5}, CALENDAR, "2026-08-01", 1
    )

    assert sample == {
        "stock_return": 0.05,
        "benchmark_return": 0.01,
        "excess_return": pytest.approx(0.04),
        "observation_date": "2026-08-04",
        "benchmark_basis": BASIS_FILTERED,
    }


def test_market_observation_carries_the_basis_through(monkeypatch):
    # The basis is persisted so a day that could not be filtered is never
    # pooled with the ones that could.
    unfiltered = BenchmarkBasis(
        status="unfiltered", metadata_date=None, constituent_count=5210,
        reasons=("no_point_in_time_metadata",),
    )
    monkeypatch.setattr(
        outcome_backfiller.market_db,
        "equal_weight_benchmark",
        lambda start, end: (0.01, unfiltered),
    )

    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5}, CALENDAR, "2026-08-01", 1
    )

    assert sample["benchmark_basis"] == "unfiltered"
