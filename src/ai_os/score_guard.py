"""Safety gates between technical scoring and simulated execution."""

from __future__ import annotations

import json
from typing import Any

from src.ai_os.evidence_policy import assess_evidence

MISSING_EVIDENCE_SCORE_CAP = 60.0
FUNDAMENTAL_RISK_SCORE_CAP = 45.0
MARKET_DATA_BLOCK_REASONS = frozenset({
    "market_context_missing",
    "market_data_degraded",
    "market_data_unavailable",
    "technical_data_stale",
    "technical_scan_incomplete",
    "trading_calendar_unverified",
    "universe_metadata_incomplete",
})


def _has_content(value: Any) -> bool:
    if value is None or value is False or value == "":
        return False
    if isinstance(value, dict | list | tuple | set):
        return bool(value)
    return True


def _text_content(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text_content(item) for item in value.values())
    if isinstance(value, list | tuple | set):
        return " ".join(_text_content(item) for item in value)
    return str(value or "")


def _numeric(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def decision_ranking_score(decision: dict[str, Any]) -> float:
    """Return the score used for candidate ranking, never the guarded score."""
    for key in ("ranking_score", "raw_ai_score", "ai_score", "fusion_score"):
        value = _numeric(decision.get(key))
        if value is not None:
            return value
    return 0.0


def decision_research_score(decision: dict[str, Any]) -> float:
    """Return the score that describes the current research conclusion.

    Ranking and research are intentionally separate.  A deep result must not
    be overwritten by the preselection/ranking score when the guard is
    applied a second time later in the pipeline.
    """
    for key in ("deep_score", "action_score", "ai_score", "fusion_score"):
        value = _numeric(decision.get(key))
        if value is not None:
            return value
    return decision_ranking_score(decision)


def decision_sort_key(decision: dict[str, Any]) -> tuple[float, float, float, str]:
    """Return a deterministic descending score key with stable tie breakers."""
    return (
        -decision_ranking_score(decision),
        -(_numeric(decision.get("technical_score"), 0.0) or 0.0),
        -(_numeric(decision.get("discovery_score"), 0.0) or 0.0),
        str(decision.get("stock_code") or "").strip().upper(),
    )


def _market_context_available(item: dict[str, Any]) -> bool:
    """Require a sourced quote before treating market context as trustworthy."""
    return assess_evidence(item).market_complete


def _fundamental_payload(item: dict[str, Any]) -> Any:
    for key in ("fundamentals", "fundamental", "financials", "profit_forecast"):
        if _has_content(item.get(key)):
            return item[key]

    stock_skill = item.get("stock_skill") or {}
    for key in ("fundamentals", "fundamental", "financials", "profit_forecast"):
        if _has_content(stock_skill.get(key)):
            return stock_skill[key]
    return None


def _has_fundamental_risk(payload: Any) -> bool:
    if payload is None:
        return False

    if isinstance(payload, dict):
        for key in (
            "net_profit",
            "forecast_net_profit",
            "expected_net_profit",
            "profit",
        ):
            value = payload.get(key)
            try:
                if value is not None and float(value) < 0:
                    return True
            except (TypeError, ValueError):
                pass

    text = _text_content(payload)
    return any(
        phrase in text
        for phrase in ("预亏", "预计亏损", "净利润为负", "业绩由盈转亏")
    )


def classify_decision_status(decision: dict[str, Any]) -> str:
    """Expose why a decision is not currently an executable order."""
    if decision.get("decision_status") == "review_blocked":
        return "review_blocked"
    reasons = set(decision.get("score_guard_reasons") or [])
    if reasons & MARKET_DATA_BLOCK_REASONS:
        return "data_blocked"
    if "fundamental_loss_risk" in reasons:
        return "risk_blocked"
    if "fundamental_evidence_missing" in reasons:
        return "research_candidate"
    direction = str(decision.get("direction") or "neutral").strip().lower()
    if direction == "buy":
        return "buy_candidate"
    if direction == "sell":
        return "sell_candidate"
    return "hold"


def apply_score_guard(
    decision: dict[str, Any],
    discovery_item: dict[str, Any] | None = None,
    deep_result: dict[str, Any] | None = None,
    additional_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Cap scores when the evidence required for a BUY is incomplete.

    The scanner score remains useful for ranking, but it must not look like an
    executable recommendation when market context or fundamentals are absent.
    A successful deep analysis can satisfy the fundamental evidence gate.
    """
    item = discovery_item or {}
    deep = deep_result or {}
    reasons: list[str] = []
    for reason in additional_reasons or []:
        normalized = str(reason or "").strip()
        if normalized and normalized not in reasons:
            reasons.append(normalized)

    # A deep model result is not an independent market-data source. It may
    # have been generated from stale or incomplete inputs, so it can satisfy
    # the fundamental research gate but never the quote/context gate.
    market_context_available = _market_context_available(item)
    evidence_assessment = assess_evidence(item, deep_result=deep)
    fundamental_payload = _fundamental_payload(item)
    deep_evidence_gaps = deep.get("evidence_gaps") or []
    deep_fundamental_available = bool(deep.get("available")) and not deep_evidence_gaps
    fundamental_available = _has_content(fundamental_payload) or deep_fundamental_available

    hard_fundamental_risk = _has_fundamental_risk(fundamental_payload)
    if deep_fundamental_available:
        hard_fundamental_risk = hard_fundamental_risk or _has_fundamental_risk(
            {
                "decision": deep.get("decision"),
                "thesis": deep.get("thesis"),
            }
        )

    if not market_context_available and "market_context_missing" not in reasons:
        reasons.append("market_context_missing")
    if not fundamental_available:
        reasons.append("fundamental_evidence_missing")
    if hard_fundamental_risk:
        reasons.append("fundamental_loss_risk")
    if decision.get("universe_metadata_complete") is False:
        reasons.append("universe_metadata_incomplete")

    raw_score = decision_ranking_score(decision)
    research_score = decision_research_score(decision)
    predicted_direction = str(
        decision.get("predicted_direction")
        or decision.get("direction")
        or "neutral"
    ).strip().lower()
    review_blocked = decision.get("decision_status") == "review_blocked"
    if review_blocked:
        guarded_score = min(
            _numeric(decision.get("ai_score"), 50.0) or 50.0,
            research_score,
        )
    elif hard_fundamental_risk:
        guarded_score = min(research_score, FUNDAMENTAL_RISK_SCORE_CAP)
    elif reasons:
        guarded_score = min(research_score, MISSING_EVIDENCE_SCORE_CAP)
    else:
        guarded_score = research_score

    decision["raw_ai_score"] = round(raw_score, 1)
    decision["ranking_score"] = round(raw_score, 1)
    decision["research_score"] = round(research_score, 1)
    decision["predicted_direction"] = predicted_direction
    decision["score_guarded"] = bool(reasons)
    decision["score_guard_reasons"] = reasons
    decision["fundamental_evidence_available"] = fundamental_available
    decision["market_evidence_complete"] = evidence_assessment.market_complete
    decision["market_evidence_sources"] = list(evidence_assessment.market_sources)
    decision["market_evidence_reasons"] = list(evidence_assessment.reasons)
    decision["execution_evidence_complete"] = not reasons and not review_blocked
    decision["ai_score"] = round(max(0.0, min(100.0, guarded_score)), 1)
    decision["fusion_score"] = decision["ai_score"]
    decision["action_score"] = decision["ai_score"]
    decision["decision_status"] = classify_decision_status(decision)
    decision["executable_direction"] = (
        decision.get("direction", "neutral") if not reasons else "neutral"
    )
    decision["evidence_status"] = "complete" if not reasons else "incomplete"
    decision["actionability_status"] = (
        "not_actionable" if reasons or review_blocked else "pending_review"
    )
    decision["score_lineage"] = {
        "scanner_score": decision.get("scanner_score"),
        "preselection_base_score": decision.get("preselection_base_score"),
        "preselection_adjustment": decision.get("ai_preselection_score"),
        "preselection_adjusted_score": decision.get(
            "preselection_adjusted_score"
        ),
        "deep_base_score": decision.get("deep_base_score"),
        "deep_score": decision.get("deep_score"),
        "research_score": decision["research_score"],
        "guard_input_score": decision["research_score"],
        "guarded_action_score": decision["action_score"],
        "guard_reasons": reasons,
    }

    if reasons:
        decision["direction"] = "neutral"
        decision["recommendation"] = "回避" if hard_fundamental_risk else "观望"

    # These fields are consumer-facing final state, so clear any stale value
    # left by an earlier stage instead of allowing a ranking BUY to survive a
    # deep Hold/veto result.
    decision["final_direction"] = str(
        decision.get("direction") or "neutral"
    ).strip().lower()
    decision["executable_direction"] = (
        decision["final_direction"]
        if not reasons and not review_blocked
        else "neutral"
    )

    evidence = decision.get("evidence")
    if isinstance(evidence, str) and evidence:
        try:
            evidence_payload = json.loads(evidence)
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence_payload = {}
        evidence_payload["score_guard"] = {
            "raw_score": decision["raw_ai_score"],
            "ranking_score": decision["ranking_score"],
            "research_score": decision["research_score"],
            "guarded_score": decision["ai_score"],
            "action_score": decision["action_score"],
            "guarded": decision["score_guarded"],
            "reasons": reasons,
            "fundamental_evidence_available": fundamental_available,
            "decision_status": decision["decision_status"],
            "score_lineage": decision["score_lineage"],
        }
        decision["evidence"] = json.dumps(evidence_payload, ensure_ascii=False)

    return decision
