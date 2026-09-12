"""Carry-forward observation for recently high-ranked stocks.

This module is intentionally outside the selection and execution pipeline.  It
only makes recent high-ranked names visible for follow-up when today's
evidence is incomplete or the ranking moves sharply.
"""

from collections import defaultdict
from typing import Any, Iterable


DEFAULT_LOOKBACK_SESSIONS = 3
DEFAULT_MAX_ITEMS = 10
DEFAULT_MIN_RANKING_SCORE = 65.0
DEFAULT_MAX_RANK_PER_SESSION = 10


def _code(item: dict[str, Any]) -> str:
    return str(item.get("stock_code") or item.get("code") or "").strip()


def _number(item: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = item.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return 0.0


def _rank_score(item: dict[str, Any]) -> float:
    return _number(item, "ranking_score", "raw_ai_score", "ai_score", "action_score")


def _reasons(item: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return [str(reason) for reason in value if str(reason).strip()]
        if value:
            return [str(value)]
    return []


def _best_per_code(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep the first row for each code; DB results are newest-first."""
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        code = _code(item)
        if code and code not in result:
            result[code] = item
    return result


def build_continuity_watchlist(
    history: Iterable[dict[str, Any]],
    current: Iterable[dict[str, Any]] | None = None,
    *,
    current_date: str = "",
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    max_items: int = DEFAULT_MAX_ITEMS,
    min_ranking_score: float = DEFAULT_MIN_RANKING_SCORE,
) -> list[dict[str, Any]]:
    """Build an observation-only carry-forward list.

    A stock qualifies when it was in the previous session's top ranked names
    with a sufficient ranking score.  The result is informational only: it
    never changes today's ranking, publication gate, position sizing, or
    execution decisions.
    """
    history_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in history:
        if not isinstance(item, dict):
            continue
        date = str(item.get("decision_date") or "").strip()
        if date and _code(item):
            history_by_date[date].append(item)

    if not current_date:
        current_date = max(history_by_date, default="")
    if not current_date or lookback_sessions <= 0 or max_items <= 0:
        return []

    current_rows = _best_per_code(current or [])
    current_ranked = sorted(
        current_rows.values(),
        key=lambda item: (-_rank_score(item), _code(item)),
    )
    current_by_code = {
        _code(item): (rank, item)
        for rank, item in enumerate(current_ranked, start=1)
    }

    prior_dates = sorted(
        (date for date in history_by_date if date < current_date),
        reverse=True,
    )[:lookback_sessions]
    observed_dates = sorted(
        {current_date, *history_by_date.keys()},
        reverse=True,
    )
    date_position = {date: position for position, date in enumerate(observed_dates)}

    carried: dict[str, dict[str, Any]] = {}
    for previous_date in prior_dates:
        previous_rows = _best_per_code(history_by_date[previous_date])
        previous_ranked = sorted(
            previous_rows.values(),
            key=lambda item: (-_rank_score(item), _code(item)),
        )
        for previous_rank, item in enumerate(previous_ranked, start=1):
            previous_score = _rank_score(item)
            if previous_rank > DEFAULT_MAX_RANK_PER_SESSION or previous_score < min_ranking_score:
                continue
            code = _code(item)
            if code in carried:
                continue
            current_rank, current_item = current_by_code.get(code, (None, {}))
            carried[code] = {
                "stock_code": code,
                "stock_name": item.get("stock_name") or code,
                "observation_only": True,
                "execution_allowed": False,
                "observation_reason": "前一交易日高排名延续观察，不改变当前买卖门控",
                "previous_decision_date": previous_date,
                "sessions_since_previous": date_position.get(previous_date, 1),
                "previous_rank": previous_rank,
                "previous_ranking_score": previous_score,
                "previous_action_score": _number(item, "action_score", "ai_score"),
                "previous_recommendation": item.get("recommendation", ""),
                "previous_decision_status": item.get("decision_status", "unknown"),
                "previous_score_guarded": bool(item.get("score_guarded")),
                "previous_guard_reasons": _reasons(item, "score_guard_reasons", "publication_block_reasons"),
                "current_rank": current_rank,
                "current_ranking_score": _rank_score(current_item) if current_item else None,
                "current_action_score": _number(current_item, "action_score", "ai_score") if current_item else None,
                "current_decision_status": current_item.get("decision_status", "not_in_current_scan") if current_item else "not_in_current_scan",
                "current_recommendation": current_item.get("recommendation", "") if current_item else "",
                "current_guard_reasons": _reasons(current_item, "score_guard_reasons", "publication_block_reasons") if current_item else [],
                "current_evidence_status": current_item.get("evidence_status", "unknown") if current_item else "missing",
            }

    return sorted(
        carried.values(),
        key=lambda item: (
            int(item["sessions_since_previous"]),
            int(item["previous_rank"]),
            -float(item["previous_ranking_score"]),
            str(item["stock_code"]),
        ),
    )[:max_items]
