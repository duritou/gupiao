"""Evidence-first allocation of candidates to expensive AI analysis."""

from __future__ import annotations

from typing import Any

from src.ai_os.evidence_policy import assess_evidence
from src.ai_os.score_guard import decision_ranking_score


def has_market_evidence(decision: dict[str, Any]) -> bool:
    """Return whether a candidate has a usable, sourced market context."""
    return assess_evidence(decision).market_complete


def _candidate_rank(decision: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        decision_ranking_score(decision),
        float(decision.get("technical_score") or 0),
        float(decision.get("discovery_score") or 0),
        str(decision.get("stock_code") or "").strip().upper(),
    )


def allocate_deep_candidates(
    decisions: list[dict[str, Any]],
    target: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Choose deep-analysis slots only from candidates with market evidence.

    Technical ranking remains the ordering signal, but it is applied after
    evidence eligibility. This prevents the previous failure mode where the
    highest technical names consumed all Codex slots with empty evidence.
    """
    eligible: list[dict[str, Any]] = []
    ineligible_count = 0
    for decision in decisions:
        eligible_for_deep = (
            has_market_evidence(decision)
            and decision.get("universe_metadata_complete", True) is not False
        )
        decision["deep_candidate_eligible"] = eligible_for_deep
        if eligible_for_deep:
            eligible.append(decision)
        else:
            ineligible_count += 1
            if decision.get("universe_metadata_complete", True) is False:
                decision["deep_candidate_exclusion_reason"] = (
                    "universe_metadata_incomplete"
                )
            else:
                assessment = assess_evidence(decision)
                decision["deep_candidate_exclusion_reason"] = ";".join(
                    assessment.reasons
                ) or "market_evidence_incomplete"

    ranked = sorted(eligible, key=_candidate_rank, reverse=True)
    limit = max(0, int(target))
    selected = ranked[:limit]
    selected_codes = {
        str(item.get("stock_code") or "").strip().upper() for item in selected
    }
    for decision in eligible:
        code = str(decision.get("stock_code") or "").strip().upper()
        if code not in selected_codes:
            decision["deep_candidate_exclusion_reason"] = "deep_analysis_capacity"

    return selected, {
        "eligible_count": len(eligible),
        "ineligible_count": ineligible_count,
        "selected_count": len(selected),
    }
