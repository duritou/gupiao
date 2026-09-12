"""Shadow-only comparison of baseline and candidate decisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


def _direction(decision: Mapping[str, Any]) -> str:
    if decision.get("actionable") is False:
        return ""
    value = decision.get("executable_direction") or decision.get("direction")
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"buy", "sell"} else ""


def _code(decision: Mapping[str, Any]) -> str:
    return str(decision.get("stock_code") or decision.get("code") or "").strip().upper()


def _score(decision: Mapping[str, Any]) -> float | None:
    value = decision.get("action_score", decision.get("ai_score"))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _evidence(decision: Mapping[str, Any]) -> tuple[Any, ...]:
    sources = decision.get("market_evidence_sources") or decision.get("market_sources") or []
    return (
        bool(decision.get("market_evidence_complete")),
        tuple(sorted(str(value).strip().lower() for value in sources if value)),
        str(decision.get("evidence_status") or ""),
    )


def build_shadow_report(
    trade_date: str,
    baseline_decisions: Sequence[Mapping[str, Any]],
    candidate_decisions: Sequence[Mapping[str, Any]],
    *,
    baseline_version: str = "",
    candidate_version: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Create a per-stock difference report without executing either side."""
    baseline = {_code(item): item for item in baseline_decisions if _code(item)}
    candidate = {_code(item): item for item in candidate_decisions if _code(item)}
    differences: list[dict[str, Any]] = []
    counts = {
        "added": 0,
        "removed": 0,
        "direction_changed": 0,
        "score_changed": 0,
        "evidence_changed": 0,
        "unchanged": 0,
    }
    for code in sorted(set(baseline) | set(candidate)):
        old = baseline.get(code)
        new = candidate.get(code)
        changes: list[str] = []
        if old is None:
            changes.append("candidate_added")
            counts["added"] += 1
        elif new is None:
            changes.append("candidate_removed")
            counts["removed"] += 1
        else:
            if _direction(old) != _direction(new):
                changes.append("direction_changed")
                counts["direction_changed"] += 1
            if _score(old) != _score(new):
                changes.append("score_changed")
                counts["score_changed"] += 1
            if _evidence(old) != _evidence(new):
                changes.append("evidence_changed")
                counts["evidence_changed"] += 1
        if not changes:
            counts["unchanged"] += 1
            continue
        differences.append({
            "stock_code": code,
            "changes": changes,
            "baseline_direction": _direction(old or {}),
            "candidate_direction": _direction(new or {}),
            "baseline_score": _score(old or {}),
            "candidate_score": _score(new or {}),
        })
    return {
        "status": "shadow_only",
        "trade_date": str(trade_date or ""),
        "run_id": str(run_id or ""),
        "baseline_version": str(baseline_version or ""),
        "candidate_version": str(candidate_version or ""),
        "baseline_count": len(baseline),
        "candidate_count": len(candidate),
        "changed_count": len(differences),
        "counts": counts,
        "differences": differences[:200],
        "paper_execution_enabled": False,
        "data_source": "same_scan_decision_sets_only",
    }


def _report_hash(report: Mapping[str, Any]) -> str:
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def persist_shadow_report(
    report: Mapping[str, Any], database: Any | None = None
) -> int:
    """Persist a shadow report in the existing replay history table only."""
    if report.get("status") != "shadow_only":
        raise ValueError("only shadow_only reports may be persisted")
    if report.get("paper_execution_enabled") is not False:
        raise ValueError("shadow report must disable paper execution")
    trade_date = str(report.get("trade_date") or "").strip()
    if not trade_date:
        raise ValueError("shadow report requires trade_date")
    if database is None:
        from src.infrastructure.storage.market_database import market_db

        database = market_db
    baseline = str(report.get("baseline_version") or "").strip()
    candidate = str(report.get("candidate_version") or "").strip()
    return database.save_replay_run(
        replay_date=trade_date,
        mode="shadow",
        model_version=f"{baseline}->{candidate}".strip("->"),
        context_hash=str(report.get("run_id") or ""),
        result_hash=_report_hash(report),
        status="shadow_only",
        result=dict(report),
    )


def load_persisted_shadow_reports(
    database: Any | None = None, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Load shadow reports without mixing them with replay or simulation runs."""
    if database is None:
        from src.infrastructure.storage.market_database import market_db

        database = market_db
    reports: list[dict[str, Any]] = []
    for run in database.get_replay_runs(limit=max(1, min(int(limit), 500))):
        if run.get("mode") != "shadow":
            continue
        report = run.get("result")
        if not isinstance(report, dict):
            continue
        reports.append({**report, "replay_run_id": run.get("id")})
    return reports
