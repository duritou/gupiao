import json

import pytest

from src.ai_os.pipeline_runner import (
    _add_held_risk_decisions,
    _apply_current_execution_metadata,
    _deep_candidate_rank,
    _execution_candidates,
)
from src.ai_os.trading_policy import (
    conditional_probe_rejection_reason,
    is_conditional_probe_approved,
    is_conditional_probe_candidate,
    is_momentum_probe_approved,
    is_momentum_probe_candidate,
    momentum_probe_candidate_rejection_reason,
    momentum_probe_rejection_reason,
)
from src.infrastructure.storage.market_database import MarketDatabase


def _probe_decision(
    code: str = "600127.SH",
    *,
    raw_score: float = 75.8,
    change_pct: float = 1.8,
) -> dict:
    evidence = {
        "score_guard": {
            "raw_score": raw_score,
            "guarded_score": 60.0,
            "guarded": True,
            "reasons": ["fundamental_evidence_missing"],
        },
        "market_discovery": {
            "discovery_score": 79.9,
            "sources": ["tencent_hot", "stock_skill"],
        },
    }
    return {
        "date": "2026-08-27",
        "stock_code": code,
        "stock_name": "momentum",
        "ai_score": 60.0,
        "direction": "neutral",
        "buy_signals": 3,
        "evidence": json.dumps(evidence),
        "market_price": 9.9,
        "market_change_pct": change_pct,
        "market_volume_ratio": 1.4,
        "market_active_volume_ratio": 0.12,
    }


def test_guarded_neutral_can_become_confirmed_momentum_probe():
    decision = _probe_decision()

    assert is_momentum_probe_candidate(decision) is True
    assert momentum_probe_candidate_rejection_reason(decision) == ""
    assert is_momentum_probe_approved(decision) is True


def test_conditional_lane_accepts_missing_overnight_context_with_live_trigger():
    decision = _probe_decision(raw_score=57.6)
    evidence = json.loads(decision["evidence"])
    evidence["technical"] = {"score": 58.7, "confirmations": 1}
    evidence["score_guard"]["reasons"] = [
        "market_context_missing", "fundamental_evidence_missing",
    ]
    decision["evidence"] = json.dumps(evidence)

    assert is_conditional_probe_candidate(decision) is True
    assert is_conditional_probe_approved(decision) is True
    assert conditional_probe_rejection_reason(decision) == ""


def test_conditional_lane_never_bypasses_hard_fundamental_risk():
    decision = _probe_decision(raw_score=80.0)
    evidence = json.loads(decision["evidence"])
    evidence["technical"] = {"score": 80.0, "confirmations": 2}
    evidence["score_guard"]["reasons"] = ["fundamental_loss_risk"]
    decision["evidence"] = json.dumps(evidence)

    assert is_conditional_probe_candidate(decision) is False
    assert conditional_probe_rejection_reason(decision) == (
        "conditional_probe_hard_risk_gate_failed"
    )


def test_exploration_lane_accepts_bounded_lower_score_candidate():
    decision = _probe_decision(raw_score=68.0)
    evidence = json.loads(decision["evidence"])
    evidence["market_discovery"]["discovery_score"] = 70.0
    decision["evidence"] = json.dumps(evidence)

    assert is_momentum_probe_candidate(decision) is True


def test_opening_recheck_accepts_ranked_neutral_with_one_balanced_buy_signal():
    decision = _probe_decision(raw_score=61.0)
    evidence = json.loads(decision["evidence"])
    evidence["market_discovery"]["discovery_score"] = 61.0
    decision.update({"buy_signals": 1, "sell_signals": 1})
    decision["evidence"] = json.dumps(evidence)

    assert is_momentum_probe_candidate(decision) is True


def test_opening_recheck_rejects_sell_dominance_and_suspension():
    sell_dominant = _probe_decision(raw_score=61.0)
    sell_dominant.update({"buy_signals": 1, "sell_signals": 2})
    assert momentum_probe_candidate_rejection_reason(sell_dominant) == (
        "momentum_probe_technical_balance_negative"
    )

    suspended = _probe_decision(raw_score=61.0)
    suspended.update({"status": "suspended", "is_suspended": True})
    assert momentum_probe_candidate_rejection_reason(suspended) == (
        "momentum_probe_stock_not_tradable"
    )


def test_opening_execution_overlays_current_tradability_only():
    decisions = [{
        "stock_code": "002998.SZ",
        "status": "active",
        "is_suspended": False,
        "industry": "化纤",
    }]

    _apply_current_execution_metadata(decisions, {
        "002998.SZ": {
            "status": "suspended",
            "is_suspended": True,
            "industry": "should-not-overwrite-frozen-research",
        }
    })

    assert decisions[0]["status"] == "suspended"
    assert decisions[0]["is_suspended"] is True
    assert decisions[0]["industry"] == "化纤"


def test_exploration_lane_accepts_strong_buy_when_codex_has_no_result():
    decision = _probe_decision(raw_score=74.0)
    evidence = json.loads(decision["evidence"])
    evidence["score_guard"]["reasons"] = []
    decision.update({
        "direction": "buy",
        "ai_score": 74.0,
        "deep_analysis_available": False,
        "deep_analysis_error": "Codex CLI timed out",
    })
    decision["evidence"] = json.dumps(evidence)

    assert is_momentum_probe_candidate(decision) is True


def test_exploration_lane_requires_two_independent_market_sources():
    decision = _probe_decision()
    evidence = json.loads(decision["evidence"])
    evidence["market_discovery"]["sources"] = ["tencent_hot"]
    decision["evidence"] = json.dumps(evidence)

    assert is_momentum_probe_candidate(decision) is False
    assert momentum_probe_candidate_rejection_reason(decision) == (
        "momentum_probe_independent_sources_insufficient"
    )


def test_deep_rank_preserves_raw_signal_before_guarded_score():
    guarded_raw_leader = {
        "raw_ai_score": 82.0,
        "ai_score": 60.0,
        "technical_score": 82.0,
        "discovery_score": 60.0,
    }
    complete_lower_raw = {
        "raw_ai_score": 75.0,
        "ai_score": 75.0,
        "technical_score": 75.0,
        "discovery_score": 75.0,
    }

    assert _deep_candidate_rank(guarded_raw_leader) > _deep_candidate_rank(
        complete_lower_raw
    )


def test_probe_allows_deep_hold_but_never_overrides_bearish_deep_result():
    deep_hold = {
        **_probe_decision(),
        "deep_analysis_available": True,
        "deep_rating": "Hold",
    }
    assert is_momentum_probe_candidate(deep_hold) is True

    deep_underweight = {
        **_probe_decision(),
        "deep_analysis_available": True,
        "deep_rating": "Underweight",
    }
    assert is_momentum_probe_candidate(deep_underweight) is False
    assert momentum_probe_candidate_rejection_reason(deep_underweight) == (
        "momentum_probe_deep_result_is_authoritative"
    )

    missing_context = _probe_decision()
    evidence = json.loads(missing_context["evidence"])
    evidence["score_guard"]["reasons"] = ["market_context_missing"]
    missing_context["evidence"] = json.dumps(evidence)
    assert is_momentum_probe_candidate(missing_context) is False
    assert momentum_probe_candidate_rejection_reason(missing_context) == (
        "momentum_probe_evidence_gate_failed"
    )


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"market_change_pct": 5.0}, "momentum_probe_opening_move_too_extended"),
        ({"market_volume_ratio": 0.8}, "momentum_probe_volume_ratio_too_low"),
        (
            {"market_active_volume_ratio": -0.01},
            "momentum_probe_active_buying_not_confirmed",
        ),
    ],
)
def test_probe_requires_non_extended_live_strength(updates, expected):
    decision = {**_probe_decision(), **updates}
    assert is_momentum_probe_approved(decision) is False
    assert momentum_probe_rejection_reason(decision) == expected


def test_execution_candidates_bounds_probe_quote_requests_to_top_five():
    decisions = [
        _probe_decision(f"60012{index}.SH", raw_score=72.0 + index)
        for index in range(7)
    ]

    selected = _execution_candidates(decisions, set())

    assert len(selected) == 5
    assert [item["stock_code"] for item in selected] == [
        "600126.SH",
        "600125.SH",
        "600124.SH",
        "600123.SH",
        "600122.SH",
    ]


def test_execution_candidates_only_probe_final_observation_scope():
    decisions = [
        _probe_decision(f"60012{index}.SH", raw_score=72.0 + index)
        for index in range(4)
    ]

    selected = _execution_candidates(
        decisions,
        set(),
        observation_codes={"600120.SH", "600122.SH"},
    )

    assert [item["stock_code"] for item in selected] == [
        "600122.SH", "600120.SH"
    ]


def test_held_risk_decisions_add_missing_holding_without_buy_signal():
    decisions = [{"stock_code": "000001.SZ", "direction": "buy"}]
    positions = [
        {"stock_code": "000001.SZ", "stock_name": "已有候选"},
        {"stock_code": "600000.SH", "stock_name": "未进候选"},
    ]

    result = _add_held_risk_decisions(
        decisions,
        positions,
        trade_date="2026-09-01",
        signal_at="2026-09-01T09:35:00+08:00",
        data_cutoff_at="2026-09-01T09:35:00+08:00",
    )

    assert [item["stock_code"] for item in result] == [
        "000001.SZ", "600000.SH"
    ]
    fallback = result[1]
    assert fallback["position_risk_review"] is True
    assert fallback["actionable"] is False
    assert fallback["direction"] == "neutral"


def test_paper_strategy_executes_probe_at_two_percent_cap(tmp_path):
    database = MarketDatabase(tmp_path / "momentum-probe.db")

    result = database.run_paper_strategy(
        [_probe_decision()],
        "2026-08-27",
        100_000,
        strict_real_data=False,
    )

    assert result["execution_status"] == "executed"
    assert result["actions"][0]["action"] == "BUY"
    assert result["actions"][0]["shares"] == 200
    assert result["actions"][0]["price"] == pytest.approx(9.91)
    assert result["actions"][0]["reason"] == (
        "momentum_probe; raw_score=75.8; max_position=2%"
    )
    assert result["new_position_policy"] == (
        "codex_deep_buy_up_to_20pct_or_confirmed_2pct_observation"
    )


def test_strict_paper_session_allows_one_guarded_momentum_probe(tmp_path):
    database = MarketDatabase(tmp_path / "strict-momentum-probe.db")
    decision = {
        **_probe_decision(),
        "date": "2026-08-27",
        "signal_at": "2026-08-27T09:34:00+08:00",
        "data_cutoff_at": "2026-08-27T09:34:00+08:00",
        "market_price_date": "2026-08-27",
        "market_price_source": "tushare_rt_min",
        "market_price_fetched_at": "2026-08-27T09:35:02+08:00",
        "market_price_exchange_at": "2026-08-27T09:35:00+08:00",
        "strategy_version": "test-v1",
        "industry": "银行",
    }

    result = database.run_paper_strategy(
        [decision],
        "2026-08-27",
        100_000,
        execution_timestamp="2026-08-27T09:35:03+08:00",
        strict_real_data=True,
        trading_day_verified=True,
        is_trading_day=True,
        trading_calendar_source="test_calendar",
    )

    assert result["execution_status"] == "executed"
    assert result["actions"][0]["execution_tier"] == "probe"
    assert result["actions"][0]["price_source"] == "tushare_rt_min"
    assert result["actions"][0]["reason"].startswith("momentum_probe")


def test_codex_timeout_buy_uses_observation_lane_without_false_rejection(tmp_path):
    database = MarketDatabase(tmp_path / "codex-timeout-observation.db")
    decision = _probe_decision(raw_score=74.0)
    evidence = json.loads(decision["evidence"])
    evidence["score_guard"]["reasons"] = []
    decision.update({
        "direction": "buy",
        "ai_score": 74.0,
        "deep_analysis_available": False,
        "deep_analysis_error": "Codex CLI timed out",
    })
    decision["evidence"] = json.dumps(evidence)

    result = database.run_paper_strategy(
        [decision],
        "2026-08-27",
        100_000,
        strict_real_data=False,
    )

    assert result["actions"][0]["action"] == "BUY"
    assert result["actions"][0]["shares"] == 200
    assert result["rejections"] == []


def test_paper_strategy_records_failed_live_probe_confirmation(tmp_path):
    database = MarketDatabase(tmp_path / "momentum-probe-rejection.db")
    decision = _probe_decision(change_pct=5.0)

    result = database.run_paper_strategy(
        [decision],
        "2026-08-27",
        100_000,
        strict_real_data=False,
    )

    assert result["actions"] == []
    assert result["rejections"][0]["reason"] == (
        "momentum_probe_opening_move_too_extended"
    )
    assert database.get_paper_order_rejections()[0]["stock_code"] == "600127.SH"
