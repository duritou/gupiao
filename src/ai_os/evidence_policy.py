"""Per-candidate evidence rules shared by ranking, research and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_NON_MARKET_SOURCES = frozenset({"", "portfolio_review", "local_fallback"})


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _market_sources(payload: dict[str, Any]) -> set[str]:
    sources = payload.get("market_sources") or payload.get("sources") or []
    result = {
        str(source or "").strip().lower()
        for source in sources
        if str(source or "").strip()
    }
    result.difference_update(_NON_MARKET_SOURCES)
    return result


def _quote(payload: dict[str, Any]) -> dict[str, Any]:
    quote = payload.get("quote")
    if isinstance(quote, dict):
        return quote
    skill = payload.get("stock_skill_evidence") or {}
    quote = skill.get("quote") if isinstance(skill, dict) else {}
    return quote if isinstance(quote, dict) else {}


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Immutable explanation of the evidence state for one candidate."""

    market_sources: tuple[str, ...]
    quote_available: bool
    market_complete: bool
    fundamental_available: bool
    reasons: tuple[str, ...]

    @property
    def deep_eligible(self) -> bool:
        return self.market_complete


def assess_evidence(
    payload: dict[str, Any],
    *,
    deep_result: dict[str, Any] | None = None,
) -> EvidenceAssessment:
    """Assess evidence without changing scores or deciding BUY/SELL."""
    sources = _market_sources(payload)
    quote = _quote(payload)
    price = payload.get("market_price") or quote.get("price")
    quote_available = _positive_number(price)
    reasons: list[str] = []
    if not sources:
        reasons.append("market_sources_missing")
    if not quote_available:
        reasons.append("market_quote_missing")

    fundamental_available = bool(payload.get("fundamental_evidence_available"))
    deep = deep_result or {}
    if bool(deep.get("available")) and not deep.get("evidence_gaps"):
        fundamental_available = True
    return EvidenceAssessment(
        market_sources=tuple(sorted(sources)),
        quote_available=quote_available,
        market_complete=bool(sources) and quote_available,
        fundamental_available=fundamental_available,
        reasons=tuple(reasons),
    )
