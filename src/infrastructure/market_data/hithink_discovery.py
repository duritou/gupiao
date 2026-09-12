"""HiThink special-data projection for remote market discovery.

The adapter deliberately returns discovery-shaped rows rather than leaking
provider payloads into the ranking pipeline.  The caller decides whether the
rows are shadow-only, primary, or fallback data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.infrastructure.market_data.hithink_contracts import normalize_thscode
from src.infrastructure.market_data.hithink_provider import hithink_provider


@dataclass(frozen=True)
class HiThinkDiscoveryResult:
    """Normalized special-data rows and a redacted audit observation."""

    sources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)


def _concepts(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return [text for item in values if (text := str(item or "").strip())]


def _row(item: dict[str, Any], *, rank: int, kind: str) -> dict[str, Any] | None:
    raw_code = item.get("thscode") or item.get("ticker")
    try:
        code = normalize_thscode(str(raw_code or ""))
    except ValueError:
        return None
    reason = item.get("limit_up_reason")
    if not reason:
        reason = {
            "limit_up": "涨停池",
            "limit_break": "炸板池",
            "dragon_tiger": "龙虎榜",
        }.get(kind, "HiThink特色数据")
    raw_rank = item.get("hot_rank") or item.get("rank")
    try:
        normalized_rank = int(float(raw_rank)) if raw_rank not in (None, "") else rank
    except (TypeError, ValueError):
        normalized_rank = rank
    return {
        "code": code,
        "name": item.get("name") or "",
        "rank": max(1, normalized_rank),
        "reason": str(reason),
        "concepts": _concepts(item.get("concept_list")),
        "hithink_kind": kind,
        "hithink_data_date": item.get("trade_date") or item.get("data_date"),
    }


def _rows(items: Any, *, kind: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        row = _row(item, rank=rank, kind=kind)
        if row is not None:
            result.append(row)
    return result


async def fetch_hithink_special(
    day: str,
    limit: int,
    *,
    provider: Any | None = None,
) -> HiThinkDiscoveryResult:
    """Fetch bounded special-data observations with no raw-payload logging."""
    provider = provider or hithink_provider
    if not bool(getattr(provider, "configured", False)):
        return HiThinkDiscoveryResult(
            observation={"status": "skipped", "reason": "not_configured", "row_count": 0}
        )

    size = max(1, min(200, max(int(limit) * 3, 50)))
    requests = (
        ("hithink_limit_up", "limit_up", provider.fetch_limit_pool("up", day, size=size)),
        ("hithink_limit_break", "limit_break", provider.fetch_limit_pool("break", day, size=size)),
        ("hithink_dragon_tiger", "dragon_tiger", provider.fetch_dragon_tiger(day)),
    )
    sources: dict[str, list[dict[str, Any]]] = {}
    successes: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for source_name, kind, request in requests:
        try:
            payload = await request
        except Exception as exc:
            failures.append({"source": source_name, "error_type": type(exc).__name__})
            continue
        rows = payload.data.get("item", []) if kind != "dragon_tiger" else payload.data.get("stock_items", [])
        normalized = _rows(rows, kind=kind)
        sources[source_name] = normalized
        successes.append(
            {
                "source": source_name,
                "row_count": len(normalized),
                "data_date": payload.data_date or None,
                "request_id": payload.request_id or None,
            }
        )
    row_count = sum(len(rows) for rows in sources.values())
    status = "ok" if successes and not failures else "partial" if successes else "failed"
    return HiThinkDiscoveryResult(
        sources=sources,
        observation={
            "status": status,
            "row_count": row_count,
            "successes": successes,
            "failures": failures,
        },
    )
