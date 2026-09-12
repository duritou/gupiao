"""Post-backfill AI rerun gating and durable orchestration helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


BACKFILL_PARTITION_VERSION = "20260906-v3"
RESEARCH_COMPONENTS = (
    "daily",
    "adjustment_factor",
    "financial_history",
    "fund_flow_history",
)
RERUN_MIN_COMPONENT_COVERAGE = 0.95
SYSTEMIC_FAILURE_STATUSES = frozenset({
    "permission_denied",
    "provider_error",
    "database_error",
    "source_unavailable",
})


def parse_backfill_partition(partition_key: str) -> dict[str, Any] | None:
    """Decode the existing checkpoint key without inventing another format."""
    parts = str(partition_key or "").split(":")
    if len(parts) != 8 or parts[0] != BACKFILL_PARTITION_VERSION:
        return None
    try:
        _, scope, source_run_id, limit, target_date, required_bars, periods, flow_days = parts
        return {
            "scope": scope,
            "source_run_id": source_run_id,
            "limit": int(limit),
            "target_date": target_date,
            "required_bars": int(required_bars),
            "periods": int(periods),
            "flow_days": int(flow_days),
        }
    except (TypeError, ValueError):
        return None


def _decode_progress(checkpoint: dict[str, Any]) -> dict[str, Any]:
    progress = checkpoint.get("progress")
    return progress if isinstance(progress, dict) else {}


def _latest_checkpoint(
    checkpoints: list[dict[str, Any]], source_run_id: str, target_date: str,
) -> dict[str, Any] | None:
    matching = []
    for checkpoint in checkpoints:
        parsed = parse_backfill_partition(checkpoint.get("partition_key", ""))
        if not parsed or parsed["scope"] != "candidate":
            continue
        if parsed["source_run_id"] != source_run_id or parsed["target_date"] != target_date:
            continue
        matching.append((str(checkpoint.get("updated_at") or ""), checkpoint))
    if not matching:
        return None
    return max(matching, key=lambda item: item[0])[1]


def _failure_details(
    codes: list[str], missing_by_component: dict[str, list[str]],
    persisted_results: dict[str, Any], coverage_details: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    missing_codes = sorted({code for values in missing_by_component.values() for code in values})
    result: dict[str, dict[str, Any]] = {}
    for code in missing_codes:
        persisted = persisted_results.get(code) or {}
        components = persisted.get("components") if isinstance(persisted, dict) else {}
        incomplete = {
            name: {
                key: item.get(key)
                for key in (
                    "status", "source", "error_type", "error_message", "error",
                    "attempted", "attempt_count", "elapsed_seconds", "data_date",
                    "target_date", "request_attempts",
                )
                if item.get(key) not in (None, "", [])
            }
            for name, item in (components or {}).items()
            if isinstance(item, dict) and item.get("status") != "available"
        }
        result[code] = {
            "incomplete_components": sorted(
                name for name, values in missing_by_component.items() if code in values
            ),
            "persisted": incomplete,
            "database_coverage": coverage_details.get(code) or {},
        }
    return result


def build_backfill_summary(
    *, checkpoint: dict[str, Any], coverage: dict[str, Any],
    source_run_id: str, target_date: str,
) -> dict[str, Any]:
    """Build a bounded, persisted summary from post-worker DB state."""
    progress = _decode_progress(checkpoint)
    codes = sorted({str(code or "").strip().upper() for code in progress.get("codes") or [] if code})
    components = coverage.get("components") or {}
    missing_by_component = {
        name: list((components.get(name) or {}).get("missing_codes") or [])
        for name in RESEARCH_COMPONENTS
    }
    component_coverage = {
        name: {
            "candidate_count": int((components.get(name) or {}).get("candidate_count") or len(codes)),
            "complete_count": int((components.get(name) or {}).get("complete_count") or 0),
            "coverage": float((components.get(name) or {}).get("coverage") or 0.0),
        }
        for name in RESEARCH_COMPONENTS
    }
    complete_codes = [
        code for code in codes
        if all(code not in missing_by_component[name] for name in RESEARCH_COMPONENTS)
    ]
    summary = {
        "target_date": target_date,
        "source_run_id": source_run_id,
        "candidate_count": len(codes),
        "complete_candidate_count": len(complete_codes),
        "component_coverage": component_coverage,
        "missing_by_component": missing_by_component,
        "missing_reason_by_symbol": _failure_details(
            codes, missing_by_component, progress.get("results") or {},
            coverage.get("details") or {},
        ),
        "checkpoint_updated_at": str(checkpoint.get("updated_at") or ""),
        "worker_status": str(checkpoint.get("status") or ""),
        "expected_flow_dates": list(coverage.get("expected_flow_dates") or []),
    }
    summary["data_revision"] = build_data_revision(summary, coverage)
    return summary


def build_data_revision(summary: dict[str, Any], coverage: dict[str, Any]) -> str:
    """Hash only persisted evidence facts so no-op checkpoint writes are stable."""
    payload = {
        "target_date": summary.get("target_date", ""),
        "source_run_id": summary.get("source_run_id", ""),
        "candidate_count": summary.get("candidate_count", 0),
        "components": summary.get("component_coverage") or {},
        "expected_flow_dates": coverage.get("expected_flow_dates") or [],
        "details": coverage.get("details") or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def evaluate_post_backfill_gate(
    summary: dict[str, Any], *, previous_ai_run_created_at: str = "",
) -> dict[str, Any]:
    """Decide whether new evidence is sufficient to rerun research."""
    reasons: list[str] = []
    candidate_count = int(summary.get("candidate_count") or 0)
    coverage = summary.get("component_coverage") or {}
    if candidate_count <= 0:
        reasons.append("no_candidates")
    if str(summary.get("worker_status") or "") not in {"completed", "partial"}:
        reasons.append("backfill_worker_not_terminal")
    for name in RESEARCH_COMPONENTS:
        value = float((coverage.get(name) or {}).get("coverage") or 0.0)
        if value < RERUN_MIN_COMPONENT_COVERAGE:
            reasons.append(f"{name}_coverage_below_threshold")
    failure_statuses = {
        str(item.get("status") or "")
        for details in (summary.get("missing_reason_by_symbol") or {}).values()
        for item in (details.get("persisted") or {}).values()
    }
    if failure_statuses & SYSTEMIC_FAILURE_STATUSES:
        reasons.append("systemic_data_source_failure")
    checkpoint_at = str(summary.get("checkpoint_updated_at") or "")
    if previous_ai_run_created_at and checkpoint_at and checkpoint_at <= previous_ai_run_created_at:
        reasons.append("no_material_data_improvement")
    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "eligible": not unique_reasons,
        "reason_codes": unique_reasons,
        "coverage_snapshot": coverage,
        "data_revision": str(summary.get("data_revision") or ""),
        "source_run_id": str(summary.get("source_run_id") or ""),
        "target_date": str(summary.get("target_date") or ""),
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "threshold": RERUN_MIN_COMPONENT_COVERAGE,
    }


def make_rerun_execution_key(summary: dict[str, Any]) -> str:
    return "post_backfill_ai_rerun:{target_date}:{source_run_id}:{data_revision}".format(
        target_date=str(summary.get("target_date") or ""),
        source_run_id=str(summary.get("source_run_id") or ""),
        data_revision=str(summary.get("data_revision") or ""),
    )


def verify_rerun_result(
    payload: dict[str, Any], persisted_evidence: dict[str, Any],
    *, source_run_id: str, checkpoint_updated_at: str,
    expected_decision_count: int = 1,
) -> dict[str, Any]:
    """Verify a worker result and the evidence persisted by the new AI run."""
    result = payload.get("result") if isinstance(payload, dict) else {}
    result = result if isinstance(result, dict) else {}
    new_run_id = str(result.get("run_id") or persisted_evidence.get("run_id") or "")
    reasons: list[str] = []
    if str(payload.get("status") or "") != "success":
        reasons.append("ai_worker_failed")
    if payload.get("execute_paper_trades") is not False:
        reasons.append("paper_execution_not_disabled")
    if not new_run_id:
        reasons.append("new_run_id_missing")
    elif new_run_id == str(source_run_id or ""):
        reasons.append("new_run_id_not_created")
    persisted_count = int(persisted_evidence.get("decision_count") or 0)
    if persisted_count <= 0:
        reasons.append("persisted_decisions_missing")
    elif persisted_count < max(1, int(expected_decision_count)):
        reasons.append("persisted_decisions_incomplete")
    run_created_at = str(
        result.get("run_created_at")
        or (result.get("market_data_quality") or {}).get("run_created_at")
        or ""
    )
    if checkpoint_updated_at and run_created_at and run_created_at <= checkpoint_updated_at:
        reasons.append("ai_run_not_after_backfill_checkpoint")
    if result.get("paper_trades"):
        reasons.append("paper_trades_created")
    return {
        "verified": not reasons,
        "reason_codes": list(dict.fromkeys(reasons)),
        "new_run_id": new_run_id,
        "persisted_evidence": persisted_evidence,
        "run_outcome": (result.get("market_data_quality") or {}).get("run_outcome") or {},
        "paper_trades": result.get("paper_trades") or [],
    }


def summarize_latest_backfill(database: Any) -> dict[str, Any]:
    """Re-read the latest AI run's matching checkpoint and evidence coverage."""
    latest_run = database.get_latest_strategy_run()
    source_run_id = str(latest_run.get("run_id") or "")
    target_date = str(latest_run.get("decision_date") or "")[:10]
    if not source_run_id or not target_date:
        return {
            "status": "not_ready", "reason_codes": ["latest_strategy_run_missing"],
        }
    checkpoints = database.list_completion_checkpoints(
        "research_data_backfill", "candidate"
    )
    checkpoint = _latest_checkpoint(checkpoints, source_run_id, target_date)
    if checkpoint is None:
        return {
            "status": "not_ready", "reason_codes": ["matching_backfill_checkpoint_missing"],
            "source_run_id": source_run_id, "target_date": target_date,
        }
    parsed = parse_backfill_partition(checkpoint.get("partition_key", "")) or {}
    codes = list((_decode_progress(checkpoint).get("codes") or latest_run.get("codes") or []))
    coverage = database.get_research_component_coverage(
        codes, target_date,
        int(parsed.get("required_bars") or 250),
        int(parsed.get("periods") or 8),
        int(parsed.get("flow_days") or 20),
    )
    return build_backfill_summary(
        checkpoint=checkpoint, coverage=coverage,
        source_run_id=source_run_id, target_date=target_date,
    )
