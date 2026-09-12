"""Flow-aware paper execution policy.

The selector remains responsible for ranking and direction.  This module only
decides how an already-produced decision may enter the paper ledger when the
fund-flow provider is incomplete.
"""

from __future__ import annotations

from enum import Enum
import math
from typing import Any


class ExecutionTier(str, Enum):
    NORMAL = "normal"
    PROBE = "probe"
    BLOCKED = "blocked"


class FlowState(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MISSING = "missing"
    INVALID = "invalid"


class ProbeStatus(str, Enum):
    NONE = "none"
    OPEN = "open"
    PROMOTED = "promoted"
    EXITED_NEGATIVE = "exited_negative"
    EXITED_UNCONFIRMED = "exited_unconfirmed"
    EXITED_STOP_LOSS = "exited_stop_loss"
    EXITED_MAX_HOLDING = "exited_max_holding"


FLOW_BLOCK_REASONS = frozenset({
    "fund_flow_positive_required",
    "fund_flow_negative",
    "fund_flow_missing",
    "fund_flow_invalid",
    "flow_fallback_not_attempted",
    "flow_fallback_incomplete",
})


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text.rstrip("%"))
    except (TypeError, ValueError):
        return None


def classify_execution_flow(decision: dict[str, Any]) -> FlowState:
    """Classify flow for execution, treating proxy volume as missing.

    Tencent active-volume proxy is useful for ranking, but it is not main-money
    flow and therefore cannot authorize a normal fill.
    """
    flow = decision.get("market_flow") or {}
    declared = str(decision.get("flow_status") or flow.get("status") or "").lower()
    source = str(
        decision.get("flow_source") or flow.get("source") or ""
    ).lower()
    if declared == "proxy" or "active_volume_proxy" in source:
        return FlowState.MISSING
    if declared in {state.value for state in FlowState}:
        return FlowState(declared)

    main_net = _number(flow.get("main_net"))
    flow_signal = _number(flow.get("flow_signal"))
    if main_net is not None and main_net > 0:
        return FlowState.POSITIVE
    if flow_signal is not None and flow_signal > 0.02:
        return FlowState.POSITIVE
    if main_net is not None or flow_signal is not None:
        return FlowState.NEGATIVE
    supplied = any(
        value not in (None, "", "-")
        for value in (flow.get("main_net"), flow.get("flow_signal"))
    )
    return FlowState.INVALID if supplied else FlowState.MISSING


def flow_execution_metadata(decision: dict[str, Any]) -> dict[str, Any]:
    """Return normalized flow evidence without changing selector fields."""
    flow = decision.get("market_flow") or {}
    state = classify_execution_flow(decision)
    attempted = bool(
        decision.get("fallback_attempted")
        or decision.get("flow_fallback_attempted")
        or flow.get("fallback_attempted")
        or flow.get("attempted")
    )
    fallback_status = str(
        decision.get("fallback_status")
        or decision.get("flow_fallback_status")
        or flow.get("fallback_status")
        or ""
    ).strip().lower()
    if not fallback_status:
        fallback_status = (
            "confirmed" if state is FlowState.POSITIVE else
            "negative" if state is FlowState.NEGATIVE else
            "not_attempted" if not attempted else "incomplete"
        )
    source = str(
        decision.get("flow_source") or flow.get("source") or ""
    ).strip()
    sources = list(decision.get("flow_sources") or [])
    if source and source not in sources:
        sources.append(source)
    return {
        "flow_state": state.value,
        "flow_sources": sources,
        "fallback_attempted": attempted,
        "fallback_status": fallback_status,
    }


def _non_flow_reasons(decision: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for raw in (
        decision.get("gate_reasons") or [],
        decision.get("score_guard_reasons") or [],
    ):
        for reason in raw:
            normalized = str(reason or "").strip()
            if normalized and normalized not in FLOW_BLOCK_REASONS and normalized not in reasons:
                reasons.append(normalized)
    if decision.get("non_flow_gates_passed") is False and "non_flow_gate_failed" not in reasons:
        reasons.append("non_flow_gate_failed")
    if decision.get("decision_status") == "review_blocked":
        reasons.append("final_review_veto")
    if (
        decision.get("final_review_required") is True
        and decision.get("final_buy_approved") is not True
    ):
        reasons.append("final_buy_not_approved")
    deep_rating = str(decision.get("deep_rating") or "").strip().lower()
    if deep_rating and deep_rating not in {"buy", "overweight"}:
        reasons.append("deep_rating_not_buy")
    return reasons


def _pre_gate_buy(decision: dict[str, Any]) -> bool:
    explicit = str(
        decision.get("pre_gate_direction")
        or decision.get("pre_execution_direction")
        or ""
    ).strip().lower()
    if explicit:
        return explicit == "buy"
    score = float(decision.get("action_score") or decision.get("ai_score") or 0)
    technical = float(decision.get("technical_score") or 0)
    confirmations = int(
        decision.get("strategy_confirmations")
        or decision.get("buy_signals")
        or 0
    )
    return score >= 65 and technical >= 55 and confirmations >= 2


def evaluate_entry_execution(
    decision: dict[str, Any],
    *,
    allow_probe: bool = True,
    paper_mode: bool = False,
) -> dict[str, Any]:
    """Return the execution tier for a final selector decision."""
    metadata = flow_execution_metadata(decision)
    state = FlowState(metadata["flow_state"])
    direction = str(
        decision.get("executable_direction")
        or decision.get("final_direction")
        or decision.get("direction")
        or "neutral"
    ).strip().lower()
    non_flow_reasons = _non_flow_reasons(decision)
    original_buy = _pre_gate_buy(decision)
    normal_buy = direction == "buy" and not non_flow_reasons
    if state is FlowState.POSITIVE:
        if normal_buy:
            return {"tier": ExecutionTier.NORMAL.value, "reason": "flow_positive", **metadata}
        # Explicit paper-only research exploration. Never turn Hold, a veto,
        # missing approval or weak/non-finite inputs into an entry.
        score = _number(decision.get("action_score", decision.get("ai_score")))
        technical = _number(decision.get("technical_score"))
        if (
            paper_mode and allow_probe and original_buy and not non_flow_reasons
            and direction == "neutral"
            and decision.get("deep_analysis_available") is True
            and str(decision.get("deep_rating") or "").lower() in {"buy", "overweight"}
            and decision.get("final_review_available") is True
            and decision.get("final_buy_approved") is True
            and str(decision.get("final_review_verdict") or "").lower() == "approve"
            and decision.get("execution_evidence_complete") is True
            and score is not None and math.isfinite(score) and score >= 65
            and technical is not None and math.isfinite(technical) and technical >= 55
        ):
            return {"tier": ExecutionTier.PROBE.value,
                    "reason": "confirmed_research_paper_probe", **metadata}
        return {
            "tier": ExecutionTier.BLOCKED.value,
            "reason": ";".join(non_flow_reasons) or "not_a_buy_signal",
            **metadata,
        }
    if state is FlowState.NEGATIVE:
        return {"tier": ExecutionTier.BLOCKED.value, "reason": "fund_flow_negative", **metadata}
    if not allow_probe:
        return {"tier": ExecutionTier.BLOCKED.value, "reason": f"fund_flow_{state.value}", **metadata}
    if not metadata["fallback_attempted"]:
        return {"tier": ExecutionTier.BLOCKED.value, "reason": "flow_fallback_not_attempted", **metadata}
    if metadata["fallback_status"] not in {"exhausted", "proxy_only", "incomplete"}:
        return {"tier": ExecutionTier.BLOCKED.value, "reason": "flow_fallback_incomplete", **metadata}
    if not original_buy:
        return {"tier": ExecutionTier.BLOCKED.value, "reason": "pre_gate_not_buy", **metadata}
    if non_flow_reasons:
        return {
            "tier": ExecutionTier.BLOCKED.value,
            "reason": ";".join(non_flow_reasons),
            **metadata,
        }
    return {
        "tier": ExecutionTier.PROBE.value,
        "reason": f"fund_flow_{state.value}_probe",
        **metadata,
    }


def is_flow_probe_candidate(decision: dict[str, Any]) -> bool:
    return evaluate_entry_execution(decision)["tier"] == ExecutionTier.PROBE.value


def probe_exit_reason(
    position: dict[str, Any],
    decision: dict[str, Any],
    current_price: float,
    holding_days: int,
    *,
    stop_loss_pct: float = 4.0,
    confirmation_days: int = 3,
    max_holding_days: int = 5,
) -> str:
    """Return a probe-specific exit reason; empty means keep observing."""
    if str(position.get("execution_tier") or "normal").lower() != "probe":
        return ""
    cost = float(position.get("avg_cost") or 0)
    price = float(current_price or 0)
    if cost <= 0 or price <= 0:
        return ""
    return_pct = (price / cost - 1.0) * 100
    if return_pct <= -abs(float(stop_loss_pct)) + 1e-6:
        return f"probe_stop_loss=-{float(stop_loss_pct):.0f}%;return={return_pct:.1f}%"
    state = classify_execution_flow(decision)
    if state is FlowState.NEGATIVE:
        return "probe_flow_negative"
    if holding_days >= max(1, int(max_holding_days)):
        return f"probe_max_holding_days={int(max_holding_days)}"
    if holding_days >= max(1, int(confirmation_days)) and state is not FlowState.POSITIVE:
        return f"probe_unconfirmed_after={int(confirmation_days)}d"
    return ""


def is_probe_promotion_candidate(decision: dict[str, Any]) -> bool:
    result = evaluate_entry_execution(decision, allow_probe=False)
    return result["tier"] == ExecutionTier.NORMAL.value
