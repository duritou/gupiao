"""Pure classification for distinguishing abstention causes in a pipeline run."""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.ai_os.execution_policy import evaluate_entry_execution

STAGE_ACCEPTANCE_SCHEMA_VERSION = "2026-09-09.v1"
PAPER_LIVENESS_LOG_LIMIT = 100


def _int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _ratio(value: int, denominator: int) -> float | None:
    """Return a bounded ratio, keeping a zero denominator explicitly unknown."""
    if denominator <= 0:
        return None
    return round(max(0, min(value, denominator)) / denominator, 4)


def _component_counts(states: list[str], required: bool = True) -> dict[str, Any]:
    required_count = len(states) if required else 0
    counts = Counter(states)
    available = counts.get("available", 0)
    return {
        "required_count": required_count,
        "available_count": available,
        "fresh_count": counts.get("fresh", 0),
        "missing_count": counts.get("missing", 0),
        "invalid_count": counts.get("invalid", 0),
        "stale_count": counts.get("stale", 0),
        "unknown_count": counts.get("unknown", 0),
        "expected_unavailable_count": counts.get("expected_unavailable", 0),
        "not_required_count": len(states) - required_count,
        "coverage_ratio": _ratio(available, required_count),
        "state_counts": dict(counts),
    }


def _stage(
    name: str,
    target: int,
    attempted: int,
    completed: int,
    *,
    skipped: int = 0,
    failed: int = 0,
    unverified: int = 0,
    status: str | None = None,
    reason_codes: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one stage record without silently dropping failed candidates."""
    target = max(0, int(target))
    attempted = max(0, int(attempted))
    completed = max(0, min(int(completed), target))
    skipped = max(0, min(int(skipped), target))
    failed = max(0, min(int(failed), target))
    unverified = max(0, min(int(unverified), target))
    if status is None:
        if target == 0:
            status = "not_requested"
        elif failed > 0:
            status = "partial"
        elif unverified > 0 or completed < target:
            status = "unverified" if completed == 0 and attempted == 0 else "partial"
        else:
            status = "completed"
    payload: dict[str, Any] = {
        "name": name,
        "target_count": target,
        "attempted_count": attempted,
        "completed_count": completed,
        "skipped_count": skipped,
        "failed_count": failed,
        "unverified_count": unverified,
        "coverage_ratio": _ratio(completed, target),
        "status": status,
        "reason_codes": list(dict.fromkeys(reason_codes or [])),
    }
    if extra:
        payload.update(extra)
    return payload


def _deep_members(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the frozen Deep set, excluding capacity-skipped shortlist rows."""
    return [
        decision for decision in decisions
        if decision.get("deep_candidate_eligible") is True
        and not str(decision.get("deep_candidate_exclusion_reason") or "").strip()
    ]


def _component_state(value: Any, *, available_when: bool = True) -> str:
    if not isinstance(value, dict):
        return "unknown"
    status = str(value.get("status") or "").strip().lower()
    if status in {"invalid", "error", "failed"}:
        return "invalid"
    if status in {"stale", "outdated"}:
        return "stale"
    if status in {"available", "complete", "fresh", "live"} and available_when:
        return "available"
    if status in {"partial", "incomplete"}:
        return "stale"
    if value.get("available") is True and available_when:
        return "available"
    if value:
        return "missing"
    return "unknown"


def _deep_stock_audit(
    decision: dict[str, Any], target_trade_date: str = ""
) -> dict[str, Any]:
    consumption = decision.get("deep_evidence_consumption") or {}
    financial = consumption.get("financials") or {}
    flow = consumption.get("fund_flow") or {}
    kline = decision.get("deep_kline_evidence") or {}
    components = consumption.get("components") or {}
    financial_state = _component_state(financial)
    if financial_state == "available" and financial.get("history_complete") is False:
        financial_state = "stale"
    flow_state = _component_state(flow)
    if flow_state == "available":
        requested = _int(flow.get("requested_days"))
        rows = _int(flow.get("row_count"))
        if requested and rows < requested:
            flow_state = "stale"
        flow_dates = [
            str(row.get("data_date") or row.get("trade_date") or "")
            for row in (flow.get("rows") or [])
            if isinstance(row, dict)
        ]
        flow_latest_date = max(flow_dates, default="")
        if target_trade_date and flow_latest_date and flow_latest_date < target_trade_date:
            flow_state = "stale"
    kline_state = "available" if kline.get("available") is True else "missing"
    kline_date = str(kline.get("visible_last_date") or "")
    if kline_state == "available" and target_trade_date and kline_date:
        if kline_date < target_trade_date:
            kline_state = "stale"
    announcement = components.get("announcements")
    announcement_state = _component_state(announcement)
    if isinstance(announcement, dict) and announcement.get("status") == "empty":
        # An empty announcement result is not evidence of a source failure;
        # keep it explicit so it cannot be mistaken for available content.
        announcement_state = "expected_unavailable"
    input_state = (
        "available"
        if consumption.get("analysis_input_sha256")
        and decision.get("deep_input_fingerprint")
        else "unknown"
    )
    final_input_state = (
        "available" if decision.get("final_review_input_sha256") else "unknown"
    )
    gaps = []
    for component, state in {
        "deep_kline": kline_state,
        "deep_financial_history": financial_state,
        "deep_fund_flow": flow_state,
        "deep_announcements": announcement_state,
        "deep_input": input_state,
    }.items():
        if state not in {"available", "not_required", "expected_unavailable"}:
            gaps.append(f"{component}_{state}")
    if decision.get("final_review_available") is True and final_input_state != "available":
        gaps.append("final_review_input_unknown")
    return {
        "stock_code": str(decision.get("stock_code") or ""),
        "stage_membership": ["technical_shortlist", "deep_research"]
        + (["final_review"] if decision.get("final_review_available") is not None else []),
        "required_for_stage": {
            "deep_kline": True,
            "deep_financial_history": True,
            "deep_fund_flow": True,
            "deep_announcements": True,
            "deep_input": True,
            "final_review_input": decision.get("final_review_available") is not None,
        },
        "component_status": {
            "deep_kline": kline_state,
            "deep_financial_history": financial_state,
            "deep_fund_flow": flow_state,
            "deep_announcements": announcement_state,
            "deep_input": input_state,
            "final_review_input": final_input_state,
        },
        "evidence_gaps": gaps,
        "evidence_ref": {
            "deep_input_fingerprint": str(decision.get("deep_input_fingerprint") or ""),
            "analysis_input_sha256": str(consumption.get("analysis_input_sha256") or ""),
            "final_review_input_sha256": str(decision.get("final_review_input_sha256") or ""),
        },
        "actual_data_date": str(
            kline_date
            or max(
                [
                    str(row.get("data_date") or row.get("trade_date") or "")
                    for row in (flow.get("rows") or [])
                    if isinstance(row, dict)
                ],
                default="",
            )
            or decision.get("market_price_date")
            or ""
        ),
        "sources": list(dict.fromkeys(
            source
            for source in (
                str(decision.get("deep_provider") or ""),
                str(decision.get("market_price_source") or ""),
                str(flow.get("source_layer") or ""),
                str(financial.get("source_layer") or ""),
            )
            if source
        )),
    }


def build_stage_acceptance(
    decisions: list[dict[str, Any]],
    market_data_quality: dict[str, Any] | None = None,
    *,
    actionable_count: int = 0,
    execution_deferred: bool = False,
    persistence: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build independent process/evidence/execution/learning acceptance labels.

    This is deliberately observational.  It never changes a decision, score,
    selector, trading rule, or learning calculation.
    """
    quality = market_data_quality or {}
    decisions = list(decisions or [])
    total = len(decisions)
    deep = _deep_members(decisions)
    eligibility = quality.get("deep_candidate_eligibility") or {}
    deep_target = _int(
        eligibility.get("selected_count")
        or quality.get("deep_analysis_target")
        or len(deep)
    )
    deep_success = _int(quality.get("deep_analysis_count"))
    deep_attempted = _int(quality.get("deep_analysis_attempted_count"))
    deep_cached = _int(quality.get("deep_analysis_cached_count"))
    deep_errors = quality.get("deep_analysis_errors") or []
    deep_failed = min(len(deep_errors), deep_target)
    deep_skipped = max(0, deep_target - deep_success - deep_failed)
    target_trade_date = str(
        quality.get("target_trade_date") or quality.get("latest_local_data_date") or ""
    )
    deep_audits = [
        _deep_stock_audit(item, target_trade_date) for item in deep
    ]
    preselection_target = _int(quality.get("ai_preselection_target"))
    preselection_attempted = _int(quality.get("ai_preselection_count"))
    preselection_input_states = [
        "available" if item.get("preselection_input_sha256") else "unknown"
        for item in decisions
        if item.get("preselection_base_score") is not None
    ]
    preselection_complete = sum(state == "available" for state in preselection_input_states)
    final_target = _int(quality.get("final_review_target") or deep_success)
    final_called = bool(
        quality.get("final_review_called")
        or _int(quality.get("final_review_calls")) > 0
    )
    final_completed = min(_int(quality.get("final_review_count")), final_target)
    final_failed = max(0, final_target - final_completed) if final_called else 0
    final_skipped = max(0, final_target - final_completed) if not final_called else 0
    deep_unverified = sum(bool(item["evidence_gaps"]) for item in deep_audits)
    final_input_unverified = sum(
        item.get("component_status", {}).get("final_review_input") != "available"
        for item in deep_audits
        if item.get("required_for_stage", {}).get("final_review_input")
    )
    execution = quality.get("execution_observability") or {}
    action_count = _int(actionable_count)
    new_actions = _int(execution.get("new_buy_count")) + _int(
        execution.get("new_sell_count")
    )
    process_errors = list(quality.get("errors") or [])
    process_status = (
        "failed" if not total and process_errors else
        "partial" if process_errors or _int(quality.get("signals_computed"))
        < _int(quality.get("technical_universe_size")) else
        "completed"
    )

    technical_target = _int(quality.get("technical_universe_size") or total)
    technical_attempted = _int(quality.get("signals_computed") or total)
    technical_skipped = max(0, technical_target - technical_attempted)
    technical_extra = {
        "policy_excluded_count": _int(
            (quality.get("universe_policy") or {}).get("excluded_count")
        ),
        "candidate_count": total,
    }
    preselection_reasons = []
    if not quality.get("ai_preselection_called") and preselection_target:
        preselection_reasons.append("preselection_not_called")
    if quality.get("ai_preselection_error"):
        preselection_reasons.append("preselection_error")
    deep_reasons = []
    if deep_failed:
        deep_reasons.append("deep_analysis_failures_retained_in_denominator")
    if deep_skipped:
        deep_reasons.append("deep_analysis_capacity_or_deadline_skip")
    if deep_audits:
        gap_count = sum(bool(item["evidence_gaps"]) for item in deep_audits)
        if gap_count:
            deep_reasons.append("deep_required_evidence_gap")
            deep_reasons.extend(
                gap
                for item in deep_audits
                for gap in item.get("evidence_gaps") or []
            )
    final_reasons = []
    if final_target and not final_called:
        final_reasons.append("final_review_not_called")
    if final_failed:
        final_reasons.append("final_review_unmatched_or_failed")

    stage_map = {
        "technical": _stage(
            "technical", technical_target, technical_attempted, technical_attempted,
            skipped=technical_skipped, failed=len(process_errors),
            reason_codes=(['technical_stage_error'] if process_errors else [])
            + (['technical_rows_not_scored_or_policy_excluded'] if technical_skipped else []),
            extra=technical_extra,
        ),
        "preselection": _stage(
            "preselection", preselection_target, preselection_attempted,
            preselection_attempted, skipped=max(0, preselection_target - preselection_attempted),
            failed=1 if quality.get("ai_preselection_error") else 0,
            unverified=max(0, preselection_attempted - preselection_complete),
            reason_codes=preselection_reasons,
            extra={
                "input_evidence_count": preselection_complete,
                "input_evidence_ratio": _ratio(preselection_complete, preselection_target),
                "input_schema": "code,name,technical_score,discovery_score,fusion_score,change_pct,sources,reasons,flow,stock_skill",
            },
        ),
        "deep_research": _stage(
            "deep_research", deep_target,
            deep_attempted + deep_cached,
            deep_success,
            skipped=deep_skipped, failed=deep_failed,
            unverified=deep_unverified,
            reason_codes=deep_reasons,
            extra={
                "fresh_attempted_count": deep_attempted,
                "reused_count": deep_cached,
                "selected_stock_codes": [str(item.get("stock_code") or "") for item in deep],
                "stock_details": deep_audits,
                "components": {
                    component: _component_counts([
                        item["component_status"].get(component, "unknown")
                        for item in deep_audits
                    ])
                    for component in (
                        "deep_kline", "deep_financial_history", "deep_fund_flow",
                        "deep_announcements", "deep_input",
                    )
                },
            },
        ),
        "final_review": _stage(
            "final_review", final_target,
            final_target if final_called else 0,
            final_completed,
            skipped=final_skipped, failed=final_failed,
            unverified=final_input_unverified,
            reason_codes=final_reasons,
            extra={
                "called": final_called,
                "input_evidence_count": sum(
                    item.get("component_status", {}).get("final_review_input") == "available"
                    for item in deep_audits
                ),
                "provider": quality.get("final_review_provider") or "",
                "model": quality.get("final_review_model") or "",
            },
        ),
    }
    if not total:
        evidence_status = "unverified"
        evidence_reasons = ["no_decisions_persisted_or_loaded"]
    elif any(stage_map[name]["status"] in {"failed", "unverified"} for name in stage_map):
        evidence_status = "insufficient"
        evidence_reasons = [
            f"{name}_{stage_map[name]['status']}"
            for name in stage_map
            if stage_map[name]["status"] in {"failed", "unverified"}
        ]
    elif any(stage_map[name]["status"] == "partial" for name in stage_map):
        evidence_status = "partial"
        evidence_reasons = [
            f"{name}_partial" for name in stage_map if stage_map[name]["status"] == "partial"
        ]
    else:
        evidence_status = "sufficient"
        evidence_reasons = []

    persistence_status = "unverified"
    if persistence is not None:
        if persistence.get("error"):
            persistence_status = "failed"
        elif persistence.get("readback_verified") and _int(
            persistence.get("saved_count")
        ) >= _int(persistence.get("expected_count")):
            persistence_status = "verified"
        else:
            persistence_status = "partial"

    research_status = (
        "not_requested" if deep_target == 0 else
        "completed" if stage_map["deep_research"]["status"] == "completed"
        and stage_map["final_review"]["status"] in {"completed", "not_requested"}
        else "failed" if stage_map["deep_research"]["status"] == "failed"
        else "partial"
    )
    if execution_deferred:
        execution_status = "deferred"
        execution_reasons = ["paper_execution_deferred"]
    elif not total:
        execution_status = "not_requested"
        execution_reasons = ["no_candidates_reached_execution"]
    elif process_errors:
        execution_status = "failed"
        execution_reasons = ["execution_process_error"]
    elif action_count or new_actions:
        execution_status = "completed"
        execution_reasons = []
    elif _int(execution.get("blocked")) >= total:
        execution_status = "blocked"
        execution_reasons = ["all_candidates_blocked_by_existing_execution_gates"]
    else:
        execution_status = "no_eligible_candidates"
        execution_reasons = ["no_candidate_reached_execution_gate"]

    learning_payload = learning or {}
    learning_status = str(learning_payload.get("status") or "not_due")
    if learning_status not in {"completed", "partial", "failed", "not_due", "unverified"}:
        learning_status = "unverified"
    statuses = {
        "process_status": process_status,
        "persistence_status": persistence_status,
        "evidence_status": evidence_status,
        "research_status": research_status,
        "execution_status": execution_status,
        "learning_status": learning_status,
    }
    hard_fail = any(value == "failed" for value in statuses.values())
    unresolved = any(value in {"partial", "insufficient", "unverified", "deferred", "blocked"}
                     for value in (*statuses.values(), evidence_status))
    acceptance_status = "fail" if hard_fail else "partial" if unresolved else "pass"
    return {
        "schema_version": STAGE_ACCEPTANCE_SCHEMA_VERSION,
        "run_id": str(quality.get("run_id") or ""),
        "target_trade_date": str(quality.get("target_trade_date") or ""),
        "as_of": str(quality.get("run_created_at") or ""),
        "acceptance_scope": "stage_observability_and_run_quality; no selector_or_trade_rule_change",
        **statuses,
        "acceptance_status": acceptance_status,
        "reason_codes": list(dict.fromkeys(
            evidence_reasons + execution_reasons + list(learning_payload.get("reason_codes") or [])
        )),
        "stages": stage_map | {
            "execution": _stage(
                "execution", total, _int(execution.get("total") or total),
                new_actions, status=execution_status, reason_codes=execution_reasons,
                extra={
                    "blocked_count": _int(execution.get("blocked")),
                    "new_buy_count": _int(execution.get("new_buy_count")),
                    "new_sell_count": _int(execution.get("new_sell_count")),
                    "deferred": bool(execution_deferred),
                },
            ),
            "learning": _stage(
                "learning", _int(learning_payload.get("target_count")),
                _int(learning_payload.get("attempted_count")),
                _int(learning_payload.get("completed_count")),
                skipped=_int(learning_payload.get("skipped_count")),
                failed=_int(learning_payload.get("failed_count")),
                unverified=_int(learning_payload.get("unverified_count")),
                status=learning_status,
                reason_codes=list(learning_payload.get("reason_codes") or []),
                extra={"source": learning_payload.get("source") or "not_provided"},
            ),
        },
        "full_pool_context": {
            "candidate_count": total,
            "fundamental_available_count": sum(
                item.get("fundamental_evidence_available") is True for item in decisions
            ),
            "flow_state_counts": dict(Counter(
                str(item.get("flow_status") or item.get("flow_state") or "missing")
                for item in decisions
            )),
            "candidate_enrichment": quality.get("candidate_evidence_enrichment") or {},
            "not_scheduled_is_not_required_note": (
                "not_scheduled remains a collection state; it is not treated as a Deep failure when the stage did not require it."
            ),
        },
    }


def classify_run_outcome(
    decisions: list[dict[str, Any]],
    market_data_quality: dict[str, Any],
    *,
    actionable_count: int,
    execution_deferred: bool,
    persistence: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a run without turning missing evidence into a trade signal."""
    total = len(decisions)
    source_count = sum(bool(item.get("market_sources")) for item in decisions)
    source_coverage = source_count / total if total else 0.0
    flow_counts = Counter(str(item.get("flow_status") or "missing") for item in decisions)
    missing_flow = flow_counts.get("missing", 0) + flow_counts.get("invalid", 0)
    flow_covered = sum(
        count for state, count in flow_counts.items()
        if state in {"positive", "negative"}
    )
    fundamental_covered = sum(
        bool(
            isinstance(item.get("fundamentals"), dict)
            and item.get("fundamentals", {}).get("available")
        )
        for item in decisions
    )
    errors = list(market_data_quality.get("errors") or [])
    degraded = bool(market_data_quality.get("degraded"))

    if execution_deferred:
        status = "discovery_only"
        reason_codes = ["paper_execution_deferred"]
    elif actionable_count > 0:
        status = "actionable_candidates"
        reason_codes = []
    elif not total or degraded or errors or source_coverage == 0.0:
        status = "data_insufficient_abstention"
        reason_codes = ["market_data_insufficient"]
    elif missing_flow / total >= 0.50:
        status = "data_insufficient_abstention"
        reason_codes = ["fund_flow_evidence_missing"]
    else:
        status = "no_actionable_market_opportunity"
        reason_codes = ["action_score_below_buy_gate"]

    stage_acceptance = build_stage_acceptance(
        decisions,
        market_data_quality,
        actionable_count=actionable_count,
        execution_deferred=execution_deferred,
        persistence=persistence,
        learning=learning,
    )
    return {
        "status": status,
        "reason_codes": reason_codes,
        "decision_count": total,
        "source_coverage": round(source_coverage, 4),
        "flow_coverage": round(flow_covered / total, 4) if total else 0.0,
        "fundamental_coverage": (
            round(fundamental_covered / total, 4) if total else 0.0
        ),
        "flow_status_counts": dict(flow_counts),
        "market_data_degraded": degraded,
        "error_count": len(errors),
        "actionable_count": int(actionable_count),
        "execution_deferred": bool(execution_deferred),
        "process_status": stage_acceptance["process_status"],
        "persistence_status": stage_acceptance["persistence_status"],
        "evidence_status": stage_acceptance["evidence_status"],
        "research_status": stage_acceptance["research_status"],
        "execution_status": stage_acceptance["execution_status"],
        "learning_status": stage_acceptance["learning_status"],
        "acceptance_status": stage_acceptance["acceptance_status"],
        "stage_acceptance": stage_acceptance,
    }


def summarize_execution_dispositions(
    decisions: list[dict[str, Any]],
    *,
    allow_probe: bool = True,
) -> dict[str, Any]:
    """Count execution eligibility without changing any decision fields."""
    counts = Counter()
    reasons = Counter()
    for decision in decisions:
        result = evaluate_entry_execution(decision, allow_probe=allow_probe)
        tier = str(result.get("tier") or "blocked")
        state = str(result.get("flow_state") or "missing")
        if tier == "normal":
            counts["normal_eligible"] += 1
        elif tier == "probe":
            counts["probe_eligible"] += 1
        else:
            counts["blocked"] += 1
            if state == "negative":
                counts["blocked_negative"] += 1
            elif state in {"missing", "invalid"}:
                counts["blocked_missing"] += 1
            if str(result.get("fallback_status") or "") == "exhausted":
                counts["fallback_exhausted"] += 1
            reasons[str(result.get("reason") or "unknown")] += 1
    return {
        **dict(counts),
        "blocked_reason_counts": dict(reasons),
        "total": len(decisions),
        "probe_enabled": bool(allow_probe),
    }
