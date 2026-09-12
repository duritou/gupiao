"""Cross-source financial-indicator checks that never rewrite source values."""

from __future__ import annotations

from typing import Any

_ALIASES = {
    "eps": {"eps", "basic_eps", "basic- eps"},
    "roe": {"roe", "roe_avg", "roe_weighted"},
    "roa": {"roa", "roa2"},
    "revenue_yoy": {"revenue_yoy", "tr_yoy", "operating_income_yoy"},
    "profit_yoy": {"profit_yoy", "netprofit_yoy", "net_profit_yoy"},
}


def _number(value: Any) -> float | None:
    if value in (None, "", "-") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _flatten_indicators(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    flattened: dict[str, Any] = {}
    for block in data.get("abilities") or []:
        if not isinstance(block, dict):
            continue
        for item in block.get("indicators") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("index_id") or "").strip().lower()
            if key:
                flattened[key] = item.get("value")
    return flattened


def _hithink_value(metrics: dict[str, Any], aliases: set[str]) -> Any:
    for alias in aliases:
        if alias in metrics:
            return metrics[alias]
    return None


def compare_financial_indicators(
    tushare: dict[str, Any] | None,
    hithink_data: Any,
    *,
    relative_tolerance: float = 0.02,
    absolute_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Return a compact consistency summary; neither input is mutated."""
    left = dict(tushare or {})
    right = _flatten_indicators(hithink_data)
    comparisons: list[dict[str, Any]] = []
    for field, aliases in _ALIASES.items():
        left_value = _number(left.get(field))
        right_value = _number(_hithink_value(right, aliases))
        if left_value is None or right_value is None:
            continue
        tolerance = max(absolute_tolerance, abs(left_value) * relative_tolerance)
        delta = abs(left_value - right_value)
        comparisons.append(
            {
                "field": field,
                "status": "match" if delta <= tolerance else "mismatch",
                "relative_error": round(delta / max(abs(left_value), absolute_tolerance), 6),
            }
        )
    if not comparisons:
        status = "insufficient"
    else:
        mismatches = sum(item["status"] == "mismatch" for item in comparisons)
        status = "mismatch" if mismatches else "match"
    return {
        "status": status,
        "compared_fields": len(comparisons),
        "matches": sum(item["status"] == "match" for item in comparisons),
        "mismatches": sum(item["status"] == "mismatch" for item in comparisons),
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance": absolute_tolerance,
        "fields": comparisons,
        "report": (hithink_data or {}).get("report") if isinstance(hithink_data, dict) else None,
    }
