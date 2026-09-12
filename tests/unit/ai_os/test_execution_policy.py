import pytest

from src.ai_os.execution_policy import (
    ExecutionTier,
    FlowState,
    classify_execution_flow,
    evaluate_entry_execution,
    is_probe_promotion_candidate,
    probe_exit_reason,
)


def _decision(**updates) -> dict:
    decision = {
        "action_score": 76,
        "ai_score": 76,
        "technical_score": 70,
        "strategy_confirmations": 3,
        "pre_gate_direction": "buy",
        "final_direction": "buy",
        "final_review_required": False,
        "gate_reasons": [],
        "non_flow_gates_passed": True,
        "market_flow": {"main_net": 120},
    }
    decision.update(updates)
    return decision


def _missing_decision(**updates) -> dict:
    decision = {
        "final_direction": "neutral",
        "flow_status": "missing",
        "market_flow": {
            "status": "missing",
            "fallback_attempted": True,
            "fallback_status": "exhausted",
        },
        "gate_reasons": ["fund_flow_missing"],
    }
    decision.update(updates)
    return _decision(**decision)


def test_positive_flow_keeps_normal_execution_tier():
    result = evaluate_entry_execution(_decision())

    assert result["tier"] == ExecutionTier.NORMAL.value
    assert result["flow_state"] == FlowState.POSITIVE.value
    assert is_probe_promotion_candidate(_decision()) is True


def test_negative_flow_is_never_a_probe():
    result = evaluate_entry_execution(
        _decision(
            flow_status="negative",
            market_flow={"status": "negative", "main_net": -1},
            final_direction="neutral",
        )
    )

    assert result["tier"] == ExecutionTier.BLOCKED.value
    assert result["reason"] == "fund_flow_negative"


def test_missing_flow_with_exhausted_fallback_is_bounded_probe():
    result = evaluate_entry_execution(_missing_decision())

    assert result["tier"] == ExecutionTier.PROBE.value
    assert result["fallback_attempted"] is True
    assert result["fallback_status"] == "exhausted"


def test_missing_flow_without_fallback_attempt_is_blocked():
    result = evaluate_entry_execution(
        _missing_decision(
            market_flow={"status": "missing"},
            fallback_attempted=False,
        )
    )

    assert result["tier"] == ExecutionTier.BLOCKED.value
    assert result["reason"] == "flow_fallback_not_attempted"


def test_invalid_flow_can_probe_only_when_it_is_the_only_blocker():
    decision = _missing_decision(
        flow_status="invalid",
        market_flow={
            "main_net": "not-a-number",
            "fallback_attempted": True,
            "fallback_status": "incomplete",
        },
        gate_reasons=["fund_flow_invalid"],
    )
    result = evaluate_entry_execution(decision)

    assert classify_execution_flow(decision) is FlowState.INVALID
    assert result["tier"] == ExecutionTier.PROBE.value


def test_multiple_non_flow_blockers_never_probe():
    result = evaluate_entry_execution(
        _missing_decision(gate_reasons=["fund_flow_missing", "score_guard_veto"])
    )

    assert result["tier"] == ExecutionTier.BLOCKED.value
    assert "score_guard_veto" in result["reason"]


def test_proxy_volume_is_missing_not_positive_flow():
    decision = _decision(
        final_direction="neutral",
        flow_status="proxy",
        market_flow={
            "status": "proxy",
            "flow_signal": 0.4,
            "source": "tencent_active_volume_proxy",
            "fallback_attempted": True,
            "fallback_status": "proxy_only",
        },
    )

    assert classify_execution_flow(decision) is FlowState.MISSING
    assert evaluate_entry_execution(decision)["tier"] == ExecutionTier.PROBE.value


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"current_price": 9.5, "holding_days": 1}, "probe_stop_loss=-4%;return=-5.0%"),
        (
            {"current_price": 10.2, "holding_days": 1, "decision": _decision(
                flow_status="negative", market_flow={"main_net": -1}
            )},
            "probe_flow_negative",
        ),
        ({"current_price": 10.2, "holding_days": 3}, "probe_unconfirmed_after=3d"),
        ({"current_price": 10.2, "holding_days": 5}, "probe_max_holding_days=5"),
    ],
)
def test_probe_exit_lifecycle(updates, expected):
    decision = updates.pop("decision", _missing_decision())
    assert probe_exit_reason(
        {"execution_tier": "probe", "avg_cost": 10.0},
        decision,
        stop_loss_pct=4,
        confirmation_days=3,
        max_holding_days=5,
        **updates,
    ) == expected


def test_probe_exit_ignores_normal_position():
    assert probe_exit_reason(
        {"execution_tier": "normal", "avg_cost": 10},
        _missing_decision(),
        9,
        10,
    ) == ""
