from src.ai_os.recommendation_quality import (
    apply_publication_quality,
    is_actionable_recommendation,
    is_publishable_recommendation,
    recommendation_tier,
)


def _decision(**overrides):
    decision = {
        "stock_code": "000001.SZ",
        "direction": "neutral",
        "decision_status": "hold",
        "deep_analysis_available": True,
        "execution_evidence_complete": True,
        "score_guard_reasons": [],
        "publication_blocked": False,
        "deep_rating": "Hold",
    }
    decision.update(overrides)
    return decision


def test_complete_deep_hold_is_publishable_but_not_actionable():
    decision = _decision()

    assert is_publishable_recommendation(decision) is True
    assert is_actionable_recommendation(decision) is False
    assert recommendation_tier(decision) == "research_complete"


def test_deep_buy_requires_the_existing_buy_approval_policy():
    decision = _decision(
        direction="buy",
        decision_status="buy_candidate",
        deep_rating="Buy",
        deep_provider="codex_cli",
        deep_model="gpt-5.6-terra",
    )

    assert is_publishable_recommendation(decision) is True
    assert is_actionable_recommendation(decision) is False


def test_publication_gate_preserves_global_block_reason():
    decision = _decision()

    apply_publication_quality(decision, ["market_data_degraded"])

    assert decision["publication_blocked"] is True
    assert decision["publication_block_reasons"] == ["market_data_degraded"]
    assert decision["recommendation_tier"] == "data_blocked"
    assert is_publishable_recommendation(decision) is False


def test_missing_deep_analysis_stays_in_technical_watchlist():
    decision = _decision(
        deep_analysis_available=False,
        execution_evidence_complete=False,
    )

    assert recommendation_tier(decision) == "technical_watchlist"
    assert is_publishable_recommendation(decision) is False
