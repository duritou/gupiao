"""Tests for auditable multi-strategy cross-sectional selection scores."""

import json

from src.ai_os.cross_sectional_scoring import apply_cross_sectional_scores


def _decision(code: str, score: float, flow: float = 1.0, sources=None) -> dict:
    return {
        "stock_code": code,
        "technical_score": score,
        "macd_score": score,
        "ma_score": score,
        "rsi_score": score,
        "kdj_score": score,
        "volume_score": score,
        "discovery_score": score,
        "learning_adjustment": 0,
        "market_sources": list(
            ["tencent", "ths_hot"] if sources is None else sources
        ),
        "market_flow": {"main_net": flow},
        "evidence": json.dumps({"technical": {"score": score}}),
    }


def test_cross_sectional_rank_orders_candidates_and_requires_confirmations():
    decisions = [
        _decision("LOW", 20),
        _decision("MID", 50),
        _decision("HIGH", 90),
    ]

    apply_cross_sectional_scores(decisions)

    assert decisions[2]["technical_score"] > decisions[1]["technical_score"]
    assert decisions[1]["technical_score"] > decisions[0]["technical_score"]
    assert decisions[2]["strategy_confirmations"] == 3
    assert decisions[2]["direction"] == "buy"
    assert decisions[0]["direction"] == "sell"


def test_equal_factor_values_receive_equal_strategy_scores():
    decisions = [_decision("A", 60), _decision("B", 60)]

    apply_cross_sectional_scores(decisions)

    assert decisions[0]["strategy_scores"] == decisions[1]["strategy_scores"]
    assert decisions[0]["technical_score"] == decisions[1]["technical_score"]


def test_missing_discovery_uses_technical_and_learning_only():
    decisions = [_decision("A", 80, sources=[])]

    apply_cross_sectional_scores(decisions)

    evidence = json.loads(decisions[0]["evidence"])
    assert evidence["fusion_policy"]["discovery_available"] is False
    assert decisions[0]["ai_score"] == 75.5


def test_positive_score_without_flow_cannot_become_buy():
    decisions = [
        _decision("LOW", 20),
        _decision("HIGH", 90, flow=-1),
    ]

    apply_cross_sectional_scores(decisions)

    assert decisions[1]["ai_score"] >= 65
    assert decisions[1]["strategy_confirmations"] >= 2
    assert decisions[1]["direction"] == "neutral"


def test_evidence_records_raw_ranked_scores_and_policy():
    decisions = [_decision("A", 70)]

    apply_cross_sectional_scores(decisions)

    evidence = json.loads(decisions[0]["evidence"])
    assert evidence["technical"]["raw_score"] == 70
    assert evidence["technical"]["strategy_scores"] == decisions[0]["strategy_scores"]
    assert evidence["fusion_policy"] == {
        "technical_weight": 0.7,
        "discovery_weight": 0.2,
        "learning_weight": 0.1,
        "discovery_available": True,
    }


def test_invalid_flow_values_are_observed_without_crashing_or_buying():
    decision = _decision("A", 90, flow="not-a-number")

    apply_cross_sectional_scores([decision])

    assert decision["flow_status"] == "invalid"
    assert decision["direction"] == "neutral"


def test_missing_and_negative_flow_are_distinct():
    missing = _decision("MISSING", 90, flow=None)
    missing["market_flow"] = {}
    negative = _decision("NEGATIVE", 90, flow=-1)

    apply_cross_sectional_scores([missing, negative])

    assert missing["flow_status"] == "missing"
    assert negative["flow_status"] == "negative"
