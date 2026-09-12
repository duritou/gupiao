"""Pure final-review decisions shared by execution, API and learning logs."""

from __future__ import annotations

from typing import Any

BUY_RATINGS = frozenset({"buy", "overweight"})


def final_buy_approval(
    deep_rating: Any,
    verdict: Any,
    *,
    review_available: bool,
) -> bool:
    """Return true only for a Buy/Overweight with an explicit approval."""
    rating = str(deep_rating or "").strip().lower()
    normalized_verdict = str(verdict or "").strip().lower()
    return (
        rating in BUY_RATINGS
        and bool(review_available)
        and normalized_verdict == "approve"
    )
