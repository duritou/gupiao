"""Fail-closed gate for multi-day shadow reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ShadowGateResult:
    """Structural result for the independent five-day shadow gate."""

    status: str
    required_days: int
    available_days: int
    shadow_gate_passed: bool
    eligible_for_promotion: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "required_days": self.required_days,
            "available_days": self.available_days,
            "shadow_gate_passed": self.shadow_gate_passed,
            "eligible_for_promotion": self.eligible_for_promotion,
            "reasons": list(self.reasons),
            "data_source": "persisted_shadow_reports_only",
        }


def evaluate_shadow_gate(
    reports: Sequence[Mapping[str, Any]], *, required_days: int = 5
) -> ShadowGateResult:
    """Require distinct, non-executable and reviewed shadow observations."""
    required = max(1, int(required_days))
    dates = [str(report.get("trade_date") or "") for report in reports]
    reasons: list[str] = []
    valid_dates = [value for value in dates if value]
    available = len(set(valid_dates))
    if available < required:
        reasons.append("insufficient_shadow_trading_days")
    if len(valid_dates) != len(dates):
        reasons.append("shadow_trade_date_missing")
    if len(valid_dates) != available:
        reasons.append("duplicate_shadow_trading_dates")

    for report in reports:
        if report.get("status") != "shadow_only":
            reasons.append("invalid_shadow_report_status")
        if report.get("paper_execution_enabled") is not False:
            reasons.append("shadow_execution_not_disabled")
        if report.get("data_source") != "same_scan_decision_sets_only":
            reasons.append("shadow_data_source_not_confirmed")
        counts = report.get("counts") or {}
        changed = int(report.get("changed_count") or 0)
        changed += int(counts.get("direction_changed") or 0)
        changed += int(counts.get("evidence_changed") or 0)
        if changed and report.get("review_status") != "reviewed":
            reasons.append("unreviewed_shadow_differences")

    unique_reasons = tuple(dict.fromkeys(reasons))
    status = "passed"
    if unique_reasons:
        status = (
            "insufficient_shadow_history"
            if unique_reasons == ("insufficient_shadow_trading_days",)
            else "blocked"
        )
    return ShadowGateResult(
        status=status,
        required_days=required,
        available_days=available,
        shadow_gate_passed=status == "passed",
        # Historical gate, P0 checks and promotion review remain separate.
        eligible_for_promotion=False,
        reasons=unique_reasons,
    )
