from src.replay.historical_gate import evaluate_historical_gate


def _snapshot(day, outcome):
    return {
        "trade_date": f"2026-08-{day:02d}",
        "baseline": [{"stock_code": "A", "direction": "buy"}],
        "candidate": [{"stock_code": "A", "direction": "buy"}],
        "outcomes": {"A": outcome},
        "lookahead_safe": True,
    }


def test_historical_gate_blocks_before_minimum_days():
    result = evaluate_historical_gate([_snapshot(day, 1) for day in range(1, 20)])

    assert result.status == "insufficient_history"
    assert result.available_days == 19
    assert result.eligible_for_promotion is False
    assert "insufficient_complete_trading_days" in result.reasons


def test_historical_gate_requires_lookahead_confirmation():
    snapshots = [_snapshot(day, 1) for day in range(1, 21)]
    snapshots[0]["lookahead_safe"] = False

    result = evaluate_historical_gate(snapshots)

    assert result.status == "blocked"
    assert result.lookahead_safe is False
    assert result.eligible_for_promotion is False


def test_historical_gate_blocks_candidate_with_worse_return_or_drawdown():
    snapshots = [_snapshot(day, 1) for day in range(1, 21)]
    for snapshot in snapshots:
        snapshot["candidate"][0]["direction"] = "sell"

    result = evaluate_historical_gate(
        snapshots
    )

    assert result.status == "blocked"
    assert "candidate_total_return_worse_than_baseline" in result.reasons


def test_historical_gate_passes_only_structurally_safe_equal_comparison():
    result = evaluate_historical_gate([_snapshot(day, 1) for day in range(1, 21)])

    assert result.status == "passed"
    assert result.historical_gate_passed is True
    assert result.eligible_for_promotion is False
    assert result.available_days == 20
