"""Fail-closed policy shared by every paper-trading execution path."""

from __future__ import annotations

import json
from typing import Any

from config.settings import settings

PAPER_MAX_POSITION_PCT = 0.20
PAPER_MIN_CASH_RESERVE_PCT = 0.10
PAPER_MAX_POSITIONS = 5
PAPER_MIN_BUY_SCORE = 65.0
PAPER_EXPLORATION_POSITION_PCT = 0.02
PAPER_EXPLORATION_MAX_ENTRIES = 2
PAPER_MOMENTUM_PROBE_POSITION_PCT = PAPER_EXPLORATION_POSITION_PCT
PAPER_MOMENTUM_PROBE_MAX_CANDIDATES = 5
PAPER_MOMENTUM_PROBE_MAX_ENTRIES = PAPER_EXPLORATION_MAX_ENTRIES
PAPER_MOMENTUM_PROBE_MIN_RAW_SCORE = 60.0
PAPER_MOMENTUM_PROBE_MIN_DISCOVERY_SCORE = 60.0
PAPER_MOMENTUM_PROBE_MIN_CHANGE_PCT = 0.3
PAPER_MOMENTUM_PROBE_MAX_CHANGE_PCT = 4.5
PAPER_NEUTRAL_EXIT_AFTER_DAYS = 5
PAPER_NEUTRAL_FORCE_EXIT_AFTER_DAYS = 8
PAPER_NEUTRAL_EXIT_SCORE = 55.0
PAPER_NEUTRAL_PROFIT_LOCK_PCT = 12.0
PAPER_PROFIT_RETRACE_PCT = 8.0
PAPER_PROFIT_RETRACE_MIN_GAIN_PCT = 5.0
PAPER_HARD_STOP_LOSS_PCT = 8.0
PAPER_MAX_HOLDING_DAYS = 20
TRADINGAGENTS_BUY_RATINGS = frozenset({"buy", "overweight"})
PAPER_LIVENESS_LOG_LIMIT = 100


def _execution_observations_by_day(
    learning_log: list[dict[str, Any]], as_of_date: str = ""
) -> list[dict[str, Any]]:
    """Collapse repeated task writes to one latest observation per calendar day."""
    latest: dict[str, dict[str, Any]] = {}
    undated: list[dict[str, Any]] = []
    cutoff = str(as_of_date or "")[:10]
    for entry in learning_log:
        if entry.get("category") != "execution_observability":
            continue
        learning_date = str(
            entry.get("learning_date") or str(entry.get("created_at") or "")[:10]
        )[:10]
        if not learning_date:
            # Compatibility for legacy/in-memory callers that supplied no
            # timestamp. These entries cannot be deduplicated by day, so keep
            # each one observable instead of silently dropping liveness data.
            undated.append(entry)
            continue
        if cutoff and learning_date > cutoff:
            continue
        previous = latest.get(learning_date)
        current_key = (
            str(entry.get("created_at") or ""),
            str(entry.get("id") or ""),
        )
        previous_key = (
            str(previous.get("created_at") or ""),
            str(previous.get("id") or ""),
        ) if previous else ("", "")
        if previous is None or current_key >= previous_key:
            latest[learning_date] = entry
    return undated + [latest[key] for key in sorted(latest, reverse=True)]


def paper_liveness_status(
    learning_log: list[dict[str, Any]],
    cash: float,
    total_value: float,
    *,
    alert_after_days: int = 5,
    minimum_cash_pct: float = 0.70,
    as_of_date: str = "",
) -> dict[str, Any]:
    """Report prolonged abstention without turning it into a buy signal."""
    consecutive_no_buy = 0
    counted_dates: list[str] = []
    for entry in _execution_observations_by_day(learning_log, as_of_date):
        evidence = entry.get("evidence") or {}
        if evidence.get("execution_deferred"):
            continue
        counted_dates.append(str(
            entry.get("learning_date") or str(entry.get("created_at") or "")[:10]
        )[:10])
        if int(evidence.get("new_buy_count") or 0) > 0:
            break
        consecutive_no_buy += 1

    cash_pct = float(cash or 0) / float(total_value or 1)
    alert = (
        consecutive_no_buy >= max(1, int(alert_after_days))
        and cash_pct >= float(minimum_cash_pct)
    )
    return {
        "alert": alert,
        "consecutive_no_buy_sessions": consecutive_no_buy,
        "counted_learning_dates": counted_dates,
        "as_of_date": str(as_of_date or "")[:10],
        "observation_source_limit": len(learning_log),
        "cash_pct": round(cash_pct, 4),
        "reason": (
            "no_actionable_buy_with_high_cash"
            if alert
            else "within_liveness_guardrail"
        ),
    }


def decision_direction(decision: dict[str, Any]) -> str:
    """Prefer the persisted deep direction over the technical direction."""
    return str(
        decision.get("effective_direction")
        or decision.get("direction")
        or "neutral"
    ).strip().lower()


def _entry_deep_rating(
    position: dict[str, Any], decision: dict[str, Any]
) -> str:
    """Read Deep Buy support from immutable entry identity during risk review."""
    if decision.get("position_risk_review") is not True:
        # Compatibility for direct policy callers that are not reviewing a
        # persisted holding. Production holding paths set position_risk_review.
        return str(decision.get("deep_rating") or "").strip().lower()
    if str(position.get("entry_identity_status") or "") != "verified":
        return ""
    if position.get("entry_decision_id") is None or not str(
        position.get("entry_strategy_version") or ""
    ).strip():
        return ""
    return str(
        position.get("entry_deep_rating")
        or decision.get("entry_deep_rating")
        or ""
    ).strip().lower()


def is_buy_signal(decision: dict[str, Any]) -> bool:
    """Return whether the effective decision is a score-qualified BUY."""
    if decision.get("actionable") is False:
        return False
    score = decision.get("action_score", decision.get("ai_score"))
    return (
        float(score or 50) >= PAPER_MIN_BUY_SCORE
        and decision_direction(decision) == "buy"
    )


def deep_buy_rejection_reason(decision: dict[str, Any]) -> str:
    """Explain why a BUY lacks Codex-Terra deep analysis and final approval."""
    if not is_buy_signal(decision):
        return "not_a_buy_signal"
    rating = str(decision.get("deep_rating") or "").strip().lower()
    available = decision.get("deep_analysis_available") is True
    if not available or not rating:
        return "codex_deep_analysis_required"
    if str(decision.get("deep_provider") or "") != "codex_cli":
        return "codex_deep_provider_required"
    if str(decision.get("deep_model") or "") != settings.CODEX_MODEL:
        return "codex_terra_model_required"
    if rating not in TRADINGAGENTS_BUY_RATINGS:
        return f"codex_deep_buy_not_approved:{rating}"
    if "final_buy_approved" in decision:
        if decision.get("final_buy_approved") is not True:
            verdict = str(decision.get("final_review_verdict") or "").lower()
            return (
                "codex_final_review_veto"
                if verdict == "veto" else "codex_final_review_required"
            )
    elif decision.get("final_review_required") is True:
        if decision.get("final_review_available") is not True:
            return "codex_final_review_required"
        if str(decision.get("final_review_verdict") or "").lower() != "approve":
            return "codex_final_review_veto"
    return ""


def is_deep_buy_approved(decision: dict[str, Any]) -> bool:
    """Fail closed unless Codex-Terra approved both deep and final stages."""
    return deep_buy_rejection_reason(decision) == ""


def _decision_evidence(decision: dict[str, Any]) -> dict[str, Any]:
    evidence = decision.get("evidence")
    if isinstance(evidence, dict):
        return evidence
    if isinstance(evidence, str) and evidence:
        try:
            parsed = json.loads(evidence)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def momentum_probe_rank(decision: dict[str, Any]) -> float:
    """Return the pre-market rank used to bound opening quote requests."""
    evidence = _decision_evidence(decision)
    guard = evidence.get("score_guard") or {}
    return float(
        decision.get("raw_ai_score")
        or guard.get("raw_score")
        or decision.get("ai_score")
        or 0
    )


def momentum_probe_candidate_rejection_reason(decision: dict[str, Any]) -> str:
    """Validate an overnight candidate before requesting a live quote.

    This path is intentionally limited to strong multi-source decisions.
    A deep Hold may receive a small live-confirmed observation position, while
    bearish deep ratings remain authoritative and cannot be bypassed.
    """
    name = str(decision.get("stock_name") or "").strip().upper()
    if "ST" in name or name.startswith(("N", "C")):
        return "momentum_probe_restricted_stock"
    status = str(decision.get("status") or "").strip().lower()
    if bool(decision.get("is_suspended")) or status in {
        "suspended", "delisted", "terminated",
    }:
        return "momentum_probe_stock_not_tradable"
    deep_rating = str(decision.get("deep_rating") or "").strip().lower()
    if deep_rating and deep_rating not in {"hold", "neutral"}:
        return "momentum_probe_deep_result_is_authoritative"
    if decision_direction(decision) not in {"neutral", "buy"}:
        return "momentum_probe_requires_neutral_or_buy"

    evidence = _decision_evidence(decision)
    guard = evidence.get("score_guard") or {}
    reasons = set(
        decision.get("score_guard_reasons")
        or guard.get("reasons")
        or []
    )
    if reasons - {"fundamental_evidence_missing"}:
        return "momentum_probe_evidence_gate_failed"
    if momentum_probe_rank(decision) < PAPER_MOMENTUM_PROBE_MIN_RAW_SCORE:
        return "momentum_probe_raw_score_too_low"

    discovery = evidence.get("market_discovery") or {}
    discovery_score = float(
        decision.get("discovery_score")
        or discovery.get("discovery_score")
        or 0
    )
    if discovery_score < PAPER_MOMENTUM_PROBE_MIN_DISCOVERY_SCORE:
        return "momentum_probe_discovery_score_too_low"
    buy_signals = int(decision.get("buy_signals") or 0)
    sell_signals = int(decision.get("sell_signals") or 0)
    if buy_signals < 1:
        return "momentum_probe_technical_confirmation_too_weak"
    if sell_signals > buy_signals:
        return "momentum_probe_technical_balance_negative"
    sources = {
        str(source).strip().lower()
        for source in (
            decision.get("market_sources") or discovery.get("sources") or []
        )
        if str(source).strip()
    }
    if len(sources) < 2:
        return "momentum_probe_independent_sources_insufficient"
    return ""


def is_momentum_probe_candidate(decision: dict[str, Any]) -> bool:
    """Return whether a guarded neutral merits a bounded opening recheck."""
    return momentum_probe_candidate_rejection_reason(decision) == ""


def momentum_probe_rejection_reason(decision: dict[str, Any]) -> str:
    """Require fresh opening strength before a small simulated position."""
    reason = momentum_probe_candidate_rejection_reason(decision)
    if reason:
        return reason
    price = float(decision.get("market_price") or 0)
    if price <= 0:
        return "momentum_probe_market_price_missing"
    change_pct = float(decision.get("market_change_pct") or 0)
    if change_pct < PAPER_MOMENTUM_PROBE_MIN_CHANGE_PCT:
        return "momentum_probe_opening_strength_too_weak"
    if change_pct > PAPER_MOMENTUM_PROBE_MAX_CHANGE_PCT:
        return "momentum_probe_opening_move_too_extended"
    if float(decision.get("market_volume_ratio") or 0) < 1.0:
        return "momentum_probe_volume_ratio_too_low"
    active_ratio = decision.get("market_active_volume_ratio")
    if active_ratio is None or float(active_ratio) <= 0:
        return "momentum_probe_active_buying_not_confirmed"
    return ""


def is_momentum_probe_approved(decision: dict[str, Any]) -> bool:
    """Return whether a fresh quote confirms the small observation entry."""
    return momentum_probe_rejection_reason(decision) == ""


def bounded_position_cap(requested: float | None = None) -> float:
    """Allow a stricter configured cap but never more than the hard 20% cap."""
    if requested is None:
        return PAPER_MAX_POSITION_PCT
    return min(PAPER_MAX_POSITION_PCT, max(0.0, float(requested)))


def position_exit_reason(
    position: dict[str, Any],
    decision: dict[str, Any],
    current_price: float,
    holding_days: int,
    high_price: float | None = None,
) -> str:
    """Return an auditable exit reason for a held position, or an empty string.

    Every position is subject to the hard loss and absolute holding limits.
    Explicit deep BUY support only exempts a position from softer neutral exit
    rules. Data freshness, T+1, and price-limit checks remain execution
    concerns in the database layer.
    """
    average_cost = float(position.get("avg_cost") or 0)
    price = float(current_price or 0)
    if average_cost <= 0 or price <= 0:
        return ""

    score = float(decision.get("ai_score") or 50)
    direction = decision_direction(decision)
    deep_rating = _entry_deep_rating(position, decision)
    return_pct = (price / average_cost - 1.0) * 100

    if direction == "sell" or score < 45:
        return f"explicit_bearish_signal:score={score:.1f};direction={direction}"
    if return_pct <= -PAPER_HARD_STOP_LOSS_PCT + 1e-6:
        return (
            f"hard_stop_loss=-{PAPER_HARD_STOP_LOSS_PCT:.0f}%;"
            f"return={return_pct:.1f}%"
        )
    if holding_days >= PAPER_MAX_HOLDING_DAYS:
        return f"max_holding_days={PAPER_MAX_HOLDING_DAYS}"
    if deep_rating in TRADINGAGENTS_BUY_RATINGS:
        return ""
    if (
        high_price is not None
        and high_price > 0
        and return_pct >= PAPER_PROFIT_RETRACE_MIN_GAIN_PCT
        and price <= high_price * (1 - PAPER_PROFIT_RETRACE_PCT / 100)
    ):
        return (
            "profit_retrace_protection="
            f"{PAPER_PROFIT_RETRACE_PCT:.0f}%;return={return_pct:.1f}%"
        )
    if return_pct >= PAPER_NEUTRAL_PROFIT_LOCK_PCT - 1e-6:
        return f"neutral_profit_lock=12%;return={return_pct:.1f}%"
    if holding_days >= PAPER_NEUTRAL_FORCE_EXIT_AFTER_DAYS:
        return f"neutral_max_holding_days={PAPER_NEUTRAL_FORCE_EXIT_AFTER_DAYS}"
    if holding_days >= PAPER_NEUTRAL_EXIT_AFTER_DAYS and score < PAPER_NEUTRAL_EXIT_SCORE:
        return (
            f"neutral_timeout={PAPER_NEUTRAL_EXIT_AFTER_DAYS}d;"
            f"score={score:.1f}<{PAPER_NEUTRAL_EXIT_SCORE:.0f}"
        )
    return ""
