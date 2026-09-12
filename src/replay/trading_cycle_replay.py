"""Deterministic, read-only validation of one Adaptive Investment day.

The replay consumes a recorded stage manifest rather than live providers or
the formal paper ledger.  It verifies the contracts that are difficult to
prove with isolated unit tests: stage ordering, sell-before-buy execution,
fail-closed degraded data handling, learning completion, and point-in-time
data safety.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

EXPECTED_STAGES = (
    "pre_market",
    "market_open",
    "midday",
    "afternoon",
    "market_close",
    "outcome_backfill",
    "evening",
)
_EXECUTED_STATUSES = frozenset({"executed", "filled", "success"})


@dataclass(frozen=True, slots=True)
class TradingCycleReplayResult:
    """Auditable result of a single offline cycle replay."""

    status: str
    trade_date: str
    stage_names: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata_verified: bool = False
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "trade_date": self.trade_date,
            "stage_names": list(self.stage_names),
            "metrics": self.metrics,
            "metadata_verified": self.metadata_verified,
            "reasons": list(self.reasons),
            "data_source": "frozen_cycle_manifest_only",
            "network_used": False,
            "formal_ledger_written": False,
        }


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _empty_metrics() -> dict[str, Any]:
    return {
        "candidate_count": 0,
        "raw_score_qualified_count": 0,
        "evidence_attempt_count": 0,
        "evidence_success_count": 0,
        "action_score_qualified_count": 0,
        "deep_analysis_count": 0,
        "final_review_approved_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "learning_update_count": 0,
        "rejection_counts": {},
    }


def _inc_rejection(rejections: dict[str, int], reason: Any, count: int = 1) -> None:
    key = str(reason or "unknown").strip() or "unknown"
    rejections[key] = rejections.get(key, 0) + max(1, int(count))


def _candidate_metrics(
    candidates: Sequence[Mapping[str, Any]],
    metrics: dict[str, Any],
) -> None:
    metrics["candidate_count"] = len(candidates)
    for candidate in candidates:
        if float(candidate.get("ranking_score") or 0) >= 65:
            metrics["raw_score_qualified_count"] += 1
        metrics["evidence_attempt_count"] += bool(candidate.get("evidence_attempted"))
        metrics["evidence_success_count"] += bool(candidate.get("evidence_complete"))
        metrics["action_score_qualified_count"] += (
            float(candidate.get("action_score") or 0) >= 65
        )
        metrics["deep_analysis_count"] += bool(candidate.get("deep_analysis_available"))
        metrics["final_review_approved_count"] += bool(candidate.get("final_buy_approved"))
        if candidate.get("rejection_reason"):
            _inc_rejection(metrics["rejection_counts"], candidate["rejection_reason"])


def _validate_stage_times(
    stage: Mapping[str, Any], reasons: list[str]
) -> None:
    started = _timestamp(stage.get("started_at"))
    completed = _timestamp(stage.get("completed_at"))
    cutoff = _timestamp(stage.get("data_cutoff_at"))
    name = str(stage.get("name") or "unknown")
    if not started or not completed:
        reasons.append(f"stage_timestamps_missing:{name}")
    elif completed < started:
        reasons.append(f"stage_timestamp_order_invalid:{name}")
    if cutoff and completed and cutoff > completed:
        reasons.append(f"future_data_detected:{name}")
    for candidate in stage.get("candidates") or []:
        data_time = _timestamp(candidate.get("data_time"))
        decision_time = _timestamp(candidate.get("decision_time"))
        if data_time and decision_time and data_time > decision_time:
            reasons.append("future_data_detected")


def replay_trading_cycle(payload: Mapping[str, Any]) -> TradingCycleReplayResult:
    """Validate a frozen daily workflow without network or database writes."""
    metadata = payload.get("metadata") or {}
    trade_date = str(metadata.get("trade_date") or "")
    reasons: list[str] = []
    if metadata.get("network_used") is not False:
        reasons.append("network_use_forbidden")
    if metadata.get("writes_formal_ledger") is not False:
        reasons.append("formal_ledger_write_forbidden")
    if metadata.get("lookahead_safe") is not True:
        reasons.append("lookahead_not_safe")
    if metadata.get("performance_evidence") is not False:
        reasons.append("synthetic_fixture_cannot_claim_performance")

    raw_stages = payload.get("stages") or []
    stages = [item for item in raw_stages if isinstance(item, Mapping)]
    stage_names = tuple(str(stage.get("name") or "") for stage in stages)
    if stage_names != EXPECTED_STAGES:
        reasons.append("stage_order_incomplete")
    if len(set(stage_names)) != len(stage_names):
        reasons.append("duplicate_stage")

    by_name = {str(stage.get("name") or ""): stage for stage in stages}
    metrics = _empty_metrics()
    pre_market = by_name.get("pre_market")
    if pre_market:
        candidates = [
            item for item in pre_market.get("candidates") or []
            if isinstance(item, Mapping)
        ]
        _candidate_metrics(candidates, metrics)

    for stage in stages:
        name = str(stage.get("name") or "unknown")
        if stage.get("status") != "success":
            reasons.append(f"stage_not_success:{name}")
        _validate_stage_times(stage, reasons)
        for rejection in stage.get("rejections") or []:
            if isinstance(rejection, Mapping):
                _inc_rejection(
                    metrics["rejection_counts"],
                    rejection.get("reason"),
                    int(rejection.get("count") or 1),
                )

        executed_actions: list[Mapping[str, Any]] = []
        for action in stage.get("actions") or []:
            if not isinstance(action, Mapping):
                continue
            action_name = str(action.get("action") or "").upper()
            action_status = str(action.get("status") or "executed").lower()
            if action_status not in _EXECUTED_STATUSES:
                _inc_rejection(metrics["rejection_counts"], action.get("reason"))
                continue
            if stage.get("market_data_status") == "degraded" and action_name == "BUY":
                _inc_rejection(metrics["rejection_counts"], "degraded_data_buy_blocked")
                reasons.append("degraded_data_buy_blocked")
                continue
            if action_name in {"BUY", "SELL"}:
                executed_actions.append(action)
                metrics[f"{action_name.lower()}_count"] += 1

        action_names = [str(item.get("action") or "").upper() for item in executed_actions]
        if "BUY" in action_names and "SELL" in action_names:
            if max(index for index, value in enumerate(action_names) if value == "SELL") > min(
                index for index, value in enumerate(action_names) if value == "BUY"
            ):
                reasons.append(f"sell_must_precede_buy:{name}")

        if name == "outcome_backfill":
            metrics["learning_update_count"] += int(stage.get("learning_updates") or 0)

    evening = by_name.get("evening") or {}
    if not evening.get("journal_saved"):
        reasons.append("daily_journal_missing")
    if not evening.get("reflection_saved"):
        reasons.append("ai_reflection_missing")
    if metrics["learning_update_count"] < 0:
        reasons.append("learning_update_count_invalid")

    unique_reasons = tuple(dict.fromkeys(reasons))
    metadata_verified = not any(
        reason in {
            "network_use_forbidden",
            "formal_ledger_write_forbidden",
            "lookahead_not_safe",
            "future_data_detected",
        }
        or reason.startswith("future_data_detected:")
        for reason in unique_reasons
    )
    return TradingCycleReplayResult(
        status="passed" if not unique_reasons else "blocked",
        trade_date=trade_date,
        stage_names=stage_names,
        metrics=metrics,
        metadata_verified=metadata_verified,
        reasons=unique_reasons,
    )
