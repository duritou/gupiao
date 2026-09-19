"""Backfill reference-index bars into the local index_daily table.

Thin CLI over `src.infrastructure.market_data.index_sync`, which the daily task
also calls -- one implementation, so the manual backfill and the scheduled
refresh can never drift apart.

The learning label scores against the equal-weight universe and needs none of
this.  These series exist so a human comparing the strategy to 沪深300 can do it
offline and reproducibly, instead of the number depending on whether a network
fetch happened to succeed during that run.

Idempotent: existing bars are never overwritten.

Usage:
    .venv\\Scripts\\python.exe scripts\\backfill_index_daily.py
    .venv\\Scripts\\python.exe scripts\\backfill_index_daily.py --days 600 --codes 000300.SH 000905.SH
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.market_data.index_sync import (  # noqa: E402
    DEFAULT_INDEX_CODES,
    sync_reference_indices,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill local reference-index bars.")
    parser.add_argument("--codes", nargs="*", default=list(DEFAULT_INDEX_CODES))
    parser.add_argument("--days", type=int, default=600, help="How far back to reach.")
    parser.add_argument("--chunk", type=int, default=365, help="Days per request window.")
    args = parser.parse_args()

    print(f"[index] 回填 {args.codes}  最近 {args.days} 天")
    result = await sync_reference_indices(
        args.codes, days=args.days, chunk_days=args.chunk
    )
    for code, summary in result["synced"].items():
        print(
            f"  {code}: 拉到 {summary['fetched']} 行, "
            f"本地 {summary['bars_before']} -> {summary['bars_after']} "
            f"({summary['first_date']} .. {summary['last_date']})"
        )
    for error in result["errors"]:
        print(f"  错误: {error}")
    if not result["synced"]:
        print("  未回填任何指数。")
        return 1
    return 0 if all(s["bars_after"] for s in result["synced"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
