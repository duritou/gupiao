"""Conservative HiThink financial-history normalization and merge rules."""

from __future__ import annotations

from typing import Any

from src.infrastructure.market_data.hithink_contracts import (
    date_text,
    normalize_thscode,
    timestamp_iso,
)

_STATEMENT_NAMES = {
    "income": "income",
    "balance": "balancesheet",
    "balancesheet": "balancesheet",
    "cashflow": "cashflow",
}


def _date(value: Any) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return timestamp_iso(value)[:10]
    return date_text(value)


def normalize_financial_statements(
    data: Any,
    code: str,
) -> dict[str, list[dict[str, Any]]]:
    """Map HiThink statement rows to the storage contract without filling nulls."""
    if not isinstance(data, dict):
        return {}
    try:
        default_code = normalize_thscode(code)
    except ValueError:
        default_code = str(code or "").strip().upper()
    result: dict[str, list[dict[str, Any]]] = {}
    for raw_name, raw_rows in (data.get("statements") or {}).items():
        statement_name = _STATEMENT_NAMES.get(str(raw_name).lower())
        if not statement_name or not isinstance(raw_rows, list):
            continue
        normalized: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            end_date = _date(raw.get("period_end_ms") or raw.get("end_date"))
            if not end_date:
                continue
            announcement_date = _date(raw.get("report_date_ms") or raw.get("ann_date"))
            row = dict(raw)
            row.update(
                {
                    "ts_code": str(raw.get("thscode") or default_code).upper(),
                    "end_date": end_date,
                    "report_date": end_date,
                    "ann_date": announcement_date,
                    "f_ann_date": announcement_date,
                    "source": "hithink",
                }
            )
            normalized.append(row)
        normalized.sort(
            key=lambda row: (row.get("end_date", ""), row.get("ann_date", "")), reverse=True
        )
        result[statement_name] = normalized
    return result


def missing_financial_rows(
    existing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Return only report periods absent from local history; never overwrite."""
    target = max(1, int(limit))
    additions: dict[str, list[dict[str, Any]]] = {}
    for statement_name, rows in incoming.items():
        known = {
            str(row.get("end_date") or row.get("report_date") or "")[:10]
            for row in (existing.get(statement_name) or [])
        }
        selected: list[dict[str, Any]] = []
        for row in rows:
            period = str(row.get("end_date") or row.get("report_date") or "")[:10]
            if not period or period in known:
                continue
            selected.append(row)
            known.add(period)
            if len(existing.get(statement_name) or []) + len(selected) >= target:
                break
        if selected:
            additions[statement_name] = selected
    return additions
