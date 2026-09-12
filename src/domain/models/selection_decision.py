"""Typed state contract for cross-stage stock selection decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DIRECTIONS = frozenset({"buy", "sell", "neutral"})


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _direction(value: Any) -> str:
    normalized = str(value or "neutral").strip().lower()
    return normalized if normalized in _DIRECTIONS else "neutral"


@dataclass(frozen=True, slots=True)
class SelectionDecisionContract:
    """Immutable view of the fields shared by ranking and execution stages."""

    stock_code: str
    ranking_score: float
    action_score: float
    predicted_direction: str
    executable_direction: str
    decision_status: str
    actionable: bool
    score_guard_reasons: tuple[str, ...]

    @classmethod
    def from_mapping(cls, decision: dict[str, Any]) -> SelectionDecisionContract:
        reasons = tuple(
            str(reason).strip()
            for reason in decision.get("score_guard_reasons") or []
            if str(reason).strip()
        )
        return cls(
            stock_code=str(decision.get("stock_code") or "").strip().upper(),
            ranking_score=_number(
                decision.get("ranking_score", decision.get("raw_ai_score", 0))
            ),
            action_score=_number(
                decision.get("action_score", decision.get("ai_score", 50)),
                50.0,
            ),
            predicted_direction=_direction(
                decision.get("predicted_direction", decision.get("direction"))
            ),
            executable_direction=_direction(
                decision.get("executable_direction", decision.get("direction"))
            ),
            decision_status=str(decision.get("decision_status") or "unknown"),
            actionable=decision.get("actionable") is True,
            score_guard_reasons=reasons,
        )


def normalize_decision_fields(decision: dict[str, Any]) -> SelectionDecisionContract:
    """Fill contract aliases without changing an existing score or decision."""
    decision.setdefault(
        "ranking_score",
        decision.get("raw_ai_score", decision.get("ai_score", 50.0)),
    )
    decision.setdefault("action_score", decision.get("ai_score", 50.0))
    decision.setdefault(
        "predicted_direction", decision.get("direction", "neutral")
    )
    reasons = decision.get("score_guard_reasons") or []
    decision.setdefault(
        "executable_direction",
        decision.get("direction", "neutral") if not reasons else "neutral",
    )
    decision.setdefault("actionable", False)
    return SelectionDecisionContract.from_mapping(decision)
