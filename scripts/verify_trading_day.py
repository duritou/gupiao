"""Verify live A-share data sources for the daily Task Scheduler job.

The check is safe to run every morning. It respects the official trading
calendar when available, reports iFind separately from the provider fallback,
and only fails on a trading day when no real-time quote can be obtained.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_PYTHON = PROJECT_ROOT.parent / "shared" / "python"
for path in (PROJECT_ROOT, SHARED_PYTHON):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from investment_common import load_runtime_env  # noqa: E402

load_runtime_env(PROJECT_ROOT)

from src.ai_os.trading_calendar import get_trading_day_status  # noqa: E402
from src.infrastructure.market_data.ifind_provider import ifind  # noqa: E402
from src.infrastructure.market_data.source_manager import source_manager  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify iFind and fallback A-share quote sources.")
    parser.add_argument("--code", default="600000.SH", help="A-share symbol used for the probe.")
    parser.add_argument(
        "--require-ifind",
        action="store_true",
        help="Fail when iFind itself is unavailable instead of accepting a fallback provider.",
    )
    return parser.parse_args()


def _ifind_configured() -> bool:
    return bool(os.getenv("IFIND_REFRESH_TOKEN") or os.getenv("IFIND_ACCESS_KEY"))


async def verify(code: str, *, require_ifind: bool) -> int:
    calendar = await get_trading_day_status()
    print(
        f"calendar: trading_day={calendar.is_trading_day} source={calendar.source}",
        flush=True,
    )
    if not calendar.is_trading_day:
        print("verification skipped: non-trading day", flush=True)
        return 0

    ifind_quote = await asyncio.to_thread(ifind.get_quote, code)
    fallback_quote, provenance = await source_manager.get_realtime_quote(code)
    if ifind_quote is not None and ifind_quote.price:
        print(f"ifind: OK price={ifind_quote.price}", flush=True)
    elif _ifind_configured():
        print("ifind: unavailable", flush=True)
    else:
        print("ifind: not configured (fallback provider is allowed)", flush=True)

    if fallback_quote is not None:
        print(
            f"market-data: OK provider={provenance.provider} live={provenance.is_live}",
            flush=True,
        )
    else:
        print(f"market-data: unavailable ({provenance.error_message})", flush=True)

    # Historical bars, carried over from the older root-level script this
    # replaces.  Informational only: a live quote already proves the session is
    # reachable, and failing here would change when the scheduled job alarms --
    # a decision for whoever owns that alarm, not a side effect of this probe.
    kline = await asyncio.to_thread(ifind.get_kline, code, count=3)
    if kline:
        latest = kline[-1]
        print(
            f"ifind-kline: OK {len(kline)} bars, latest "
            f"{latest.get('date')} close={latest.get('close')}",
            flush=True,
        )
    else:
        print("ifind-kline: no data", flush=True)

    if require_ifind and (ifind_quote is None or not ifind_quote.price):
        return 2
    return 0 if fallback_quote is not None else 1


def main() -> int:
    args = parse_args()
    return asyncio.run(verify(args.code, require_ifind=args.require_ifind))


if __name__ == "__main__":
    raise SystemExit(main())
