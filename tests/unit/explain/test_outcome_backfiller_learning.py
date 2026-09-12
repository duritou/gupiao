from src.explain import outcome_backfiller
from src.infrastructure.market_data.tushare_provider import TusharePayload


from src.explain.outcome_backfiller import _build_market_observation


def test_market_observation_requires_a_benchmark_result():
    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5},
        {},
        "2026-08-01",
        1,
    )

    assert sample is None


def test_market_observation_requires_matching_observation_dates():
    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5},
        {"2026-08-01": 100.0, "2026-08-05": 101.0},
        "2026-08-01",
        1,
    )

    assert sample is None


def test_market_observation_contains_stock_benchmark_and_excess_return():
    sample = _build_market_observation(
        {"2026-08-01": 10.0, "2026-08-04": 10.5},
        {"2026-08-01": 100.0, "2026-08-04": 101.0},
        "2026-08-01",
        1,
    )

    assert sample == {
        "stock_return": 0.05,
        "benchmark_return": 0.01,
        "excess_return": 0.04,
        "observation_date": "2026-08-04",
    }


def test_benchmark_prefers_tushare(monkeypatch):
    async def fetch_index_closes(code, count):
        return TusharePayload(
            {"2026-09-01": 100.0, "2026-09-02": 101.0, "2026-09-03": 102.0,
             "2026-09-04": 103.0, "2026-09-05": 104.0, "2026-09-06": 105.0},
            "index_daily",
            "2026-09-06",
            row_count=6,
        )

    monkeypatch.setattr(
        "src.infrastructure.market_data.tushare_provider.tushare_provider.fetch_index_closes",
        fetch_index_closes,
    )

    result = outcome_backfiller._fetch_hs300_bars(days=60)

    assert len(result) == 6
    assert outcome_backfiller._benchmark_source == "tushare"
