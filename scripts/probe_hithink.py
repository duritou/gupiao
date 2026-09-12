"""Read-only, bounded HiThink canary probe.

The probe records capability-level health only.  It never persists raw
provider payloads, request headers, or credentials.

Usage:
    .venv\\Scripts\\python.exe scripts\\probe_hithink.py --capability snapshot
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.infrastructure.market_data.hithink_provider import hithink_provider

_CAPABILITIES = (
    "snapshot",
    "valuation",
    "daily_kline",
    "financial_indicators",
    "limit_up_pool",
    "limit_break_pool",
    "dragon_tiger",
)


def _report_for_today(today: date | None = None) -> str:
    """Use the latest completed quarter instead of the in-progress one."""
    current = today or datetime.now().date()
    quarter = (current.month - 1) // 3 + 1
    if quarter == 1:
        return f"{current.year - 1}-4"
    return f"{current.year}-{quarter - 1}"


def _classify_error(exc: Exception) -> str:
    return str(getattr(exc, "category", "") or type(exc).__name__).lower()[:80]


def _row_count(payload: Any) -> int:
    if isinstance(getattr(payload, "data", None), list):
        return len(payload.data)
    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        for key in ("item", "stock_items", "abilities"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return int(getattr(payload, "row_count", 0) or 0)


def _payload_summary(payload: Any, elapsed_ms: float) -> dict[str, Any]:
    return {
        "status": "supported",
        "row_count": _row_count(payload),
        "data_date": str(getattr(payload, "data_date", "") or "")[:10],
        "is_live": bool(getattr(payload, "is_live", False)),
        "elapsed_ms": round(elapsed_ms, 2),
        "request_id": str(getattr(payload, "request_id", "") or "")[:120],
    }


def _probe_callers(code: str) -> dict[str, Callable[[], Awaitable[Any]]]:
    today = datetime.now().date().isoformat()
    start = (datetime.now().date()).isoformat()
    return {
        "snapshot": lambda: hithink_provider.fetch_snapshot(code),
        "valuation": lambda: hithink_provider.fetch_valuation_snapshot(code),
        "daily_kline": lambda: hithink_provider.fetch_daily_history(
            code, start, today, adjust="none"
        ),
        "financial_indicators": lambda: hithink_provider.fetch_financial_indicators(
            code, _report_for_today()
        ),
        "limit_up_pool": lambda: hithink_provider.fetch_limit_pool("up", today, page=1, size=50),
        "limit_break_pool": lambda: hithink_provider.fetch_limit_pool(
            "break", today, page=1, size=50
        ),
        "dragon_tiger": lambda: hithink_provider.fetch_dragon_tiger(today),
    }


async def run_probe(
    code: str = "600519.SH",
    capabilities: tuple[str, ...] | list[str] | None = None,
    *,
    provider: Any = hithink_provider,
) -> dict[str, Any]:
    """Run selected probes sequentially and return a redacted health summary."""
    if not bool(getattr(provider, "configured", False)):
        return {"status": "not_configured", "code": code, "results": []}
    selected = tuple(capabilities or _CAPABILITIES)
    unknown = [name for name in selected if name not in _CAPABILITIES]
    if unknown:
        raise ValueError(f"unknown_capability:{','.join(unknown)}")
    callers = _probe_callers(code)
    # Make the helper testable without changing the production singleton.
    if provider is not hithink_provider:
        callers = _probe_callers_for_provider(code, provider)
    results: list[dict[str, Any]] = []
    for capability in selected:
        started = time.perf_counter()
        try:
            payload = await callers[capability]()
            results.append(
                {
                    "capability": capability,
                    **_payload_summary(payload, (time.perf_counter() - started) * 1000),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "capability": capability,
                    "status": "failed",
                    "error_type": _classify_error(exc),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
    supported = sum(item["status"] == "supported" for item in results)
    return {
        "status": "completed" if supported else "failed",
        "code": code,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "capability_count": len(results),
        "supported_count": supported,
        "results": results,
        "runtime_stats": provider.runtime_stats() if hasattr(provider, "runtime_stats") else {},
    }


def _probe_callers_for_provider(
    code: str, provider: Any
) -> dict[str, Callable[[], Awaitable[Any]]]:
    today = datetime.now().date().isoformat()
    return {
        "snapshot": lambda: provider.fetch_snapshot(code),
        "valuation": lambda: provider.fetch_valuation_snapshot(code),
        "daily_kline": lambda: provider.fetch_daily_history(code, today, today, adjust="none"),
        "financial_indicators": lambda: provider.fetch_financial_indicators(
            code, _report_for_today()
        ),
        "limit_up_pool": lambda: provider.fetch_limit_pool("up", today, page=1, size=50),
        "limit_break_pool": lambda: provider.fetch_limit_pool("break", today, page=1, size=50),
        "dragon_tiger": lambda: provider.fetch_dragon_tiger(today),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded HiThink health probe.")
    parser.add_argument("--code", default="600519.SH", help="One A-share code to probe.")
    parser.add_argument(
        "--capability",
        action="append",
        choices=_CAPABILITIES,
        help="Probe one capability; repeat the option for multiple capabilities.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON summary output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(run_probe(args.code.strip().upper(), tuple(args.capability or ())))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
