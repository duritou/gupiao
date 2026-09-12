from src.research.factor_validation import (
    neutralize_factor,
    validate_factor,
    validate_factor_horizons,
    validate_factor_rolling,
)


def _observations(date_count=6):
    rows = []
    for day in range(date_count):
        date = f"2026-01-{day + 1:02d}"
        for symbol, factor in (("A", 1), ("B", 2), ("C", 3), ("D", 4), ("E", 5)):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "factor": factor,
                    "forward_return": factor * 0.01,
                    "horizon": 1,
                }
            )
    return rows


def test_validate_factor_reports_positive_ic_ir_and_spread():
    result = validate_factor(_observations(), factor_name="momentum")

    assert result.usable is True
    assert result.factor_name == "momentum"
    assert result.date_count == 6
    assert result.mean_ic == 1.0
    assert result.information_ratio == 0.0
    assert result.top_bottom_spread > 0


def test_validate_factor_isolates_horizon_and_fails_closed_on_sparse_data():
    result = validate_factor(
        [{"date": "2026-01-01", "symbol": "A", "factor": 1, "forward_return": 0.1}],
        horizon=5,
    )

    assert result.usable is False
    assert "insufficient" in result.warnings[0]


def test_validate_factor_rolling_uses_only_out_of_sample_blocks():
    windows = validate_factor_rolling(
        _observations(date_count=5), train_dates=2, test_dates=2
    )

    assert len(windows) == 2
    assert windows[0].start_date == "2026-01-03"
    assert windows[0].end_date == "2026-01-04"
    assert windows[1].start_date == "2026-01-05"


def test_horizon_report_exposes_relative_decay():
    rows = _observations(date_count=6)
    rows += [
        {**row, "horizon": 5, "forward_return": row["forward_return"] * 0.5}
        for row in _observations(date_count=6)
    ]

    report = validate_factor_horizons(rows, horizons=(1, 5))

    assert report.by_horizon[1].mean_ic == 1.0
    assert report.by_horizon[5].mean_ic == 1.0
    assert report.ic_decay[1] == 1.0
    assert report.spread_decay[5] == 0.5


def test_neutralize_factor_removes_same_date_industry_mean_without_mutating_input():
    rows = [
        {"date": "2026-01-01", "symbol": "A", "industry": "bank", "factor": 1},
        {"date": "2026-01-01", "symbol": "B", "industry": "bank", "factor": 3},
        {"date": "2026-01-01", "symbol": "C", "industry": "tech", "factor": 8},
    ]

    result = neutralize_factor(rows)

    assert rows[0]["factor"] == 1
    assert result[0]["factor"] == -1
    assert result[1]["factor"] == 1
    assert result[2]["factor"] == 0
