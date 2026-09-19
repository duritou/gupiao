"""Verify live A-share data sources for the daily Task Scheduler job.

The check is safe to run every morning. It respects the official trading
calendar when available and only fails on a trading day when no real-time quote
can be obtained from any provider.

It reports which provider answered rather than asserting a specific one: the
chain is ranked dynamically by observed reliability, and naming a winner here
would just be a second place for that ranking to drift out of sync with.

iFind (同花顺 QuantAPI) was removed from the chain on 2026-09-19 when the
account expired; the checks that named it are gone with it.
"""

from __future__ import annotations

import argparse
import asyncio
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
from src.infrastructure.market_data.source_manager import source_manager  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify live A-share quote and K-line sources.")
    parser.add_argument("--code", default="600000.SH", help="A-share symbol used for the probe.")
    return parser.parse_args()


async def verify(code: str) -> int:
    calendar = await get_trading_day_status()
    print(
        f"calendar: trading_day={calendar.is_trading_day} source={calendar.source}",
        flush=True,
    )
    if not calendar.is_trading_day:
        print("verification skipped: non-trading day", flush=True)
        return 0

    quote, provenance = await source_manager.get_realtime_quote(code)
    if quote is not None:
        print(
            f"market-data: OK provider={provenance.provider} live={provenance.is_live}",
            flush=True,
        )
    else:
        print(f"market-data: unavailable ({provenance.error_message})", flush=True)

    # Historical bars.  Informational only: a live quote already proves the
    # session is reachable, and failing here would change when the scheduled
    # job alarms -- a decision for whoever owns that alarm.
    klines, kline_provenance = await source_manager.get_kline(code, count=3)
    if klines:
        latest = klines[-1]
        print(
            f"market-data-kline: OK provider={kline_provenance.provider} "
            f"{len(klines)} bars, latest {latest.get('date')} close={latest.get('close')}",
            flush=True,
        )
    else:
        print(
            f"market-data-kline: no data ({kline_provenance.error_message})",
            flush=True,
        )

    return 0 if quote is not None else 1


def main() -> int:
    args = parse_args()
    return asyncio.run(verify(args.code))


if __name__ == "__main__":
    raise SystemExit(main())
