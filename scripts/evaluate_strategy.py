"""Score the live strategy on the decisions it actually recorded.

Read-only.  Prints the segments rather than a headline number, because the
record spans configurations that are not comparable: gates that could never
open and 67% data coverage were both fixed on 2026-09-19, and rows written
before the equal-weight switch carry 沪深300 excess.

A sanity check worth repeating whenever this is read: sampling random stocks on
the same dates should give a mean excess near zero.  If it does not, the
benchmark is biased and nothing else here means anything.

Usage:
    .venv\\Scripts\\python.exe scripts\\evaluate_strategy.py
    .venv\\Scripts\\python.exe scripts\\evaluate_strategy.py --start 2026-09-19
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.explain.strategy_evaluation import evaluate_decisions  # noqa: E402
from src.infrastructure.storage.market_database import DB_PATH  # noqa: E402


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.3f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate recorded strategy decisions.")
    parser.add_argument("--start", default="2026-07-01", help="First decision date.")
    parser.add_argument("--horizon", type=int, default=5, help="Forward sessions.")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON.")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        result = evaluate_decisions(
            conn, start_date=args.start, horizon_days=args.horizon
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(
        f"决策 {result.total_decisions} 条, 可评估 {result.evaluated} 条, "
        f"无结果跳过 {result.skipped_no_outcome} 条 "
        f"(持有期 {result.horizon_days} 个交易日)"
    )
    print()
    print("按 strategy_version 分段 —— 不得合并阅读")
    for name, summary in result.by_strategy_version.items():
        print(
            f"  {name or '(未标注)':<28} n={summary.get('n', 0):<6} "
            f"命中率={summary.get('hit_rate')} 平均超额={_pct(summary.get('mean_excess'))}"
        )
    print()
    print("按基准口径分段 —— 不得合并阅读")
    for name, summary in result.by_benchmark_basis.items():
        print(
            f"  {name:<16} n={summary.get('n', 0):<6} "
            f"命中率={summary.get('hit_rate')} 平均超额={_pct(summary.get('mean_excess'))}"
        )
    print()
    print("评分十分位 —— 平均超额是这里的有效指标")
    for decile in result.score_deciles:
        print(
            f"  D{decile['decile']:<2} {decile['score_min']:>6.1f}~{decile['score_max']:<6.1f} "
            f"n={decile['n']:<5} 平均超额={_pct(decile['mean_excess'])}"
        )
    print()
    print("门禁归因 —— 放行后的平均超额(正数=闸门有代价, 负数=闸门省了钱)")
    for entry in result.gate_attribution:
        print(
            f"  {entry['reason']:<32} n={entry['n']:<6} "
            f"{_pct(entry['mean_excess_if_released'])}"
        )
    if result.notes:
        print()
        for note in result.notes:
            print(f"  注意: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
