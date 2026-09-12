from src.domain.models.selection_decision import (
    SelectionDecisionContract,
    normalize_decision_fields,
)


def test_contract_normalization_preserves_ranking_and_separates_action_score():
    decision = {
        "stock_code": "000001.sz",
        "ranking_score": 82.5,
        "action_score": 60.0,
        "direction": "buy",
        "score_guard_reasons": ["market_quote_missing"],
    }

    contract = normalize_decision_fields(decision)

    assert isinstance(contract, SelectionDecisionContract)
    assert contract.stock_code == "000001.SZ"
    assert contract.ranking_score == 82.5
    assert contract.action_score == 60.0
    assert contract.predicted_direction == "buy"
    assert contract.executable_direction == "neutral"
    assert decision["ranking_score"] == 82.5
    assert decision["actionable"] is False


def test_contract_normalization_is_compatible_with_legacy_decision_shape():
    decision = {"stock_code": "600000.SH", "ai_score": 71, "direction": "unknown"}

    contract = normalize_decision_fields(decision)

    assert contract.ranking_score == 71
    assert contract.action_score == 71
    assert contract.predicted_direction == "neutral"
    assert contract.executable_direction == "neutral"
