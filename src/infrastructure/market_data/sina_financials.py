"""Native Sina financial-statement adapter for Adaptive.

The adapter keeps report periods intact and exposes the raw statement rows
alongside a small set of normalized latest-period metrics used by the UI.  It
is deliberately independent of Vibe so a financials request can stay inside
Adaptive's data layer.  A missing or malformed response is reported as
unavailable; no values are synthesized.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from src.infrastructure.market_data.stock_skill_bridge import normalize_stock_code

SINA_FINANCIAL_URL = (
    "https://quotes.sina.cn/cn/api/openapi.php/"
    "CompanyFinanceService.getFinanceReport2022"
)
_REPORT_TYPES = {
    "balance_sheet": "fzb",
    "income_statement": "lrb",
    "cash_flow_statement": "llb",
}
_SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}


def _plain_code(code: str) -> tuple[str, str] | None:
    normalized = normalize_stock_code(code)
    if not normalized:
        return None
    plain, exchange = normalized.split(".", 1)
    if exchange not in {"SH", "SZ"}:
        return None
    return plain, exchange.lower()


def _report_date(period: object) -> str:
    text = str(period or "").strip()
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def _row_from_period(period: object, payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    date_text = _report_date(period)
    row: dict[str, Any] = {
        "report_date": date_text,
        "\u62a5\u544a\u671f": date_text,
    }
    items = payload.get("data")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("item_title") or "").strip()
        if not title or item.get("item_value") is None:
            continue
        row[title] = item.get("item_value")
        yoy = item.get("item_tongbi")
        if yoy not in (None, ""):
            row[f"{title}_\u540c\u6bd4"] = yoy
    return row if len(row) > 2 else None


def parse_sina_financial_payload(payload: object, *, limit: int = 8) -> list[dict[str, Any]]:
    """Parse Sina's ``result.data.report_list`` response into dated rows."""
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    report_list = data.get("report_list") if isinstance(data, dict) else None
    if not isinstance(report_list, dict):
        return []

    rows: list[dict[str, Any]] = []
    for period in sorted(report_list, key=lambda value: str(value), reverse=True):
        row = _row_from_period(period, report_list[period])
        if row:
            rows.append(row)
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def _label_key(value: object) -> str:
    return re.sub(r"[\s()（）_\-/]", "", str(value or "")).lower()


def _metric(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    wanted = {_label_key(alias) for alias in aliases}
    for key, value in row.items():
        if key.endswith("_\u540c\u6bd4") or key in {"report_date", "\u62a5\u544a\u671f"}:
            continue
        if _label_key(key) in wanted:
            return value
    return None


def _metric_yoy(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    wanted = {_label_key(alias) for alias in aliases}
    suffix = "_\u540c\u6bd4"
    for key, value in row.items():
        if not key.endswith(suffix):
            continue
        if _label_key(key[: -len(suffix)]) in wanted:
            return value
    return None


def _latest_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    latest = rows[0]
    summary: dict[str, Any] = {
        "period": latest.get("report_date", ""),
        "report_date": latest.get("report_date", ""),
    }
    metrics = {
        "revenue": ("\u8425\u4e1a\u6536\u5165", "\u8425\u4e1a\u603b\u6536\u5165"),
        "net_profit": (
            "\u51c0\u5229\u6da6",
            "\u5f52\u5c5e\u4e8e\u6bcd\u516c\u53f8\u80a1\u4e1c\u7684\u51c0\u5229\u6da6",
            "\u5f52\u5c5e\u6bcd\u516c\u53f8\u80a1\u4e1c\u7684\u51c0\u5229\u6da6",
        ),
        "eps": ("\u57fa\u672c\u6bcf\u80a1\u6536\u76ca", "\u6bcf\u80a1\u6536\u76ca", "EPS"),
        "roe": (
            "\u51c0\u8d44\u4ea7\u6536\u76ca\u7387",
            "\u52a0\u6743\u51c0\u8d44\u4ea7\u6536\u76ca\u7387",
            "ROE",
        ),
        "bvps": ("\u6bcf\u80a1\u51c0\u8d44\u4ea7", "BVPS"),
        "net_margin": ("\u9500\u552e\u51c0\u5229\u7387", "\u51c0\u5229\u7387"),
    }
    for field, aliases in metrics.items():
        value = _metric(latest, aliases)
        if value is not None:
            summary[field] = value
        yoy = _metric_yoy(latest, aliases)
        if yoy is not None and field in {"revenue", "net_profit"}:
            summary[f"{field}_yoy"] = yoy
    return summary


async def _fetch_statement(
    client: httpx.AsyncClient,
    plain: str,
    market: str,
    source: str,
    limit: int,
) -> list[dict[str, Any]]:
    response = await client.get(
        SINA_FINANCIAL_URL,
        params={
            "paperCode": f"{market}{plain}",
            "source": source,
            "type": "0",
            "page": "1",
            "num": str(limit),
        },
    )
    response.raise_for_status()
    return parse_sina_financial_payload(response.json(), limit=limit)


async def fetch_sina_financials(code: str, *, limit: int = 8) -> dict[str, Any]:
    """Fetch all three Sina statements with explicit point-in-time metadata."""
    parsed = _plain_code(code)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if parsed is None:
        return {
            "data": {},
            "_meta": {
                "provider": "sina",
                "source_layer": "adaptive_native",
                "available": False,
                "historical": True,
                "error": "invalid A-share code",
                "fetched_at": fetched_at,
            },
        }

    plain, market = parsed
    statements: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    timeout = httpx.Timeout(connect=3.0, read=8.0, write=2.0, pool=1.0)

    async def fetch_one(
        client: httpx.AsyncClient, name: str, source: str
    ) -> tuple[str, list[dict[str, Any]], str]:
        try:
            rows = await _fetch_statement(client, plain, market, source, max(1, int(limit)))
            return name, rows, ""
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return name, [], f"{name}: {str(exc)[:120]}"

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=_SINA_HEADERS,
            follow_redirects=True,
        ) as client:
            results = await asyncio.gather(
                *(fetch_one(client, name, source) for name, source in _REPORT_TYPES.items())
            )
            for name, rows, error in results:
                statements[name] = rows
                if error:
                    errors.append(error)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        errors.append(str(exc)[:120])

    available_statements = {name: rows for name, rows in statements.items() if rows}
    income_rows = statements.get("income_statement", [])
    latest = _latest_summary(income_rows)
    latest_date = max(
        (row.get("report_date", "") for rows in statements.values() for row in rows),
        default="",
    )
    data = {
        **latest,
        "code": f"{plain}.{market.upper()}",
        "statements": available_statements,
        "income_statement": statements.get("income_statement", []),
        "balance_sheet": statements.get("balance_sheet", []),
        "cash_flow_statement": statements.get("cash_flow_statement", []),
        "latest_report_date": latest_date,
    }
    return {
        "data": data if available_statements else {},
        "_meta": {
            "provider": "sina",
            "source_name": "Sina financial statements",
            "source_url": SINA_FINANCIAL_URL,
            "source_layer": "adaptive_native",
            "available": bool(available_statements),
            "historical": True,
            "point_in_time": True,
            "report_periods": {name: len(rows) for name, rows in statements.items()},
            "latest_report_date": latest_date,
            "fetched_at": fetched_at,
            "error": "; ".join(errors) if errors and not available_statements else "",
        },
    }
