from src.ai_os.market_learning import learning_adjustment
from src.ai_os.recommendation_quality import (
    apply_publication_quality,
    is_publishable_recommendation,
    sort_decisions,
)
from src.ai_os.score_guard import apply_score_guard
from src.ai_os.trading_policy import is_buy_signal, paper_liveness_status


def test_learning_adjustment_is_bounded_for_two_observations():
    result = learning_adjustment(
        {
            "by_symbol": {
                "002385.SZ": {"observations": 2, "correct": 2, "incorrect": 0}
            }
        },
        "002385.SZ",
        [],
    )

    assert result["score_adjustment"] == 2.0
    assert "early cap2" in result["policy"]


def test_learning_adjustment_accepts_decayed_fractional_observations():
    result = learning_adjustment(
        {
            "horizon_days": 1,
            "by_symbol": {
                "000001.SZ": {
                    "observations": 2.4,
                    "correct": 2.0,
                    "incorrect": 0.4,
                }
            },
            "by_source": {},
        },
        "000001.SZ",
        [],
    )

    assert result["symbol_adjustment"] > 0


def test_missing_evidence_caps_score_and_blocks_buy():
    decision = {"ai_score": 70.4, "fusion_score": 70.4, "direction": "buy"}

    apply_score_guard(decision, {})

    assert decision["ai_score"] == 60.0
    assert decision["direction"] == "neutral"
    assert decision["recommendation"] == "观望"
    assert decision["score_guarded"] is True
    assert decision["decision_status"] == "data_blocked"
    assert "fundamental_evidence_missing" in decision["score_guard_reasons"]


def test_score_guard_distinguishes_missing_market_data_from_research_candidate():
    decision = {"ai_score": 70.4, "direction": "buy"}

    apply_score_guard(decision, {"fundamentals": {"profit": 1}})

    assert decision["decision_status"] == "data_blocked"


def test_loss_forecast_caps_score_more_aggressively():
    decision = {"ai_score": 82.0, "fusion_score": 82.0, "direction": "buy"}
    discovery = {
        "sources": ["cninfo"],
        "quote": {"price": 3.2},
        "fundamentals": {"expected_net_profit": -600000000},
    }

    apply_score_guard(decision, discovery)

    assert decision["ai_score"] == 45.0
    assert decision["direction"] == "neutral"
    assert decision["recommendation"] == "回避"
    assert "fundamental_loss_risk" in decision["score_guard_reasons"]


def test_successful_deep_analysis_can_clear_missing_evidence_gate():
    decision = {"ai_score": 70.0, "fusion_score": 70.0, "direction": "buy"}
    deep = {"available": True, "evidence_gaps": [], "decision": "继续观察", "thesis": ""}

    apply_score_guard(
        decision,
        {"sources": ["cninfo"], "quote": {"price": 10.0}},
        deep,
    )

    assert decision["ai_score"] == 70.0
    assert decision["score_guarded"] is False
    assert decision["fundamental_evidence_available"] is True


def test_guarded_score_does_not_replace_ranking_score():
    decision = {"ai_score": 82.0, "fusion_score": 82.0, "direction": "buy"}

    apply_score_guard(decision, {})

    assert decision["ranking_score"] == 82.0
    assert decision["raw_ai_score"] == 82.0
    assert decision["action_score"] == 60.0
    assert decision["ai_score"] == 60.0


def test_deep_analysis_is_not_market_context():
    decision = {"ai_score": 70.0, "direction": "buy"}
    deep = {"available": True, "evidence_gaps": []}

    apply_score_guard(decision, {}, deep)

    assert decision["decision_status"] == "data_blocked"
    assert "market_context_missing" in decision["score_guard_reasons"]


def test_incomplete_universe_metadata_cannot_be_published():
    decision = {
        "ai_score": 76.0,
        "direction": "buy",
        "universe_metadata_complete": False,
    }

    apply_score_guard(
        decision,
        {"sources": ["tencent"], "quote": {"price": 10.0}},
        {"available": True, "evidence_gaps": []},
    )

    assert decision["decision_status"] == "data_blocked"
    assert "universe_metadata_incomplete" in decision["score_guard_reasons"]
    assert decision["execution_evidence_complete"] is False


def test_global_data_quality_block_prevents_publication():
    decision = {
        "ai_score": 76.0,
        "direction": "buy",
        "deep_analysis_available": True,
        "decision_status": "buy_candidate",
    }
    apply_score_guard(
        decision,
        {"sources": ["tencent"], "quote": {"price": 10.0}},
        {"available": True, "evidence_gaps": []},
        additional_reasons=["market_data_degraded"],
    )
    apply_publication_quality(decision, ["market_data_degraded"])

    assert decision["decision_status"] == "data_blocked"
    assert decision["publication_blocked"] is True
    assert is_publishable_recommendation(decision) is False


def test_actionable_false_blocks_buy_even_when_score_is_high():
    decision = {
        "ai_score": 80.0,
        "action_score": 80.0,
        "direction": "buy",
        "actionable": False,
    }

    assert is_buy_signal(decision) is False


def test_paper_liveness_alert_is_observability_only():
    history = [
        {
            "category": "execution_observability",
            "evidence": {"new_buy_count": 0, "execution_deferred": False},
        }
        for _ in range(5)
    ]

    status = paper_liveness_status(history, cash=800.0, total_value=1000.0)

    assert status["alert"] is True
    assert status["consecutive_no_buy_sessions"] == 5
    assert status["reason"] == "no_actionable_buy_with_high_cash"


def test_publishable_recommendations_are_sorted_by_unblocked_ranking_score():
    complete = {
        "stock_code": "000002.SZ",
        "ai_score": 72.0,
        "ranking_score": 72.0,
        "technical_score": 70.0,
        "discovery_score": 70.0,
        "direction": "neutral",
        "decision_status": "hold",
        "deep_analysis_available": True,
        "execution_evidence_complete": True,
        "score_guard_reasons": [],
        "publication_blocked": False,
    }
    blocked = {
        **complete,
        "stock_code": "000001.SZ",
        "ranking_score": 90.0,
        "score_guard_reasons": ["market_data_degraded"],
        "publication_blocked": True,
    }

    assert is_publishable_recommendation(complete) is True
    assert sort_decisions([complete, blocked])[0]["stock_code"] == "000001.SZ"


def test_score_guard_persists_a_complete_score_lineage():
    decision = {
        "scanner_score": 76.0,
        "preselection_base_score": 76.0,
        "ai_preselection_score": 4.0,
        "preselection_adjusted_score": 80.0,
        "deep_base_score": 80.0,
        "deep_score": 82.0,
        "ai_score": 82.0,
        "direction": "buy",
    }

    apply_score_guard(
        decision,
        {"sources": ["tencent"], "quote": {"price": 10.0}},
        {"available": True, "evidence_gaps": []},
    )

    assert decision["score_lineage"]["scanner_score"] == 76.0
    assert decision["score_lineage"]["preselection_adjustment"] == 4.0
    assert decision["score_lineage"]["deep_score"] == 82.0
    assert decision["score_lineage"]["guard_input_score"] == 82.0
