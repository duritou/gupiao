"""Publication gates for trustworthy AI stock recommendations."""

from __future__ import annotations

from typing import Any

from src.ai_os.score_guard import decision_sort_key
from src.domain.models.selection_decision import normalize_decision_fields

_PUBLISHABLE_STATUSES = frozenset({"buy_candidate", "sell_candidate", "hold"})
_BLOCKED_STATUSES = frozenset({"data_blocked", "risk_blocked", "review_blocked"})

DISPLAY_STATE_LABELS = {
    "research_pending": "分析待完成",
    "research_blocked": "证据待补充",
    "hold": "观望",
    "reduce": "减持/回避",
    "buy_candidate": "买入候选·待确认",
    "execution_ready": "买入条件已满足",
    "expired": "条件失效·待重评",
}


def _unique_reasons(*groups: list[str] | None) -> list[str]:
    result: list[str] = []
    for group in groups:
        for reason in group or []:
            value = str(reason or "").strip()
            if value and value not in result:
                result.append(value)
    return result


def is_publishable_recommendation(decision: dict[str, Any]) -> bool:
    """Return whether a decision has enough evidence for the recommendation list."""
    return (
        bool(decision.get("deep_analysis_available"))
        and bool(decision.get("execution_evidence_complete"))
        and not bool(decision.get("score_guard_reasons"))
        and not bool(decision.get("publication_blocked"))
        and str(decision.get("decision_status") or "") in _PUBLISHABLE_STATUSES
    )


def is_actionable_recommendation(decision: dict[str, Any]) -> bool:
    """Return whether a published deep result is an approved BUY candidate."""
    if not is_publishable_recommendation(decision):
        return False
    if str(decision.get("direction") or "").strip().lower() != "buy":
        return False
    from src.ai_os.trading_policy import is_deep_buy_approved

    return is_deep_buy_approved(decision)


def recommendation_tier(decision: dict[str, Any]) -> str:
    """Classify what a consumer is allowed to do with a decision."""
    status = str(decision.get("decision_status") or "")
    if status in _BLOCKED_STATUSES or decision.get("publication_blocked"):
        return "data_blocked"
    if is_actionable_recommendation(decision):
        return "actionable_candidate"
    if is_publishable_recommendation(decision):
        return "research_complete"
    if decision.get("deep_analysis_available"):
        return "research_candidate"
    return "technical_watchlist"


def decision_display_state(decision: dict[str, Any]) -> str:
    """Return the single state that should be shown as the primary UI result."""
    status = str(decision.get("decision_status") or "").strip().lower()
    rating = str(decision.get("deep_rating") or "").strip().lower()
    direction = str(
        decision.get("final_direction")
        or decision.get("direction")
        or "neutral"
    ).strip().lower()

    # Repair legacy rows that persisted a pre-review BUY direction alongside
    # a later deep Hold/Underweight conclusion before the new contract existed.
    if rating in {"buy", "overweight"}:
        decision["final_direction"] = "buy"
    elif rating in {"underweight", "sell", "reduce"}:
        decision["final_direction"] = "sell"
    elif rating in {"hold", "neutral"}:
        decision["final_direction"] = "neutral"
    else:
        decision["final_direction"] = direction

    if rating in {"underweight", "sell", "reduce"} or direction == "sell":
        return "reduce"
    if status in _BLOCKED_STATUSES:
        return "research_blocked"
    if rating in {"buy", "overweight"}:
        approved = decision.get("final_buy_approved") is True
        if (
            approved
            and decision.get("execution_disposition") == "normal"
            and decision.get("execution_quote_verified") is True
        ):
            return "execution_ready"
        return "buy_candidate"
    if rating in {"hold", "neutral"} or decision.get("deep_analysis_available"):
        return "hold"
    if direction == "buy":
        return "buy_candidate"
    return "research_pending"


def apply_decision_display_fields(decision: dict[str, Any]) -> dict[str, Any]:
    """Attach explicit display scores so ranking cannot masquerade as research."""
    display_state = decision_display_state(decision)
    deep_score = decision.get("deep_score")
    research_score = decision.get("research_score")
    if research_score is None and deep_score is not None:
        research_score = deep_score
    primary_score = (
        research_score
        if research_score is not None
        else decision.get("action_score", decision.get("ai_score"))
    )
    try:
        primary_score = round(float(primary_score), 1) if primary_score is not None else None
    except (TypeError, ValueError):
        primary_score = None

    if research_score is not None:
        try:
            research_score = round(float(research_score), 1)
        except (TypeError, ValueError):
            research_score = None

    decision["display_state"] = display_state
    decision["display_state_label"] = DISPLAY_STATE_LABELS[display_state]
    decision["primary_score"] = primary_score
    decision["primary_score_label"] = (
        "研究评分" if decision.get("deep_analysis_available") or research_score is not None
        else "行动评分"
    )
    decision["research_score"] = research_score
    decision["ranking_score_label"] = "机会排名分"
    decision["score_display"] = {
        "ranking_score": decision.get("ranking_score"),
        "research_score": research_score,
        "action_score": decision.get("action_score"),
        "display_score": primary_score,
        "display_label": decision["primary_score_label"],
        "guarded": bool(decision.get("score_guarded")),
        "guard_reasons": list(decision.get("score_guard_reasons") or []),
    }
    decision["execution_status_label"] = {
        "normal": "执行条件已通过",
        "probe": "仅纸面试探",
        "blocked": "执行已阻断",
        "pending": "等待执行确认",
    }.get(
        str(decision.get("execution_disposition") or "pending"),
        "等待执行确认",
    )
    return decision


def apply_publication_quality(
    decision: dict[str, Any],
    global_block_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Annotate a decision without hiding why it is not publishable."""
    normalize_decision_fields(decision)
    reasons = _unique_reasons(
        list(decision.get("score_guard_reasons") or []),
        global_block_reasons,
    )
    decision["publication_blocked"] = bool(reasons)
    decision["publication_block_reasons"] = reasons
    decision["recommendation_tier"] = recommendation_tier(decision)
    decision["actionable"] = is_actionable_recommendation(decision)
    apply_decision_display_fields(decision)
    return decision


def sort_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort by raw/ranking score, then deterministic technical tie breakers."""
    return sorted(decisions, key=decision_sort_key)
