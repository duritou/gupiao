from scripts.build_historical_replay_snapshots import _decision_row, _outcomes


def test_decision_row_keeps_research_score_but_blocks_neutral_execution():
    row = _decision_row({
        "stock_code": "000001.SZ",
        "direction": "neutral",
        "fusion_score": 60.0,
        "forward_return_pct": 1.2,
        "outcome_available": True,
    })

    assert row["ranking_score"] == 60.0
    assert row["action_score"] is None
    assert row["actionable"] is False
    assert row["executable_direction"] == ""


def test_outcomes_only_contains_complete_forward_labels():
    rows = [
        {
            "stock_code": "000001.SZ",
            "forward_return_pct": 1.2,
            "outcome_available": True,
        },
        {
            "stock_code": "000002.SZ",
            "forward_return_pct": None,
            "outcome_available": False,
        },
    ]

    assert _outcomes(rows) == {"000001.SZ": 1.2}


def test_decision_row_normalizes_direction_for_comparator_contract():
    row = _decision_row({
        "stock_code": "600000.SH",
        "direction": " SELL ",
        "fusion_score": 30.0,
        "outcome_available": True,
    })

    assert row["direction"] == "sell"
    assert row["executable_direction"] == "sell"
    assert row["actionable"] is True
