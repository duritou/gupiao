from types import SimpleNamespace

import pytest

from src.ai_os.pipeline_observability import build_stage_acceptance, classify_run_outcome
from src.ai_os.pipeline_runner import _apply_ai_preselection
from src.ai_os.trading_policy import paper_liveness_status


def _deep_decision(code: str, *, available: bool = True) -> dict:
    return {
        "stock_code": code,
        "market_sources": ["tushare"],
        "flow_status": "positive",
        "fundamental_evidence_available": True,
        "deep_candidate_eligible": True,
        "deep_analysis_available": available,
        "deep_input_fingerprint": f"fingerprint-{code}",
        "deep_kline_evidence": {"available": available, "visible_last_date": "2026-09-08"},
        "deep_evidence_consumption": {
            "financials": {
                "status": "available" if available else "unavailable",
                "history_complete": available,
                "period_counts": {name: 8 for name in (
                    "income", "balancesheet", "cashflow", "fina_indicator"
                )},
            },
            "fund_flow": {
                "status": "available" if available else "unavailable",
                "requested_days": 20,
                "row_count": 20 if available else 0,
                "source_layer": "adaptive_tushare_flow_history",
                "rows": [{"data_date": "2026-09-08"}] if available else [],
            },
            "components": {
                "announcements": {
                    "status": "available" if available else "empty",
                    "available": available,
                },
            },
            "analysis_input_sha256": f"analysis-input-{code}",
        },
        "final_review_available": available,
        "final_review_input_sha256": f"review-input-{code}",
    }


def _quality(*, target: int = 2, attempted: int = 2, successful: int = 2, failed=None):
    quality = {
        "run_id": "isolated-run",
        "target_trade_date": "2026-09-08",
        "technical_universe_size": 2,
        "signals_computed": 2,
        "ai_preselection_target": 2,
        "ai_preselection_count": 2,
        "ai_preselection_called": True,
        "deep_candidate_eligibility": {"selected_count": target},
        "deep_analysis_target": target,
        "deep_analysis_attempted_count": attempted,
        "deep_analysis_count": successful,
        "deep_analysis_errors": failed or [],
        "final_review_target": successful,
        "final_review_count": successful,
        "final_review_called": True,
        "execution_observability": {"total": 2, "blocked": 2},
    }
    return quality


def test_stage_contract_keeps_deep_failures_in_denominator_and_zero_is_null():
    decisions = [_deep_decision(f"00000{i}.SZ") for i in range(8)]
    decisions.extend(
        _deep_decision(f"00001{i}.SZ", available=False) for i in range(2)
    )
    quality = _quality(
        target=10,
        attempted=10,
        successful=8,
        failed=[{"stock_code": "000010.SZ", "error": "timeout"},
                {"stock_code": "000011.SZ", "error": "invalid response"}],
    )
    quality["technical_universe_size"] = 10
    quality["signals_computed"] = 10
    quality["execution_observability"] = {"total": 10, "blocked": 10}
    audit = build_stage_acceptance(
        decisions,
        quality,
        execution_deferred=True,
        persistence={"expected_count": 10, "saved_count": 10, "readback_verified": True},
    )

    deep = audit["stages"]["deep_research"]
    assert deep["target_count"] == 10
    assert deep["completed_count"] == 8
    assert deep["failed_count"] == 2
    assert len(deep["stock_details"]) == 10
    assert audit["execution_status"] == "deferred"
    assert audit["evidence_status"] in {"partial", "insufficient"}

    empty = build_stage_acceptance([], {"run_id": "empty"})
    assert empty["stages"]["learning"]["coverage_ratio"] is None
    assert empty["execution_status"] == "not_requested"


def test_deferred_execution_does_not_mask_evidence_gap():
    decision = _deep_decision("000001.SZ", available=False)
    quality = _quality(target=1, attempted=1, successful=1)
    quality.update({
        "technical_universe_size": 1,
        "signals_computed": 1,
        "ai_preselection_target": 0,
        "ai_preselection_count": 0,
        "execution_observability": {"total": 1, "blocked": 1},
    })
    audit = classify_run_outcome(
        [decision], quality, actionable_count=0, execution_deferred=True
    )
    assert audit["status"] == "discovery_only"
    assert audit["execution_status"] == "deferred"
    assert audit["evidence_status"] in {"partial", "insufficient"}
    assert audit["acceptance_status"] == "partial"


def test_acceptance_labels_do_not_mutate_business_decision_projection():
    decisions = [_deep_decision("000001.SZ"), _deep_decision("000002.SZ")]
    decisions[0].update({
        "direction": "buy",
        "final_direction": "buy",
        "ai_score": 78.0,
        "action_score": 76.0,
        "execution_rejection_reasons": ["paper_execution_deferred"],
    })
    decisions[1].update({
        "direction": "neutral",
        "final_direction": "neutral",
        "ai_score": 54.0,
        "action_score": 52.0,
        "execution_rejection_reasons": ["score_below_gate"],
    })
    fields = (
        "stock_code", "direction", "final_direction", "ai_score", "action_score",
        "recommendation", "execution_rejection_reasons",
    )
    before = [[decision.get(field) for field in fields] for decision in decisions]

    build_stage_acceptance(
        decisions,
        _quality(target=2, attempted=2, successful=2),
        actionable_count=1,
        execution_deferred=True,
    )

    after = [[decision.get(field) for field in fields] for decision in decisions]
    assert after == before


def test_deep_evidence_date_before_target_is_stale_not_available():
    decision = _deep_decision("000003.SZ")
    decision["deep_kline_evidence"]["visible_last_date"] = "2026-09-03"
    audit = build_stage_acceptance(
        [decision],
        _quality(target=1, attempted=1, successful=1),
    )

    deep = audit["stages"]["deep_research"]
    assert deep["completed_count"] == 1
    assert deep["unverified_count"] == 1
    assert deep["components"]["deep_kline"]["stale_count"] == 1
    assert deep["components"]["deep_kline"]["available_count"] == 0
    assert "deep_kline_stale" in deep["reason_codes"]


@pytest.mark.asyncio
async def test_preselection_records_actual_input_without_changing_zero_adjustment():
    decision = {
        "stock_code": "000001.SZ",
        "stock_name": "test",
        "technical_score": 70,
        "discovery_score": 60,
        "fusion_score": 68,
        "market_change_pct": 1.2,
        "market_sources": ["tushare"],
        "market_reasons": [],
        "market_flow": {"status": "positive"},
        "stock_skill_evidence": {},
        "ai_score": 68,
    }

    class Router:
        async def generate(self, **kwargs):
            return SimpleNamespace(
                text='[{"code":"000001.SZ","score_adjustment":0,"direction":"neutral","reason":"ok"}]',
                provider="codex_cli",
                model="test-model",
                fallback_used=False,
            )

    matched, called, error = await _apply_ai_preselection(
        [decision], 1, Router(), True
    )
    assert (matched, called, error) == (1, True, "")
    assert decision["ai_score"] == 68
    assert len(decision["preselection_input_sha256"]) == 64
    assert decision["preselection_input_count"] == 1
    assert "flow" in decision["preselection_input_fields"]


def test_liveness_uses_one_latest_observation_per_day_and_same_cutoff():
    logs = [
        {"id": 5, "category": "execution_observability", "learning_date": "2026-09-10",
         "created_at": "2026-09-10T20:00:00", "evidence": {"new_buy_count": 0}},
        {"id": 4, "category": "execution_observability", "learning_date": "2026-09-08",
         "created_at": "2026-09-08T20:01:00", "evidence": {"new_buy_count": 0}},
        {"id": 3, "category": "execution_observability", "learning_date": "2026-09-08",
         "created_at": "2026-09-08T20:00:00", "evidence": {"new_buy_count": 1}},
        {"id": 2, "category": "execution_observability", "learning_date": "2026-09-07",
         "created_at": "2026-09-07T20:00:00", "evidence": {"new_buy_count": 0}},
        {"id": 1, "category": "execution_observability", "learning_date": "2026-09-06",
         "created_at": "2026-09-06T20:00:00", "evidence": {"execution_deferred": True}},
    ]
    result = paper_liveness_status(
        logs, 90, 100, as_of_date="2026-09-08", alert_after_days=5
    )
    assert result["counted_learning_dates"] == ["2026-09-08", "2026-09-07"]
    assert result["consecutive_no_buy_sessions"] == 2
