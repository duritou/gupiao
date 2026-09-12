from src.replay.algorithm_comparator import compare_algorithms


def _decision(code, direction, *, actionable=True):
    return {
        "stock_code": code,
        "direction": direction,
        "actionable": actionable,
    }


def test_comparator_uses_same_frozen_dates_and_scores_sell_with_inverse_return():
    result = compare_algorithms([
        {
            "trade_date": "2026-08-24",
            "baseline": [_decision("A", "buy")],
            "candidate": [_decision("A", "buy")],
            "outcomes": {"A": 2.0},
            "lookahead_safe": True,
        },
        {
            "trade_date": "2026-08-25",
            "baseline": [_decision("B", "sell")],
            "candidate": [_decision("B", "sell")],
            "outcomes": {"B": 3.0},
            "lookahead_safe": True,
        },
    ])

    assert result.status == "ok"
    assert result.lookahead_safe is True
    assert result.metrics["baseline"].correct_signals == 1
    assert result.metrics["baseline"].evaluated_signals == 2
    assert result.metrics["baseline"].average_return_pct == -0.5
    assert result.metrics["baseline"].average_return_ci95_pct is not None


def test_comparator_reports_coverage_rejection_and_candidate_delta():
    result = compare_algorithms([
        {
            "trade_date": "2026-08-24",
            "baseline": [
                _decision("A", "buy"), _decision("B", "neutral", actionable=False)
            ],
            "candidate": [
                _decision("A", "buy"), _decision("B", "buy", actionable=False),
            ],
            "outcomes": {"A": 1.0},
            "lookahead_safe": True,
        },
    ])

    baseline = result.metrics["baseline"]
    candidate = result.metrics["candidate"]
    assert baseline.coverage_pct == 100.0
    assert baseline.rejection_rate_pct == 50.0
    assert candidate.actionable_signals == 1
    assert result.deltas["rejection_rate_pct"] == 0.0


def test_comparator_fails_closed_when_lookahead_is_not_confirmed():
    result = compare_algorithms([
        {"trade_date": "2026-08-24", "baseline": [], "candidate": []}
    ])

    assert result.status == "lookahead_unverified"
    assert result.lookahead_safe is False
    assert "lookahead_safety_not_confirmed" in result.warnings


def test_comparator_rejects_duplicate_dates():
    result = compare_algorithms([
        {"trade_date": "2026-08-24"}, {"trade_date": "2026-08-24"}
    ])

    assert result.status == "invalid_snapshots"
    assert result.metrics == {}
