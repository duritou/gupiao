"""Cross-sectional multi-strategy scoring for the broad A-share scan."""

from __future__ import annotations

import json
from statistics import mean

from src.ai_os.execution_policy import classify_execution_flow, flow_execution_metadata


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _percentile_ranks(values: list[float]) -> list[float]:
    """Return tie-aware percentile ranks while preserving input order."""
    if len(values) <= 1:
        return [float(values[0])] if values else []
    sorted_values = sorted(values)
    positions: dict[float, float] = {}
    index = 0
    while index < len(sorted_values):
        value = sorted_values[index]
        end = index + 1
        while end < len(sorted_values) and sorted_values[end] == value:
            end += 1
        average_index = (index + end - 1) / 2
        positions[value] = average_index / (len(values) - 1) * 100
        index = end
    return [positions[value] for value in values]


def _strategy_raw(decision: dict) -> dict[str, float]:
    return {
        "trend": mean([
            float(decision.get("macd_score", 50)),
            float(decision.get("ma_score", 50)),
        ]),
        "reversal": mean([
            float(decision.get("rsi_score", 50)),
            float(decision.get("kdj_score", 50)),
        ]),
        "volume": float(decision.get("volume_score", 50)),
    }


def flow_status(decision: dict) -> str:
    """Classify flow evidence without allowing malformed provider data to crash.

    ``missing`` means no provider supplied a value; ``invalid`` means a value
    was supplied but could not be parsed; ``negative`` is a valid non-positive
    flow.  Only ``positive`` may satisfy the BUY flow confirmation.
    """
    # Keep selector and execution semantics identical. In particular, an
    # active-volume proxy is useful context but is not verified main-money
    # flow and must remain ``missing`` rather than authorizing a BUY gate.
    return classify_execution_flow(decision).value


def flow_positive(decision: dict) -> bool:
    return flow_status(decision) == "positive"


def _flow_positive(decision: dict) -> bool:
    return flow_positive(decision)


def refresh_execution_gate(decision: dict) -> None:
    """Re-evaluate the existing gate after later evidence is attached.

    Candidate evidence enrichment runs after cross-sectional scoring.  Only
    gate-derived fields are refreshed here: scores, ranks and the selector's
    weighting formula are intentionally untouched.  A positive flow packet
    can clear the flow blocker only when the already-computed non-flow gates
    pass; it can never create a BUY on its own.
    """
    action_score = float(
        decision.get("ranking_score")
        or decision.get("ai_score")
        or decision.get("fusion_score")
        or 0
    )
    technical_score = float(decision.get("technical_score") or 0)
    confirmations = int(
        decision.get("strategy_confirmations")
        or decision.get("buy_signals")
        or 0
    )
    execution_flow_state = flow_status(decision)
    non_flow_gates_passed = (
        action_score >= 65
        and technical_score >= 55
        and confirmations >= 2
    )
    buy_gate = non_flow_gates_passed and execution_flow_state == "positive"
    gate_reasons = [
        str(reason)
        for reason in (decision.get("gate_reasons") or [])
        if not str(reason).startswith("fund_flow_")
    ]
    if not non_flow_gates_passed:
        if action_score < 65:
            gate_reasons.append("action_score_below_buy_gate")
        if technical_score < 55:
            gate_reasons.append("technical_score_below_buy_gate")
        if confirmations < 2:
            gate_reasons.append("technical_confirmation_insufficient")
    if execution_flow_state != "positive":
        gate_reasons.append(f"fund_flow_{execution_flow_state}")

    direction = (
        "buy" if buy_gate
        else "sell" if action_score < 35
        else "neutral"
    )
    decision["direction"] = direction
    decision["final_direction"] = direction
    decision["pre_gate_direction"] = (
        "buy" if non_flow_gates_passed
        else "sell" if action_score < 35
        else "neutral"
    )
    decision["non_flow_gates_passed"] = non_flow_gates_passed
    decision["flow_status"] = execution_flow_state
    decision.update(flow_execution_metadata(decision))
    decision["flow_status"] = decision["flow_state"]
    decision["gate_reasons"] = list(dict.fromkeys(gate_reasons))
    decision["recommendation"] = (
        "强烈买入" if direction == "buy" and action_score >= 80
        else "买入" if direction == "buy"
        else "卖出" if direction == "sell"
        else "观察"
    )


def apply_cross_sectional_scores(
    decisions: list[dict],
    technical_weight: float = 0.70,
    discovery_weight: float = 0.20,
    learning_weight: float = 0.10,
    rank_weight: float = 0.70,
) -> None:
    """Mutate candidates with auditable strategy ranks and final scores."""
    if not decisions:
        return
    raw_by_strategy = [_strategy_raw(decision) for decision in decisions]
    ranks = {
        strategy: _percentile_ranks([item[strategy] for item in raw_by_strategy])
        for strategy in ("trend", "reversal", "volume")
    }

    for index, decision in enumerate(decisions):
        raw = raw_by_strategy[index]
        strategy_scores = {
            strategy: round(
                rank_weight * ranks[strategy][index] + (1 - rank_weight) * raw[strategy],
                2,
            )
            for strategy in raw
        }
        technical_score = (
            0.40 * strategy_scores["trend"]
            + 0.30 * strategy_scores["reversal"]
            + 0.30 * strategy_scores["volume"]
        )
        confirmations = sum(score >= 60 for score in strategy_scores.values())
        learning_adjustment = float(decision.get("learning_adjustment") or 0)
        learning_score = _clamp(50 + learning_adjustment * 4)
        discovery_available = bool(decision.get("market_sources"))
        if discovery_available:
            adaptive_score = (
                technical_weight * technical_score
                + discovery_weight * float(decision.get("discovery_score", 50))
                + learning_weight * learning_score
            )
        else:
            adaptive_score = 0.85 * technical_score + 0.15 * learning_score
        adaptive_score = _clamp(adaptive_score)
        execution_flow_state = classify_execution_flow(decision).value
        non_flow_gates_passed = (
            adaptive_score >= 65
            and technical_score >= 55
            and confirmations >= 2
        )
        buy_gate = (
            adaptive_score >= 65
            and technical_score >= 55
            and confirmations >= 2
            and flow_positive(decision)
        )
        gate_reasons: list[str] = []
        if adaptive_score < 65:
            gate_reasons.append("action_score_below_buy_gate")
        if technical_score < 55:
            gate_reasons.append("technical_score_below_buy_gate")
        if confirmations < 2:
            gate_reasons.append("technical_confirmation_insufficient")
        if execution_flow_state != "positive":
            gate_reasons.append(f"fund_flow_{execution_flow_state}")
        direction = "buy" if buy_gate else "sell" if adaptive_score < 35 else "neutral"

        decision["raw_technical_score"] = decision.get("technical_score", 50)
        decision["technical_score"] = round(technical_score, 1)
        decision["strategy_scores"] = strategy_scores
        decision["strategy_confirmations"] = confirmations
        # This is the candidate-ranking score. Execution may later apply an
        # evidence guard, but that guarded value must not reorder candidates.
        decision["ranking_score"] = round(adaptive_score, 1)
        decision["ai_score"] = round(adaptive_score, 1)
        decision["fusion_score"] = round(adaptive_score, 1)
        decision["direction"] = direction
        decision["final_direction"] = direction
        decision["pre_gate_direction"] = (
            "buy" if non_flow_gates_passed
            else "sell" if adaptive_score < 35
            else "neutral"
        )
        decision["buy_signals"] = confirmations
        decision["flow_status"] = flow_status(decision)
        decision.update(flow_execution_metadata(decision))
        decision["non_flow_gates_passed"] = non_flow_gates_passed
        decision["gate_reasons"] = gate_reasons
        decision["execution_disposition"] = "pending"
        decision["recommendation"] = (
            "强烈买入" if direction == "buy" and adaptive_score >= 80
            else "买入" if direction == "buy"
            else "卖出" if direction == "sell"
            else "观察"
        )
        decision["confidence"] = round(
            min(0.95, abs(adaptive_score - 50) / 50 * 0.8 + 0.3), 3
        )
        try:
            evidence = json.loads(str(decision.get("evidence") or "{}"))
            evidence["technical"] = {
                **(evidence.get("technical") or {}),
                "raw_score": decision["raw_technical_score"],
                "cross_sectional_score": decision["technical_score"],
                "strategy_scores": strategy_scores,
                "confirmations": confirmations,
                "policy": "70% percentile rank + 30% absolute strategy score",
            }
            evidence["fusion_policy"] = {
                "technical_weight": technical_weight,
                "discovery_weight": discovery_weight,
                "learning_weight": learning_weight,
                "discovery_available": discovery_available,
            }
            decision["evidence"] = json.dumps(evidence, ensure_ascii=False)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
