"""Read-only Tushare capability probe for the configured account.

This script deliberately probes one stock and one recent trading day.  It does
not print the token, write market data, or claim that an empty result means a
permission failure.

Usage:
    .venv\\Scripts\\python.exe scripts/probe_tushare.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.infrastructure.market_data.tushare_provider import tushare_provider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Tushare endpoint permissions and data.")
    parser.add_argument("--code", default="600519.SH", help="One A-share code to probe.")
    parser.add_argument("--trade-date", default="", help="YYYY-MM-DD; defaults to latest open day.")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Also probe optional news, announcement, report and event endpoints.",
    )
    return parser.parse_args()


def _classify_error(error: Exception) -> str:
    message = str(error).lower()
    if any(word in message for word in ("permission", "权限", "积分", "access denied")):
        return "permission_denied"
    if "empty" in message:
        return "empty"
    return "transient_error"


async def _probe(
    endpoint: str,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        payload = await tushare_provider._call(endpoint, **kwargs)
        rows = payload.data.to_dict("records")
        dates = [str(row.get("trade_date") or row.get("cal_date") or "") for row in rows]
        return {
            "endpoint": endpoint,
            "status": "supported",
            "row_count": len(rows),
            "data_date": max((item for item in dates if item), default=""),
        }
    except Exception as exc:
        return {
            "endpoint": endpoint,
            "status": _classify_error(exc),
            "row_count": 0,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


async def run_probe(code: str, trade_date: str, extended: bool = False) -> dict[str, Any]:
    if not tushare_provider.configured:
        return {"status": "not_configured", "endpoints": []}
    dates = await tushare_provider.recent_trade_dates(1)
    target = (trade_date or (dates[-1] if dates else "")).replace("-", "")
    if not target:
        return {"status": "calendar_unavailable", "endpoints": []}

    code = code.strip().upper()
    probes = [
        ("trade_cal", {"exchange": "", "start_date": target, "end_date": target}),
        (
            "stock_basic",
            {"exchange": "", "list_status": "L", "fields": "ts_code,name,industry,list_date"},
        ),
        ("daily", {"ts_code": code, "trade_date": target}),
        ("daily_basic", {"ts_code": code, "trade_date": target}),
        ("adj_factor", {"ts_code": code, "trade_date": target}),
        ("index_basic", {"market": ""}),
        ("index_daily", {"ts_code": "000300.SH", "trade_date": target}),
        ("index_dailybasic", {"ts_code": "000300.SH", "trade_date": target}),
        ("moneyflow", {"ts_code": code, "trade_date": target}),
        ("fina_indicator", {"ts_code": code, "limit": 1}),
        ("income", {"ts_code": code, "limit": 1}),
        ("balancesheet", {"ts_code": code, "limit": 1}),
        ("cashflow", {"ts_code": code, "limit": 1}),
        ("stk_limit", {"ts_code": code, "trade_date": target}),
        ("suspend_d", {"ts_code": code, "trade_date": target}),
        ("margin", {"ts_code": code, "trade_date": target}),
        ("top_list", {"trade_date": target}),
    ]
    if extended:
        probes.extend(
            [
                ("anns_d", {"ts_code": code, "start_date": target, "end_date": target}),
                (
                    "news",
                    {
                        "start_date": target + " 00:00:00",
                        "end_date": target + " 23:59:59",
                        "src": "sina",
                    },
                ),
                (
                    "major_news",
                    {
                        "src": "sina",
                        "start_date": target + " 00:00:00",
                        "end_date": target + " 23:59:59",
                    },
                ),
                ("report_rc", {"ts_code": code, "start_date": target, "end_date": target}),
                ("block_trade", {"ts_code": code, "trade_date": target}),
                ("margin_detail", {"ts_code": code, "trade_date": target}),
                ("index_member_all", {"index_code": "000300.SH"}),
            ]
        )
    results = []
    for endpoint, kwargs in probes:
        results.append(await _probe(endpoint, **kwargs))
    supported = sum(item["status"] == "supported" for item in results)
    return {
        "status": "completed",
        "code": code,
        "trade_date": target[:4] + "-" + target[4:6] + "-" + target[6:],
        "supported_count": supported,
        "endpoint_count": len(results),
        "endpoints": results,
    }


def main() -> int:
    args = parse_args()
    result = asyncio.run(run_probe(args.code, args.trade_date, args.extended))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
