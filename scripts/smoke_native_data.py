"""Read-only smoke test for Adaptive's native market-data adapters.

The command probes public Sina, CNINFO, and Eastmoney endpoints without
writing market, paper-trading, or journal data.  It reports source metadata,
cache usage, record counts, and bounded error text so a scheduled/manual
check can distinguish an unavailable provider from an empty result.

Examples::

    python scripts/smoke_native_data.py
    python scripts/smoke_native_data.py --code 600519 --trade-date 2026-08-28 --strict
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

# Task Scheduler may start this file with a different working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.infrastructure.market_data.cninfo_announcements import (
    fetch_cninfo_announcements,  # noqa: E402
)
from src.infrastructure.market_data.eastmoney_billboard import (
    fetch_eastmoney_dragon_tiger,  # noqa: E402
)
from src.infrastructure.market_data.eastmoney_emotion import fetch_limit_up_sentiment  # noqa: E402
from src.infrastructure.market_data.eastmoney_news import (  # noqa: E402
    fetch_eastmoney_global_news,
    fetch_eastmoney_stock_news,
)
from src.infrastructure.market_data.eastmoney_reports import fetch_eastmoney_reports  # noqa: E402
from src.infrastructure.market_data.sina_financials import fetch_sina_financials  # noqa: E402

Probe = Callable[[], Awaitable[dict[str, Any]]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe native A-share data sources without writing local trading data."
    )
    parser.add_argument("--code", default="600519", help="A-share code (default: 600519)")
    parser.add_argument(
        "--trade-date",
        default=None,
        help="Historical date in YYYY-MM-DD (default: provider/current date)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum rows requested from row-based probes (default: 5)",
    )
    parser.add_argument(
        "--skip-global-news",
        action="store_true",
        help="Skip the market-wide Eastmoney 7x24 news probe",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 if any selected source is unavailable",
    )
    return parser.parse_args()


def _record_count(label: str, result: dict[str, Any]) -> int:
    data = result.get("data")
    if label == "financials":
        statements = data.get("statements") if isinstance(data, dict) else None
        return sum(len(rows) for rows in statements.values()) if isinstance(statements, dict) else 0
    if label == "announcements":
        return len(result.get("announcements") or [])
    if label == "reports":
        return len(result.get("reports") or [])
    if label == "dragon_tiger":
        records = data.get("records") if isinstance(data, dict) else None
        return len(records or []) if isinstance(records, list) else 0
    if label in {"stock_news", "global_news"}:
        return len(result.get("news") or [])
    if label == "emotion":
        return sum(
            int(data.get(key) or 0)
            for key in ("zt_count", "zb_count", "dt_count", "yesterday_limit_up_count")
        ) if isinstance(data, dict) else 0
    return 0


async def _probe(label: str, operation: Probe) -> tuple[str, dict[str, Any]]:
    try:
        result = await operation()
        return label, result if isinstance(result, dict) else {"_meta": {"available": False}}
    except Exception as exc:  # A smoke test must report provider failures, not hide them.
        return label, {"_meta": {"available": False, "error": f"{type(exc).__name__}: {exc}"}}


def _print_result(label: str, result: dict[str, Any]) -> bool:
    metadata = result.get("_meta") if isinstance(result.get("_meta"), dict) else {}
    available = bool(metadata.get("available"))
    provider = str(metadata.get("provider") or "unknown")
    cached = "yes" if metadata.get("cached") else "no"
    count = _record_count(label, result)
    error = str(metadata.get("error") or "").replace("\n", " ")[:180]
    # An empty historical pool (for example, no 龙虎榜 record on the date) is
    # different from a transport/provider error and should not look like a
    # broken endpoint in the smoke output.
    state = "ok" if available else (
        "empty" if not error or error.lower().startswith(("no ", "empty")) else "error"
    )
    suffix = f" error={error}" if error else ""
    print(
        f"[{label}] state={state} available={'yes' if available else 'no'} "
        f"provider={provider} cached={cached} records={count}{suffix}"
    )
    return state != "error"


async def run(args: argparse.Namespace) -> int:
    limit = max(1, min(30, int(args.limit)))
    trade_date = args.trade_date
    probes: list[tuple[str, Probe]] = [
        ("financials", lambda: fetch_sina_financials(args.code, limit=limit)),
        ("announcements", lambda: fetch_cninfo_announcements(args.code, limit=limit)),
        ("reports", lambda: fetch_eastmoney_reports(args.code, max_pages=1, limit=limit)),
        (
            "dragon_tiger",
            lambda: fetch_eastmoney_dragon_tiger(
                args.code, trade_date=trade_date, look_back=30, limit=limit
            ),
        ),
        ("stock_news", lambda: fetch_eastmoney_stock_news(args.code, page_size=limit)),
        ("emotion", lambda: fetch_limit_up_sentiment(trade_date)),
    ]
    if not args.skip_global_news:
        probes.append(("global_news", lambda: fetch_eastmoney_global_news(page_size=limit)))

    print(
        f"=== Native data smoke test: code={args.code} "
        f"trade_date={trade_date or 'provider/current'} ==="
    )
    responding = 0
    for label, operation in probes:
        _, result = await _probe(label, operation)
        if _print_result(label, result):
            responding += 1
    selected = len(probes)
    print(f"=== Sources responding: {responding}/{selected} | read_only=yes ===")
    if args.strict and responding < selected:
        return 1
    return 0 if responding else 2


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
